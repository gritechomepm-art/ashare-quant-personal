#!/usr/bin/env node
/* Reproducible historical cohort. Reads only public, committed daily bars.
 * Never fetches prices or adjusts signal thresholds, and never writes to git.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const BT = require('../assets/backtest-v2.js');
const ROOT = path.resolve(__dirname, '..');
const historyDir = path.join(ROOT, 'data', 'history');
const outPath = process.argv[2] || path.join(ROOT, 'site', 'data', 'backtest_v2.json');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const start = html.indexOf('function valMA('), end = html.indexOf('function graph(a){', start);
if (start < 0 || end <= start) throw Error('Cannot access current UI indicator definitions');
const {enrichJS,entrySignalJS} = new Function(html.slice(start,end)+'\nreturn {enrichJS,entrySignalJS};')();
const buckets = () => Object.fromEntries(BT.HORIZONS.map(h => [h, []]));
const paired = {train:buckets(), test:buckets()};
const nonoverlap = {all:buckets(), train:buckets(), test:buckets()};
const pairSymbols = {train:new Set(),test:new Set()};
const all = [], dateFrequency = new Map();
let invalid = 0, scanned = 0;
const files = fs.readdirSync(historyDir).filter(x => /^\d{6}\.json$/.test(x)).sort();
for (const filename of files) {
  scanned++;
  try {
    const row = JSON.parse(fs.readFileSync(path.join(historyDir,filename),'utf8'));
    const bars = row.bars;
    if (!Array.isArray(bars) || bars.length < 100) {invalid++;continue;}
    if (!bars.every((b,i)=>/^\d{4}-\d{2}-\d{2}$/.test(b.date)&&
        (!i || b.date > bars[i-1].date) &&
        ['open','high','low','close','volume'].every(k=>Number.isFinite(Number(b[k])))&&
        Number(b.open)>0 && Number(b.high)>0 && Number(b.low)>0 && Number(b.close)>0)) {
      invalid++;continue;
    }
    const code=filename.slice(0,6);
    all.push({code,bars});
    for (const b of bars) dateFrequency.set(b.date,(dateFrequency.get(b.date)||0)+1);
  } catch(e) {invalid++;}
}
if (!all.length) throw Error('No valid history — refusing to publish synthetic study');
const threshold = Math.max(1, Math.ceil(all.length*.25));
let calendar=[...dateFrequency].filter(([,count])=>count>=threshold).map(([date])=>date).sort();
if (calendar.length < 100) throw Error('Insufficient common calendar to define chronological split');
const cutDate=calendar[Math.floor(calendar.length*.70)];
let usable=0, staleForHoldout=0, latest='', earliest='';
for (const {code,bars} of all) {
  try {
    const arr=enrichJS(bars);
    const splitIndex=arr.findIndex(b=>b.date>=cutDate);
    const cutoff=splitIndex<0?arr.length:splitIndex;
    if (cutoff<65) {invalid++;continue;}
    if (cutoff>=arr.length) staleForHoldout++;
    usable++;
    latest=!latest||latest<arr.at(-1).date?arr.at(-1).date:latest;
    earliest=!earliest||earliest>arr[0].date?arr[0].date:earliest;
    const s=BT.study(arr,code,entrySignalJS,cutoff);
    for (const part of ['train','test']) {
      if (s.paired[part]['3'].length) pairSymbols[part].add(code);
      for (const h of BT.HORIZONS) {
        paired[part][h].push(...s.paired[part][h]);
      }
    }
    for (const part of ['all','train','test']) for (const h of BT.HORIZONS) {
      nonoverlap[part][h].push(...s.sequential[part][h]);
    }
  } catch(e) {invalid++; console.warn('Study skipped:',code,String(e.message).slice(0,120));}
}
const clean=(arr,drawdown=false)=>{
  const value=BT.evaluate(arr,drawdown);
  if (value.profitFactor === Infinity) value.profitFactor='∞';
  return value;
};
const metrics={paired:{},sequential:{}};
for (const part of ['train','test']){
  metrics.paired[part]=Object.fromEntries(BT.HORIZONS.map(h=>[h,clean(paired[part][h],false)]));
}
for (const part of ['all','train','test']){
  metrics.sequential[part]=Object.fromEntries(BT.HORIZONS.map(h=>[h,clean(nonoverlap[part][h],false)]));
}
const train=metrics.paired.train,test=metrics.paired.test;
const bothSufficient=train['3'].count>=100&&test['3'].count>=100&&pairSymbols.train.size>=30&&pairSymbols.test.size>=30;
const comparison={
  oos_5_minus_3_avg_return_pp:test['3'].count ? test['5'].avgReturnPct-test['3'].avgReturnPct : null,
  train_5_minus_3_avg_return_pp:train['3'].count ? train['5'].avgReturnPct-train['3'].avgReturnPct : null,
  min_sample_rule:'Each split: >=100 paired signals across >=30 distinct symbols',
  evidence_status:!bothSufficient?'INSUFFICIENT':
    train['5'].avgReturnPct>train['3'].avgReturnPct && test['5'].avgReturnPct>test['3'].avgReturnPct
      ?'CANDIDATE_REQUIRES_PROSPECTIVE_VALIDATION':'NO_CONSISTENT_IMPROVEMENT',
  live_default_hold:3,
  auto_promotion:false
};
const report={
  schema:2,model:'A-share V2.0 single-stock rules, multi-horizon paired and sequential',
  generated_at:new Date().toISOString(), cutoff_date:cutDate,
  split:'First 70% of common trading calendar is training; later 30% held out by date. Train entries must fully exit before cutoff; test entries must be >=cutoff. Paired cohort requires the full 10-session horizon.',
  cutoff_common_calendar_days:calendar.length,
  date_earliest:earliest, date_latest:latest,
  history_files_scanned:scanned, stocks_eligible:usable,
  skipped_history_files:invalid, stocks_without_oos_history:staleForHoldout,
  paired_distinct_stocks:{train:pairSymbols.train.size,test:pairSymbols.test.size},
  horizons:BT.HORIZONS,price_filter:'none; mirrors current single-stock backtest',
  assumptions:'100 shares, 0.1% each-side slippage, max(5 RMB, 0.03%) each-side commission, 0.05% sell stamp; T+1; same signal-date ATR; next-day opening no-chase check; conservative same-bar stop precedence; no live executable prices.',
  caveats:'Incomplete universe, no delistings, no suspension/limit-up fill simulation, no corporate action adjustments. Paired signals can overlap; pooled averages are not portfolio returns. Parameters have not been tuned on holdout.',
  metrics,comparison
};
fs.mkdirSync(path.dirname(outPath),{recursive:true});
fs.writeFileSync(outPath,JSON.stringify(report,null,2)+'\n','utf8');
console.log('V2 holding study:',JSON.stringify({
  cutoff:cutDate,scanned,usable,invalid,staleForHoldout,
  trainPairCount:train['3'].count, testPairCount:test['3'].count,
  trainStocks:pairSymbols.train.size,testStocks:pairSymbols.test.size,
  train3:train['3'].avgReturnPct,train5:train['5'].avgReturnPct,
  oos3:test['3'].avgReturnPct,oos5:test['5'].avgReturnPct,
  status:comparison.evidence_status,output:outPath
}));
