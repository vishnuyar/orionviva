"""Actual PDF capture, retained source reading, accepted posting and native SQL fixture."""
from io import BytesIO
from pathlib import Path
from decimal import Decimal
from dataclasses import replace
import json
from reportlab.pdfgen.canvas import Canvas
from viva.ingest.raw_store import RawStore
from viva.ledger import Ledger
from viva.ledger.events import account_opened, document_captured, read_recorded, Provenance
from viva.ledger.postings import simple_transaction
from viva.ingest.paystub_projector import post_paystub
from viva.ingest.brokerage_projector import post_brokerage
from viva.investment.healing import heal_after_source
from viva.investment.extraction import parse
from test_payroll_counterpart import payroll_data, plan_facts, facts, sf
from test_nonbank_funding import source_packet
from viva.ingest.brokerage import from_brokerage_json


def pdf_bytes(packet):
    stream=BytesIO();canvas=Canvas(stream,pagesize=(612,792),invariant=1)
    canvas.setFont('Helvetica',8);y=770
    canvas.drawString(24,y,'SYNTHETIC TEST SOURCE - NOT ISSUED BY AN INSTITUTION');y-=14
    def printed(value,path=''):
        if type(value) is dict and set(value) in ({'raw','page'},{'raw','page','role'}):
            return [path+': '+str(value['raw'])]
        if type(value) is dict:return [line for key,item in value.items() for line in printed(item,path+'/'+key)]
        if type(value) is list:return [line for index,item in enumerate(value) for line in printed(item,path+'/'+str(index))]
        return [path+': '+str(value)]
    for line in printed(packet):
        for offset in range(0,len(line),110):
            if y<20:raise ValueError('one-page fixture source exceeds declared page')
            canvas.drawString(24,y,line[offset:offset+110]);y-=7
    canvas.showPage();canvas.save();return stream.getvalue()


def capture(ledger,raw,output,name,kind,packet,when):
    data=pdf_bytes(packet);document=raw.put(data)
    (output/name).write_bytes(data)
    ledger.append(document_captured(document,name,len(data),kind,1.0,when,Provenance(doc_id=document)))
    return document


def reading(ledger,document,packet,when,version):
    ledger.append(read_recorded(document,'offline-fixture',version,'document',json.dumps(packet),0,0,0,True,None,when,Provenance(doc_id=document),usage_reported=False))


def fixture(root,output):
    output.mkdir(parents=True,exist_ok=True);ledger=Ledger.open(root/'events.jsonl','synthetic-only');raw=RawStore.open(root/'raw','synthetic-only')
    ledger.append(account_opened('bank','depository','Synthetic bank','USD','2021-01-01'))
    accounts=[]
    for month,reference in enumerate(('PLAN-A','PLAN-B','PLAN-C'),1):
        when=f'2021-{month:02d}-25';end=f'2021-{month:02d}-'+('28' if month==2 else '31');start=f'2021-{month:02d}-01'
        bank=capture(ledger,raw,output,reference+'-bank.pdf','bank_statement',{'account':'bank','date':when,'net_salary':'12450','currency':'USD'},when)
        ledger.append(simple_transaction('bank','12450','Synthetic salary net',when,provenance=Provenance(doc_id=bank,page=1)))
        packet=payroll_data();packet.update(pay_date_raw=when,period_start_raw=start,period_end_raw=end)
        source=packet['payroll_source'];source['schema']='payroll-source-v2';source['headers'].update(source_reference=sf('PAY-'+reference),pay_date=sf(when),period_start=sf(start),period_end=sf(end));source['deductions'][2].update(destination_reference=sf(reference),contribution_reference=sf('CONTRIB-'+reference))
        document=capture(ledger,raw,output,reference+'-payroll.pdf','pay_stub',packet,when);reading(ledger,document,packet,when,'extract:paystub-base-v2+paystub-v2')
        assert post_paystub(ledger,facts(packet,doc=document)).action=='posted'
        plan=plan_facts();source=plan.investment_source.to_dict();source['headers'].update(account_reference=sf(reference),period_start=sf(start),period_end=sf(end),as_of=sf(end),opening_cash=sf('300000'),closing_cash=sf('300975'));source['rows'][0].update(date=sf(when),printed_reference=sf('CONTRIB-'+reference),counterpart_reference=sf('PAY-'+reference));source['rows'][1]['date']=sf(when)
        plan=replace(plan,account_number=reference,account_ref=reference,opening_cash=Decimal('300000'),cash=Decimal('300975'),total=Decimal('301000'),as_of=end,activity=[replace(row,date=when) for row in plan.activity],investment_source=parse(source))
        printed={'headers':dict(source['headers']),'positions':source['positions'],'rows':source['rows']}
        document=capture(ledger,raw,output,reference+'-initial-plan.pdf','brokerage_statement',printed,end)
        plan=replace(plan,doc_id=document);posted=post_brokerage(ledger,plan);assert posted.action=='posted',posted;heal_after_source(ledger,document);accounts.append(posted.account)
    for origin,destination,amount,when,opening_source,opening_destination,reference in [('PLAN-A','PLAN-B','185973.66','2022-12-31','300975','300975','ROLLOVER-023'),('PLAN-B','PLAN-C','212855.52','2024-06-30','486948.66','300975','ROLLOVER-041')]:
        for incoming,account,counterpart,opening,closing in [(False,origin,destination,Decimal(opening_source),Decimal(opening_source)-Decimal(amount)),(True,destination,origin,Decimal(opening_destination),Decimal(opening_destination)+Decimal(amount))]:
            packet=source_packet(incoming,reference=reference,counterpart=counterpart);end=when;start=when[:7]+'-01'
            packet.update(institution=plan_facts().institution,account_ref=account,account_number=account,cash_raw=str(closing),total_raw=str(closing),opening_cash_raw=str(opening),as_of_raw=end)
            packet['activity'][0].update(date_raw=when,amount_raw=amount)
            source=packet['investment_source'];source['headers'].update(account_reference=sf(account),period_start=sf(start),period_end=sf(end),as_of=sf(end),opening_cash=sf(str(opening)),closing_cash=sf(str(closing)));source['rows'][0].update(date=sf(when),amount=sf(amount))
            name=reference+('-in.pdf' if incoming else '-out.pdf');document=capture(ledger,raw,output,name,'brokerage_statement',packet,end);reading(ledger,document,packet,end,'offline-investment-source-v2')
            parsed,error=from_brokerage_json(json.dumps(packet),document,'en-US','USD');assert error is None,error;posted=post_brokerage(ledger,parsed);assert posted.action=='posted',posted;heal_after_source(ledger,document)
    return ledger,accounts


def annual_fixture(root,output):
    output.mkdir(parents=True,exist_ok=True);ledger=Ledger.open(root/'events.jsonl','synthetic-only');raw=RawStore.open(root/'raw','synthetic-only')
    ledger.append(account_opened('bank','depository','Synthetic bank','USD','2024-01-01'));accounts=[]
    from test_extraction import legacy
    for reference,when,start,end in [('PLAN-B','2024-06-25','2024-01-01','2024-06-30'),('PLAN-C','2024-12-25','2024-07-01','2024-12-31')]:
        bank=capture(ledger,raw,output,reference+'-bank.pdf','bank_statement',{'account':'bank','date':when,'net_salary':'7450','currency':'USD'},when)
        ledger.append(simple_transaction('bank','7450','Synthetic salary net',when,provenance=Provenance(doc_id=bank,page=1)))
        packet=payroll_data();packet.update(pay_date_raw=when,period_start_raw=start,period_end_raw=end,net_raw='7450');packet['deductions'][2]['amount_raw']='6000'
        source=packet['payroll_source'];source['schema']='payroll-source-v2';source['headers'].update(source_reference=sf('PAY-'+reference),pay_date=sf(when),net=sf('7450'),period_start=sf(start),period_end=sf(end));source['deductions'][2].update(amount=sf('6000'),destination_reference=sf(reference),contribution_reference=sf('CONTRIB-'+reference))
        document=capture(ledger,raw,output,reference+'-payroll.pdf','pay_stub',packet,when);reading(ledger,document,packet,when,'extract:paystub-base-v2+paystub-v2');assert post_paystub(ledger,facts(packet,doc=document)).action=='posted'
        plan=plan_facts();source=plan.investment_source.to_dict();source['headers'].update(account_reference=sf(reference),period_start=sf(start),period_end=sf(end),as_of=sf(end),closing_cash=sf('5975'));source['rows'][0].update(date=sf(when),amount=sf('6000'),printed_reference=sf('CONTRIB-'+reference),counterpart_reference=sf('PAY-'+reference));source['rows'][1]['date']=sf(when)
        packet=legacy();packet.update(institution='Synthetic broker',account_ref=reference,account_number=reference,as_of_raw=end,opening_cash_raw='0',cash_raw='5975',total_raw='6000')
        packet['activity']=[{'date_raw':when,'kind':'contribution','amount_raw':'6000','description':'Employee retirement contribution','page':1},{'date_raw':when,'kind':'buy','amount_raw':'25','instrument':'TEST-SEC','description':'Synthetic investment purchase','page':1}]
        packet['investment_source']=source
        document=capture(ledger,raw,output,reference+'-plan.pdf','brokerage_statement',packet,end);reading(ledger,document,packet,end,'offline-investment-source-v1')
        parsed,error=from_brokerage_json(json.dumps(packet),document,'en-US','USD');assert error is None,error;posted=post_brokerage(ledger,parsed);assert posted.action=='posted',posted;heal_after_source(ledger,document);accounts.append(posted.account)
    return ledger,accounts
