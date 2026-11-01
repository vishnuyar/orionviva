"""Real source/post/SQL emitters for the cross-tool vocabulary sweeps."""
from contextlib import contextmanager
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import json
import pypdfium2 as pdfium
import sys
import tempfile
from unittest.mock import patch

TESTS=Path(__file__).parent
for directory in (TESTS/'investment_evidence',TESTS/'retirement_funding'):
    if str(directory) not in sys.path:sys.path.append(str(directory))


def _scaled(value,factor,key=''):
    money={'gross','net','amount','opening_cash','closing_cash','market_value','cost_basis','reported_realized_gain',
        'gross_raw','net_raw','amount_raw','opening_cash_raw','cash_raw','total_raw','market_value_raw','cost_basis_raw','realized_gain_raw','net_salary'}
    if type(value) is dict:
        if set(value)=={'raw','page'} and key in money:
            return {**value,'raw':str(Decimal(value['raw'])*factor)}
        return {name:_scaled(item,factor,name) for name,item in value.items()}
    if type(value) is list:return [_scaled(item,factor,key) for item in value]
    if key in money and value is not None:return str(Decimal(value)*factor)
    return value


@lru_cache(maxsize=4)
def source_emitter_results(factor='1'):
    """Scale printed monetary facts before capture; units and row counts stay fixed."""
    import retirement_wire_fixture as source
    from test_wire import source_packet
    from viva.ledger.events import read_recorded,Provenance
    from viva.ledger.instruments import reference_event
    from viva.ingest.instrument_contracts import Source
    from viva.ingest.raw_store import RawStore
    from viva.ingest.brokerage import from_brokerage_json
    from viva.ingest.brokerage_projector import post_brokerage
    from viva.read_store import ReadStore
    from viva.tools import default_registry
    from time import monotonic
    multiplier=Decimal(factor)
    real_capture=source.capture;real_transaction=source.simple_transaction
    def capture(ledger,raw,output,name,kind,packet,when):
        changed=_scaled(packet,multiplier);packet.clear();packet.update(changed)
        return real_capture(ledger,raw,output,name,kind,packet,when)
    def transaction(account,amount,*args,**kwargs):
        return real_transaction(account,str(Decimal(amount)*multiplier),*args,**kwargs)
    with tempfile.TemporaryDirectory(prefix='viva-source-emitter-') as directory:
        root=Path(directory);output=root/'pdfs'
        with patch.object(source,'capture',capture),patch.object(source,'simple_transaction',transaction):
            ledger,plans=source.annual_fixture(root,output)
        raw=RawStore.open(root/'raw','synthetic-only')
        bank=real_capture(ledger,raw,output,'broker-funding.pdf','bank_statement',
            {'account':'bank','date':'2025-01-25','outflow':str(100*multiplier),'reference':'PRINTED-X'},'2025-01-25')
        ledger.append(real_transaction('bank',str(-100*multiplier),'Test investment contribution','2025-01-25',
            provenance=Provenance(doc_id=bank,page=1),source_reference='PRINTED-X',counterparty_reference='BROKER-REF'))
        ledger.append(reference_event('bank','BANK-REF','2025-01-01',Source(bank,1)))
        packet=_scaled(source_packet(),multiplier)
        document=real_capture(ledger,raw,output,'investment.pdf','brokerage_statement',packet,'2025-01-31')
        reply=json.dumps(packet)
        ledger.append(read_recorded(document,'offline-source-emitter','fixture','document',reply,0,0,0,True,None,'2025-01-31',usage_reported=False))
        facts,error=from_brokerage_json(reply,document,'en-US','USD');assert error is None,error
        source_pdf=pdfium.PdfDocument(raw.get(document))
        try:
            facts.validated_source_page_count=len(source_pdf)
        finally:
            source_pdf.close()
        posted=post_brokerage(ledger,facts);assert posted.action=='posted',posted
        with ReadStore.create(root/'reads','synthetic-only') as reads:
            reads.synchronize(ledger.store)
            @contextmanager
            def supplier():
                with reads.open_reader() as revision:yield revision
            registry=default_registry(ledger.projection(),today='2026-01-01',instrument_scope=supplier)
            results=[]
            for name,args in [
                ('read_investment_evidence',{'view':'positions','account':posted.account,'currency':'USD','as_of':'2025-01-31'}),
                ('read_retirement_funding',{'view':'annual_employee_contributions','plans':plans,'currency':'USD','year':2024})]:
                with registry.instrument_runtime.execution(monotonic()+2):result=registry.call(name,args)
                assert result.ok and result.figures,result.to_dict()
                results.append(result)
            return tuple(results)
