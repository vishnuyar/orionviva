import { act, fireEvent, render, renderHook, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useSessionReads } from './useSessionReads';
import { initialSession, sessionReducer } from './session';
import { privateSource } from '../surface/sources';
import { App } from './App';
import sample from '../../../product/viva/surface/fixtures/overview-parity-v1.json';
import { BridgeRefusal, REQUEST_REFUSED } from '../bridge/contracts';

const row = { id:'invented', date:'2026-01-01', description:'Invented activity', account:'invented', account_id:'invented', account_name:'Invented account', direction:'out', exact_value:'1', currency:'USD', display:'USD 1', nature:'spending', treatment:{kind:'spending',name:''}, sentence:'', decided_by:'default', provisional:false, linked:false, category:{id:'other',label:'Other'}, subcategory:{id:'unclassified',label:'Unclassified'}, classification:{grade:'unverified',provenance:'default'}, tags:[], evidence_links:[{document_id:'invented-doc',label:'invented.pdf',relation:'attests',page:'2',region:''}], transfer:{state:'none'}, actions:[] };
const raw = (offset:number, count=50, revision='invented-revision') => ({ sentence:'Invented recorded activity', items:Array.from({length:Math.min(count,160-offset)},(_,i)=>({...row,id:`invented-${offset+i}`})), beyond:{count:160-Math.min(count,160-offset)}, vocabularies:{categories:{items:[{id:'other',label:'Other'}],complete:true,limit:40},subcategories:{items:[{id:'unclassified',label:'Unclassified',category_id:'other'}],complete:true,limit:200},tags:{items:[],complete:true,limit:40,max_selected:40,max_label_length:80}}, page:{version:1,revision,next_cursor:offset+count<160?`cursor-${offset+count}`:null,cumulative_count:Math.min(offset+count,160),remaining_count:Math.max(0,160-offset-count)} });
const ref = (current:any) => ({current});

async function harness(read: (params:any)=>Promise<any>) {
  const actions=privateSource({readActivity:read} as any).activityActions;
  let state={...initialSession(),requestId:1};
  state={...state,snapshot:{...state.snapshot,activity:await actions.read(50)}};
  const context:any={session:state,dispatch:(action:any)=>{state=sessionReducer(state,action);context.session=state;},requestId:ref(1),activityLimit:ref(50),surfaceRevision:ref(1),priorityGeneration:ref(0),secondaryGeneration:ref(0),jobsGeneration:ref(0),destinationGeneration:ref(0),retryingDestination:ref(null),retryingPriority:ref(null),activityActions:actions,source:null,sourceIdentity:ref(null)};
  const hook=renderHook(()=>useSessionReads(context));
  return {context,hook,state:()=>state,setState:(next:typeof state)=>{state=next;context.session=state;},more:async()=>{await act(async()=>{await hook.result.current.loadMoreActivity();});hook.rerender();}};
}

it('awaits bounded 50-row continuation past 100 through the adapter, hook, reducer and view',async()=>{
  const requests:any[]=[];
  const h=await harness(async(params)=>{requests.push(params);return {data:raw(params.cursor?({"cursor-50":50,"cursor-100":100,"cursor-150":150} as Record<string,number>)[params.cursor]:0)};});
  await h.more(); await h.more(); await h.more();
  const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('Activity unavailable');
  expect(activity.data.movements).toHaveLength(160);
  expect(requests.map(p=>p.limit)).toEqual([50,50,50,50]);
  expect(requests.every(p=>p.page_version===1)).toBe(true);
  expect(activity.data.page?.remainingCount).toBe(0);

});

it('retains prior rows and cursor on a resolved failure and retries the same bounded page',async()=>{
  let fail=true;const requests:any[]=[];
  const h=await harness(async(params)=>{requests.push(params);if(params.cursor&&fail)throw new Error('refused');return {data:raw(params.cursor?50:0)};});
  await h.more();
  const failed=h.state().snapshot.activity;
  if(failed.state!=='ready')throw new Error('prior rows lost');
  expect(failed.data.movements).toHaveLength(50);expect(failed.data.continuationFailed).toBe(true);
  fail=false;await h.more();
  const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('retry unavailable');
  expect(activity.data.movements).toHaveLength(100);
  expect(requests[1]).toEqual(requests[2]);
});

it('reads a focus-seeded initial page then continues with cursor and limit alone',async()=>{
  const requests:any[]=[];
  const source=privateSource({readActivity:async(params:any)=>{
    requests.push(params);
    const data=raw(params.cursor?49:0);
    if(!params.cursor)data.items[49]={...row,id:'invented-159'};
    else{data.page.cumulative_count=100;data.page.remaining_count=60;data.page.next_cursor='cursor-100';}
    return {data};
  }} as any);
  const initial=await source.loadDestination!('activity',50,'invented-159');
  if(initial.activity?.state!=='ready')throw new Error('focused first page unavailable');
  const next=await source.activityActions.read(50,initial.activity.data.page!.nextCursor!);
  if(next.state!=='ready')throw new Error('cursor-only continuation unavailable');
  expect(requests).toEqual([{page_version:1,limit:50,focus:'invented-159'},{page_version:1,limit:50,cursor:'cursor-50'}]);
  const ids=[...initial.activity.data.movements,...next.data.movements].map(m=>m.id);
  expect(ids).toHaveLength(100);expect(new Set(ids).size).toBe(100);
  expect(ids).toContain('invented-49');expect(ids.filter(id=>id==='invented-159')).toHaveLength(1);
});

it('admits only one continuation at a time and rejects delayed pages after a write',async()=>{
  let release!:(value:any)=>void;const delayed=new Promise(resolve=>{release=resolve;});
  const read=vi.fn(async(params)=>params.cursor?delayed:{data:raw(0)});
  const h=await harness(read);
  let first!:Promise<void>,second!:Promise<void>;
  act(()=>{first=h.hook.result.current.loadMoreActivity();second=h.hook.result.current.loadMoreActivity();});
  expect(read).toHaveBeenCalledTimes(2);
  h.context.surfaceRevision.current++;
  release({data:raw(50)});
  await act(async()=>{await Promise.all([first,second]);});
  const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('lost rows');
  expect(activity.data.movements).toHaveLength(50);
});

it.each(['request','source','destination','recovery'])('rejects delayed continuation after %s changes',async(change)=>{
  let release!:(value:any)=>void;const delayed=new Promise(resolve=>{release=resolve;});
  const h=await harness(async(params)=>params.cursor?delayed:{data:raw(0)});
  let pending!:Promise<void>;act(()=>{pending=h.hook.result.current.loadMoreActivity();});
  if(change==='request')h.context.requestId.current++;
  if(change==='source')h.context.sourceIdentity.current={};
  if(change==='destination')h.context.destinationGeneration.current++;
  if(change==='recovery')h.context.priorityGeneration.current++;
  release({data:raw(50)});await act(async()=>{await pending;});
  const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('lost rows');
  expect(activity.data.movements).toHaveLength(50);
});

it.each(['overlap','revision','counts'])('preserves the chain on %s mismatch',async(change)=>{
  const h=await harness(async(params)=>{
    const data=raw(params.cursor?50:0);
    if(params.cursor&&change==='overlap')data.items[0].id='invented-0';
    if(params.cursor&&change==='revision')data.page.revision='other';
    if(params.cursor&&change==='counts')data.page.cumulative_count=110;
    return {data};
  });
  await h.more();const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('lost rows');
  expect(activity.data.movements).toHaveLength(50);
  expect(activity.data.page?.nextCursor).toBe('cursor-50');
  expect(activity.data.continuationFailed).toBe(true);
});

it('keeps an older reader initial list usable and discloses unavailable continuation',async()=>{
  const h=await harness(async(params)=>{if(params.page_version)throw new BridgeRefusal(REQUEST_REFUSED,'unsupported');const data:any=raw(0);delete data.page;data.beyond.count=110;return {data};});
  await h.more();const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('initial legacy unavailable');
  expect(activity.data.movements).toHaveLength(50);
  expect(activity.data.page).toBeUndefined();
});

it('invalidates continuation on revision change and retains exact accumulated omission count',async()=>{
  const h=await harness(async(params)=>({data:raw(params.cursor?50:0)}));
  await h.more();
  const state=h.state();
  const source={} as any;
  const held={...state,source,readRevision:'old'};
  const invalid=sessionReducer(held,{type:'priority-loaded',requestId:1,source,overview:held.snapshot.overview,disclosure:held.snapshot.disclosure,revision:'new',freshness:'current',lifecycle:'equal',retryable:false});
  if(invalid.snapshot.activity.state!=='ready')throw new Error('rows lost');
  expect(invalid.snapshot.activity.data.movements).toHaveLength(100);
  expect(invalid.snapshot.activity.data.page).toBeUndefined();
  expect(invalid.snapshot.activity.data.beyond.count).toBe(60);
  expect(invalid.snapshot.activity.data.continuationInvalidated).toBe(true);
});

it('discovers a changed revision after cursor refusal and refreshes from a focused first page',async()=>{
  let revision='old';const requests:any[]=[];
  const h=await harness(async(params)=>{
    requests.push(params);
    if(params.cursor){revision='new';throw new BridgeRefusal(REQUEST_REFUSED,'stale');}
    return {data:raw(0,50,revision)};
  });
  const source:any={activityActions:h.context.activityActions,loadPriority:vi.fn(async()=>({snapshot:h.state().snapshot,revision:'g-new',freshness:'current',lifecycle:'equal',retryable:false}))};
  h.context.source=source;h.context.sourceIdentity.current=source;h.context.activityFocus=ref('invented-150');
  h.setState({...h.state(),source,readRevision:'g-old',priorityFreshness:'current',destination:'activity'});
  h.hook.rerender();
  await h.more();
  // Publish the reducer's new revision to the coordinator's normal effect.
  await act(async()=>{h.hook.rerender();await Promise.resolve();});
  const activity=h.state().snapshot.activity;
  if(activity.state!=='ready')throw new Error('initial refresh unavailable');
  expect(activity.data.movements).toHaveLength(50);
  expect(activity.data.page?.revision).toBe('new');
  expect(requests.at(-1)).toMatchObject({page_version:1,limit:50,focus:'invented-150'});
  expect(requests.at(-1).cursor).toBeUndefined();
});

it('invalidates a held chain during publication recovery and rereads first 50 on recovery',async()=>{
  const requests:any[]=[];
  const h=await harness(async(params)=>{requests.push(params);return {data:raw(params.cursor?50:0)};});
  const source:any={activityActions:h.context.activityActions};
  h.context.source=source;h.context.sourceIdentity.current=source;h.context.activityFocus=ref('invented-150');
  h.setState({...h.state(),source,readRevision:'held',priorityFreshness:'current',destination:'activity'});
  h.hook.rerender();await h.more();
  const publish=(freshness:'stale'|'current')=>{
    const held=h.state();
    h.setState(sessionReducer(held,{type:'priority-loaded',requestId:1,source,overview:held.snapshot.overview,disclosure:held.snapshot.disclosure,revision:'held',freshness,lifecycle:freshness==='stale'?'rebuilding':'equal',retryable:false}));
  };
  publish('stale');h.hook.rerender();
  const stale=h.state().snapshot.activity;
  if(stale.state!=='ready')throw new Error('held rows lost');
  expect(stale.data.movements).toHaveLength(100);expect(stale.data.page).toBeUndefined();
  await act(async()=>{publish('current');h.hook.rerender();await Promise.resolve();});
  const recovered=h.state().snapshot.activity;
  if(recovered.state!=='ready')throw new Error('recovery unavailable');
  expect(recovered.data.movements).toHaveLength(50);
  expect(requests.at(-1)).toEqual({page_version:1,limit:50,focus:'invented-150'});
});

it('loads later rows and their source links through the actual bridge client and App',async()=>{
  const reads=sample.reads as Record<string,{result:{data:unknown}}>;
  const activityRequests:any[]=[];
  const previous=window.orionVivaBridge;
  window.orionVivaBridge={request:async<T,>(frame:any)=>{
    let value:any={kind:'completed',message:'Done.',state:null,reason:null};
    if(frame.operation==='bridge.open_demo_vault')value={state:'opened',sample:true,frame:{title:'Invented vault',detail:'All records are invented.',leave:'Leave sample'},priority_reads:['overview_accounts']};
    if(frame.operation==='bridge.handshake')value={protocol:'2.0',transport:'json-lines',revision:'invented'};
    if(frame.operation==='viva.surface.capabilities')value={protocol:'2.0',capabilities:[],destinations:{overview:true,accounts:true,activity:true,documents:true,plans:true,review:true,viva:true,trust:true}};
    if(frame.operation==='viva.settings.read')value={state:'ready',locale:'en-US',currency:'USD',adapter:'',model:'',base_url:'',key_set:false,can_send:false};
    if(frame.operation==='viva.surface.read'){
      const surface=frame.payload.surface;
      let data=reads[surface]?.result.data;
      if(surface==='overview_accounts')data={state:'ready',freshness:'current',lifecycle:'equal',revision:'invented',overview:reads.overview.result.data,accounts:reads.overview.result.data,error:''};
      if(surface==='documents')data={...(data as object),documents:[{...(data as any).documents[0],id:'invented-doc',filename:'invented.pdf'}],holds:[]};
      if(surface==='activity'){
        const params=frame.payload.parameters;activityRequests.push(params);
        const offset=({'cursor-50':50,'cursor-100':100,'cursor-150':150} as Record<string,number>)[params.cursor]??0;
        data=raw(offset);
      }
      value={surface,job_id:'invented',data};
    }
    return {protocol:'1.0',request_id:frame.requestId,ok:true,result:value as T};
  }};
  try{
    const app=render(<App/>);
    fireEvent.click(app.getByRole('button',{name:'Open the sample vault'}));
    await waitFor(()=>expect(app.getByRole('note',{name:'Invented vault'})).toBeInTheDocument());
    fireEvent.click(app.getByRole('button',{name:'Transactions'}));
    await waitFor(()=>expect(app.container.querySelectorAll('.activity-movement')).toHaveLength(50));
    for(const count of [100,150,160]){
      fireEvent.click(app.getByRole('button',{name:'Load 50 more'}));
      await waitFor(()=>expect(app.container.querySelectorAll('.activity-movement')).toHaveLength(count));
    }
    expect(activityRequests.map(p=>p.limit)).toEqual([50,50,50,50]);
    expect(app.queryByRole('button',{name:'Load 50 more'})).toBeNull();
    const later=app.container.querySelectorAll('.activity-movement').item(159);
    expect(later.querySelector('button')?.textContent).toContain('Explain');
    expect(later.querySelector('.activity-source')?.textContent).toContain('invented.pdf');
    const sourceButton=later.querySelector('.activity-source button') as HTMLButtonElement;
    fireEvent.click(sourceButton);
    await waitFor(()=>expect(app.getByRole('heading',{name:'Statements & documents'})).toBeInTheDocument());
  }finally{window.orionVivaBridge=previous;}
});
