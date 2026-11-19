#!/usr/bin/env node
/* V2.2 – fixed hypotheses against original single-stock 3-day paired signals.
 * Research-only, no mutation of entry rules or quote ingestion.
 * The historical test set was already reviewed in V2.1, so ALL filter results
 * on that set are exploratory; prospective decision remains unavailable.
 */
'use strict';
const fs=require('node:fs'),path=require('node:path');
const ROOT=path.resolve(__dirname,'..');
const BT=require('../assets/backtest-v2.js');
const QR=require('../assets/entry-quality-v22.js');
const historyDir=path.join(ROOT,'data','history');
const output=process.argv[2] || path.join(ROOT,'site','data','entry_quality_v22.json');
const testLimit=Number(process.argv[3]||0);
const HISTORIC_SPLIT='2026-07-21';
const FORWARD_START='2026-11-20';
const html=fs.readFileSync(path.join(ROOT,'index.html'),'utf8');
const a=html.indexOf('function valMA('),b=html.indexOf('function graph(a){',a);
if(a<0||b<=a)throw Error('Cannot locate original indicators and entry rule');
const {enrichJS,entrySignalJS}=new Function(html.slice(a,b)+'\nreturn {enrichJS,entrySignalJS};')();

const files=fs.readdirSync(historyDir).filter(x=>/^\d{6}\.json$/.test(x)).sort();
const chosen=Number.isInteger(testLimit)&&testLimit>0?files.slice(0,testLimit):files;
const raw={train:[],test:[]};let eligible=0,skipped=0;
const lastDates=[];
for(const file of chosen){
 try{
  const record=JSON.parse(fs.readFileSync(path.join(historyDir,file),'utf8'));
  const bars=record.bars;
  if(!Array.isArray(bars)||bars.length<100){skipped++;continue;}
  if(!bars.every((p,i)=>/^\d{4}-\d{2}-\d{2}$/.test(p.date)&&
   (!i||p.date>bars[i-1].date)&&
   ['open','high','low','close','volume'].every(k=>Number.isFinite(Number(p[k])))&&
   Number(p.open)>0&&Number(p.high)>0&&Number(p.low)>0&&Number(p.close)>0)) {
    skipped++;continue;
   }
  const splitAt=bars.findIndex(x=>x.date>=HISTORIC_SPLIT);
  const cutoff=splitAt<0?bars.length:splitAt;
  if(cutoff<65){skipped++;continue;}
  const enriched=enrichJS(bars);
  const study=BT.study(enriched,file.slice(0,6),entrySignalJS,cutoff);
  eligible++;lastDates.push(enriched.at(-1).date);
  for(const p of ['train','test']){
   for(const trade of study.paired[p]['3']){
     raw[p].push(QR.annotate(trade,enriched));
   }
  }
 }catch(e){skipped++;console.warn('Skipped '+file+': '+String(e.message).slice(0,160));}
}
if(!eligible)throw Error('No valid real history available; research cannot proceed');
const summary={train:QR.stats(raw.train),test:QR.stats(raw.test)};
const candidates=QR.evaluateRuleTables(raw.train,raw.test);
const prospective=QR.prospectiveState(raw.test,FORWARD_START);
const criteria={
 minTrainSignals:100,minTrainSymbols:30,
 // Averages must improve on the TRAIN-only historical baseline to qualify for a
 // *research hypothesis*. It is still not a verified trading recommendation.
 ruleEligibility:'研究候选需要样本内至少100笔、30只股票且样本内平均净收益高于原策略；即使满足，也只可继续前瞻研究',
 historicalOosUsedBefore:true,automaticStrategyPromotion:false,
 };
const baseline=summary.train.avgNetPct;
const candidatesWithGate=candidates.map(c=>({
  ...c,
  trainDeltaPp:baseline==null||c.train.avgNetPct==null?null:c.train.avgNetPct-baseline,
  researchEligible:c.id!=='baseline'&&c.train.count>=criteria.minTrainSignals&&
    c.train.distinctStocks>=criteria.minTrainSymbols&&
    c.train.avgNetPct!==null&&baseline!==null&&c.train.avgNetPct>baseline,
  // Not a pristine validation result, since historic test was inspected during V2.1.
  historicalTestIsIndependent:false
}));
const data={
 schema:1,model:'A-share V2.2 entry-quality diagnostic',
 source:'Previously committed public historical daily bars; same signal and fill engine as V2.0/V2.1.',
 generatedAt:new Date().toISOString(),
 historicCutoff:HISTORIC_SPLIT,forwardStart:FORWARD_START,
 historyFilesRead:chosen.length,eligibleHistoryFiles:eligible,skippedHistoryFiles:skipped,
 lastHistoryDate:lastDates.sort().at(-1)||null,
 baseline:summary,candidates:candidatesWithGate,prospective,
 criteria,
 method:'Matched 3-day trade cohort: each accepted entry has complete 10-session future observation; no train exit crosses 2026-07-21. 100 shares with original fees, slippage and signal-day ATR. Single-variable filters are decided at the signal bar only. No combination search.',
 limitations:'Research cohorts may overlap across signals/stocks, without portfolio capital constraints. Original 2026 historical holdout was already reviewed in V2.1; candidates cannot be considered independently validated. Missing history, suspensions, price limits, delistings, corporate actions, and friction modeling remain limitations.',
 releaseDecision:'KEEP_V2_1_LIVE_STRATEGY',
 candidateAutoApply:false
};
fs.mkdirSync(path.dirname(output),{recursive:true});
fs.writeFileSync(output,JSON.stringify(data,null,2)+'\n');
console.log('Entry quality V2.2:',JSON.stringify({
 files:chosen.length,eligible,skipped,cutoff:HISTORIC_SPLIT,
 trainCount:summary.train.count,testCount:summary.test.count,
 trainTrend:summary.train.trendExitPct,testTrend:summary.test.trendExitPct,
 rules:candidatesWithGate.map(x=>({id:x.id,trainCount:x.train.count,trainAvg:x.train.avgNetPct,
  historicTestCount:x.test.count,historicTestAvg:x.test.avgNetPct,trainCandidate:x.researchEligible})),
 forwardCount:prospective.completedPairedSignals,output
}));
