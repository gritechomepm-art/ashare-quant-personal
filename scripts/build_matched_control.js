#!/usr/bin/env node
/* Research-only stock-and-month matched RANDOM NON-SIGNAL control.
 * Exact same V2.2 tradeAt mechanics: signal-date ATR, no-chase next open,
 * T+1, conservative stop/target, fees, slippage, holding period.
 * Entry gate only is replaced with "not a signal". Does NOT change any
 * production signal/threshold/backtest file.
 */
'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const ROOT=path.resolve(__dirname,'..');
const BT=require('../assets/backtest-v2.js');
const CUTOFF='2026-07-21', SEED='ashare-control-v1-2026-11-21';
const outfile=process.argv[2]||path.join(ROOT,'site/data/evidence_control.json');
const limit=Number(process.argv[3]||0);
const html=fs.readFileSync(path.join(ROOT,'index.html'),'utf8');
const start=html.indexOf('function valMA('),end=html.indexOf('function graph(a){',start);
if(start<0||end<0)throw Error('Missing frozen indicator / entry rules');
const {enrichJS,entrySignalJS}=new Function(html.slice(start,end)+'\nreturn {enrichJS,entrySignalJS};')();
function chooseIndex(code,date,count){
 const h=crypto.createHash('sha256').update(SEED+'|'+code+'|'+date).digest();
 return h.readUInt32BE(0)%count;
}
const noSignal=()=>({buy:true}); // Only the entry *classification* differs.
const groups={train:[],historical_test:[]};
let scanned=0,invalid=0,referenceTrades=0,notMatched=0;
const raw=fs.readdirSync(path.join(ROOT,'data/history')).filter(x=>/^\d{6}\.json$/.test(x)).sort();
const files=limit>0?raw.slice(0,limit):raw;
for(const filename of files){
 scanned++;
 try{
  const content=JSON.parse(fs.readFileSync(path.join(ROOT,'data/history',filename),'utf8'));
  const bars=content.bars||[];
  if(bars.length<100 || !bars.every((b,i)=>/^\d{4}-\d{2}-\d{2}$/.test(b.date)&&
    (!i||b.date>bars[i-1].date)&&
    ['open','high','low','close','volume'].every(k=>Number.isFinite(Number(b[k]))&&Number(b[k])>=0)&&
    Number(b.open)>0&&Number(b.close)>0&&Number(b.high)>0&&Number(b.low)>0)) { invalid++;continue; }
  const a=enrichJS(bars),code=filename.slice(0,6),idx=a.findIndex(x=>x.date>=CUTOFF);
  const cutoff=idx<0?a.length:idx;
  if(cutoff<65)continue;
  const study=BT.study(a,code,entrySignalJS,cutoff);
  // Use the same 3-day paired, 10-day-complete original signal cohort.
  const reference=[
   ...study.paired.train[3].map(t=>({part:'train',trade:t})),
   ...study.paired.test[3].map(t=>({part:'historical_test',trade:t}))
  ];
  if(!reference.length)continue;
  const pools={train:new Map(),historical_test:new Map()};
  // Candidate selection uses only signal-date conditions and next-session open.
  // Control may be reused in a given stock/month; bootstrap accounts for clustering.
  for(let i=64;i+11<a.length;i++){
   const entering=i+1;
   const part=entering<cutoff?'train':'historical_test';
   if(part==='train'&&entering+10>=cutoff)continue;
   if(part==='historical_test'&&entering<cutoff)continue;
   if(entrySignalJS(a.slice(0,i+1)).buy)continue;
   const t=BT.tradeAt(a,code,3,i,noSignal);
   if(!t)continue; // same no-chase rule, same completed window
   const month=a[i].date.slice(0,7);
   if(!pools[part].has(month))pools[part].set(month,[]);
   pools[part].get(month).push(t);
  }
  for(const {part,trade} of reference){
   referenceTrades++;
   const month=trade.signalDate.slice(0,7);
   const pool=pools[part].get(month)||[];
   if(!pool.length){notMatched++;continue;}
   const control=pool[chooseIndex(code,trade.signalDate,pool.length)];
   groups[part].push({
    code, signalDate:trade.signalDate, controlDate:control.signalDate,
    netSignalPct:trade.returnPct, netControlPct:control.returnPct,
    differencePp:trade.returnPct-control.returnPct
   });
  }
 }catch(e){invalid++;console.warn('Skipped control history '+filename+': '+String(e.message).slice(0,130));}
}
function prng(seed){
 let x=seed>>>0;
 return ()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296;};
}
function percentile(a,p){if(!a.length)return null;const k=(a.length-1)*p,l=Math.floor(k),r=Math.ceil(k);return a[l]+(a[r]-a[l])*(k-l);}
function results(rows){
 const codes=new Map();
 for(const r of rows){
  let v=codes.get(r.code);
  if(!v){v={count:0,sum:0};codes.set(r.code,v);}
  v.count++;v.sum+=r.differencePp;
 }
 const n=rows.length,stockCount=codes.size;
 const sum=(key)=>n?rows.reduce((acc,row)=>acc+row[key],0)/n:null;
 const ans={matchedPairs:n,distinctStocks:stockCount,
  signalAvgNetPct:sum('netSignalPct'),controlAvgNetPct:sum('netControlPct'),
  signalMinusControlPp:sum('differencePp'),
  clusterBootstrap95Pp:null,clusterBootstrapReplicates:0,
  status:n>=100&&stockCount>=30?'EXPLORATORY_ONLY':'INSUFFICIENT_MATCHES'};
 if(!n||!stockCount)return ans;
 // Resample entire stock clusters, NOT individual signals.
 const stocks=[...codes.values()];
 const draws=1000,random=prng(0xa5122026);
 const values=[];
 for(let k=0;k<draws;k++){
  let count=0,total=0;
  for(let j=0;j<stockCount;j++){
   const v=stocks[Math.floor(random()*stockCount)];
   count+=v.count;total+=v.sum;
  }
  if(count)values.push(total/count);
 }
 values.sort((a,b)=>a-b);
 ans.clusterBootstrap95Pp=[percentile(values,.025),percentile(values,.975)];
 ans.clusterBootstrapReplicates=values.length;
 return ans;
}
const report={
 schema:1,kind:'matched random non-signal research control / not a tradable strategy',
 generated_at:new Date().toISOString(),fixed_historical_cutoff:CUTOFF,
 seed:SEED, control_definition:'Deterministic SHA256 seeded pseudo-random non-BUY-WATCH signal date within the same stock, calendar month, and historic split; the signal candidate must have a valid next-session open inside its 0.25xATR no-chase corridor. Every matched trade requires a full 10-session lookahead and the exact original 3-day execution logic. Duplicate controls within a stock/month are permitted.',
 metric:'Paired net return percentage-point difference after identical 100-share fees, T+1, signal-day ATR, stop/target, trend exit and slippage assumptions.',
 uncertainty:'95% percentile bootstrap by whole stock code (1000 fixed-seed cluster resamples), not 8,000 independent trade observations. Does not adjust for market-wide common dates or parameter search.',
 historical_warning:'The entire historic holdout has already been examined for strategy research. These controls do NOT constitute independent prospective validation. No claim that one model is superior is authorized.',
 scanned_files:scanned,invalid_files:invalid,baseline_reference_trades:referenceTrades,unmatched_signals:notMatched,
 results:{train:results(groups.train),historical_test:results(groups.historical_test)},
 rules_frozen:true,auto_activate:false
};
fs.mkdirSync(path.dirname(outfile),{recursive:true});
fs.writeFileSync(outfile,JSON.stringify(report,null,2)+'\n');
console.log('Matched non-signal control:',JSON.stringify({files:scanned,invalid,referenceTrades,unmatched:notMatched,train:report.results.train,test:report.results.historical_test,output:outfile}));
