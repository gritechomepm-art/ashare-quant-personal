import test from 'node:test';
import assert from 'node:assert/strict';
import {checkAndDispatch,beijingClock} from '../src/index.mjs';

const NOW=new Date('2026-11-23T11:45:00.000Z'); // 19:45 Beijing
const json=(x,code=200)=>new Response(JSON.stringify(x),{status:code,headers:{'content-type':'application/json'}});
const mock=({asof='2026-11-20',scope='FULL_A',runs=[],failure=null}={})=>{
 const calls=[];
 const fetcher=async(url,opts={})=>{
   calls.push({url,opts});
   if(url.includes('raw.githubusercontent.com'))return json({schema:1,asof,board_scope:scope});
   if(url.includes('/runs?'))return json({workflow_runs:runs});
   if(opts.method==='POST')return failure?new Response('token denied',{status:403}):new Response(null,{status:204});
   throw Error('Unexpected request: '+url);
 };
 return {calls,fetcher};
};

test('Beijing clock is date-based and weekends are ignored',async()=>{
 assert.deepEqual(beijingClock(NOW).date,'2026-11-23');
 const m=mock();const r=await checkAndDispatch({now:new Date('2026-11-22T11:45:00Z'),secret:'test',fetcher:m.fetcher});
 assert.equal(r.status,'MARKET_WEEKEND');assert.equal(m.calls.length,0);
});
test('fresh, certified EOD never dispatches',async()=>{
 const m=mock({asof:'2026-11-23',scope:'SH_SZ_MAIN'});
 const r=await checkAndDispatch({now:NOW,secret:'test',fetcher:m.fetcher});
 assert.equal(r.status,'EOD_FRESH');assert.equal(m.calls.length,1);
});
test('active GitHub EOD run suppresses duplicate cloud dispatch',async()=>{
 const m=mock({runs:[{event:'schedule',status:'in_progress',head_branch:'main',created_at:'2026-11-23T10:20:00Z'}]});
 const r=await checkAndDispatch({now:NOW,secret:'test',fetcher:m.fetcher});
 assert.equal(r.status,'EOD_IN_PROGRESS');assert.ok(m.calls.every(c=>!c.opts.method));
});
test('one external dispatch per Beijing day, even on 2nd Cron',async()=>{
 const m=mock({runs:[{event:'workflow_dispatch',status:'completed',conclusion:'failure',head_branch:'main',created_at:'2026-11-23T11:47:00Z'}]});
 const r=await checkAndDispatch({now:new Date('2026-11-23T13:45:00Z'),secret:'test',fetcher:m.fetcher});
 assert.equal(r.status,'DISPATCH_ALREADY_RECORDED');
 assert.ok(m.calls.every(c=>!c.opts.method));
});
test('stale EOD invokes only the fixed workflow on current main',async()=>{
 const m=mock();
 const r=await checkAndDispatch({now:NOW,secret:'local-test-secret',fetcher:m.fetcher,log:{info(){}}});
 assert.equal(r.status,'DISPATCHED');
 const calls=m.calls.filter(c=>c.opts.method==='POST');
 assert.equal(calls.length,1);
 assert.equal(calls[0].url,'https://api.github.com/repos/gritechomepm-art/ashare-quant-personal/actions/workflows/baostock-backfill.yml/dispatches');
 assert.deepEqual(JSON.parse(calls[0].opts.body),{ref:'main'});
 assert.equal(calls[0].opts.headers.Authorization,'Bearer local-test-secret');
});
test('missing secret and GitHub permission errors fail closed',async()=>{
 const m=mock();
 await assert.rejects(()=>checkAndDispatch({now:NOW,fetcher:m.fetcher}),/secret not configured/);
 const err=mock({failure:true});
 await assert.rejects(()=>checkAndDispatch({now:NOW,secret:'dummy',fetcher:err.fetcher}),/HTTP 403/);
});
test('bad file and missing run list never dispatch a false success',async()=>{
 const f=async()=>json({schema:1,asof:'2026-11-20'});
 await assert.rejects(()=>checkAndDispatch({now:NOW,secret:'dummy',fetcher:f}),/Malformed EOD run list/);
});
