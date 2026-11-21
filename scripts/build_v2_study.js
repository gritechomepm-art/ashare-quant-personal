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
const testLimit = Number(process.argv[3] || 0);
const sourceFiles = fs.readdirSync(historyDir).filter(x => /^\d{6}\.json$/.test(x)).sort();
const files = Number.isInteger(testLimit) && testLimit > 0 ? sourceFiles.slice(0,testLimit) : sourceFiles;
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
// Preserve the first published historical holdout; never slide old OOS rows into training.
const cutDate='2026-07-21';
const prospectiveStart='2026-11-20';
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
// Exploratory diagnostics only. The original 2026 holdout was already examined;
// it must NOT be reused as a pristine model-selection set.
function avg(vals){return vals.length?vals.reduce((s,v)=>s+v,0)/vals.length:null;}
function netWithShares(t,shares){
 const buyAmount=t.entry*shares,sellAmount=t.exit*shares;
 const buyFee=Math.max(5,buyAmount*.0003),sellFee=Math.max(5,sellAmount*.0003)+sellAmount*.0005;
 return 100*(sellAmount-buyAmount-buyFee-sellFee)/(buyAmount+buyFee);
}
function diagnose(trades){
 const n=trades.length, gross=[],net=[],drag=[],notional5000=[];
 const exits={},above20=[];
 for(const t of trades){
   const price=t.entry/1.001; // next-session open is observable before hypothetical entry
   const preCostExit=t.exit/.999;
   const raw=100*(preCostExit-price)/price;
   gross.push(raw);net.push(t.returnPct);drag.push(raw-t.returnPct);
   const shares=Math.max(100,Math.ceil(5000/t.entry/100)*100);
   notional5000.push(netWithShares(t,shares));
   exits[t.reason]=(exits[t.reason]||0)+1;
   if(price>=20)above20.push(t.returnPct);
 }
 return {
   count:n, avgGrossPriceReturnPct:avg(gross),avgNet100SharesPct:avg(net),
   avgEstimatedCostDragPp:avg(drag), avgNetMinimum5000NotionalPct:avg(notional5000),
   priceAtLeast20:{count:above20.length,avgNet100SharesPct:avg(above20)},
   exitReasons:exits
 };
}
const diagnostic={train:diagnose(paired.train[3]),test:diagnose(paired.test[3]),
  methodology:'同一批3日信号；gross为买卖原始价格差，drag为含滑点、佣金、印花税后平均净收益差。5000元情景按100股整数倍增加股数，未模拟资金容量、滑点随单量变化或资金占用，不是实盘组合。入场价≥20元筛选属于已探索的候选，不等于独立验证或新默认策略。',
  candidate_promotion:false,holdout_reused_for_diagnostics:true};
const prospectiveTrades=paired.test[3].filter(t=>t.entryDate>=prospectiveStart);
const prospectiveStocks=new Set(prospectiveTrades.map(t=>t.code)).size;
const prospective={start_date:prospectiveStart,completed_3day_paired_signals:prospectiveTrades.length,
  distinct_stocks:prospectiveStocks,
  min_rule:'至少100个具有完整10日后续窗口的匹配信号，来自至少30只不同股票',
  status:prospectiveTrades.length>=100&&prospectiveStocks>=30?'OBSERVATIONS_AVAILABLE_REVIEW_REQUIRED':'WAIT_FOR_FUTURE_SAMPLES',
  auto_promotion:false,
  note:'2026-11-20 起新增的真实日线才可作为前瞻观察；不能重新把已分析的历史测试集称为全新样本。'};
// Universe accounting: present current directory counts only; historic delistings
// or historic ST statuses cannot be reconstructed from the current master.
const masterFile=path.join(ROOT,'data','stocks.json');
const master=fs.existsSync(masterFile)?JSON.parse(fs.readFileSync(masterFile,'utf8')):{};
const masterStocks=master.stocks||{}, masterCodes=Object.keys(masterStocks);
const eligibleCodes=new Set(all.filter(({bars})=>bars.length>=100).map(x=>x.code));
const namedST=masterCodes.filter(c=>/ST|退市|退/i.test(String(masterStocks[c]?.name||'')));
const masterUncovered=masterCodes.filter(c=>!eligibleCodes.has(c));
const universeAudit={
 directory_asof:master.asof||null,
 current_directory_stocks:masterCodes.length,
 valid_history_files_in_research:usable,
 directory_missing_valid_history:masterUncovered.length,
 current_names_flagged_ST_or_delisting:namedST.length,
 historic_delisted_count:null,
 historic_ST_during_study_count:null,
 unknown_explanation:'Current stock master is not a point-in-time constituent history. Historic delistings and ST occurrences cannot be counted from these files, and a current ST name is not proof of ST during an earlier period.'
};
const report={
  schema:2,model:'A-share V2.0 single-stock rules, multi-horizon paired and sequential',
  generated_at:new Date().toISOString(), cutoff_date:cutDate,
  split:'Historical split frozen at 2026-07-21 (the original V2.0 70/30 boundary). Train entries must fully exit before this date; historical test entries start no earlier than this date. The 10-session matched cohort excludes incomplete future windows. Optimisation scenarios that inspect historical test are exploratory, not pristine OOS evidence.',
  cutoff_common_calendar_days:calendar.length,
  date_earliest:earliest, date_latest:latest,
  history_files_scanned:scanned, stocks_eligible:usable,
  skipped_history_files:invalid, stocks_without_oos_history:staleForHoldout,
  paired_distinct_stocks:{train:pairSymbols.train.size,test:pairSymbols.test.size},
  horizons:BT.HORIZONS,price_filter:'none; mirrors current single-stock backtest',
  assumptions:'100 shares, 0.1% each-side slippage, max(5 RMB, 0.03%) each-side commission, 0.05% sell stamp; T+1; same signal-date ATR; next-day opening no-chase check; conservative same-bar stop precedence; no live executable prices.',
  caveats:'Incomplete universe, no delistings, no suspension/limit-up fill simulation, no corporate action adjustments. Paired signals can overlap; pooled averages are not portfolio returns. Parameters have not been tuned on holdout.',
  metrics,comparison,diagnostic,prospective,universe_audit:universeAudit
};
fs.mkdirSync(path.dirname(outPath),{recursive:true});
fs.writeFileSync(outPath,JSON.stringify(report,null,2)+'\n','utf8');
console.log('V2 holding study:',JSON.stringify({
  cutoff:cutDate,scanned,usable,invalid,staleForHoldout,
  trainPairCount:train['3'].count, testPairCount:test['3'].count,
  trainStocks:pairSymbols.train.size,testStocks:pairSymbols.test.size,
  train3:train['3'].avgReturnPct,train5:train['5'].avgReturnPct,
  oos3:test['3'].avgReturnPct,oos5:test['5'].avgReturnPct,
  status:comparison.evidence_status,trainGross:diagnostic.train.avgGrossPriceReturnPct,oosGross:diagnostic.test.avgGrossPriceReturnPct,prospectiveCount:prospectiveTrades.length,output:outPath
}));
