/* Exploratory entry-quality analysis. Never authorizes a trading signal.
 * Filters are fixed, human-readable single-variable hypotheses, not a
 * hyperparameter search or an automatic model-selection optimizer.
 */
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 root.AShareEntryResearch=api;
})(typeof globalThis==='undefined'?this:globalThis,function(){
 'use strict';
 const RULES=Object.freeze([
  Object.freeze({id:'baseline',label:'原策略（不额外过滤）'}),
  Object.freeze({id:'ma_gap',label:'MA5比MA10至少高0.6%'}),
  Object.freeze({id:'ma_slope',label:'MA5单日增幅至少0.4%'}),
  Object.freeze({id:'volume',label:'信号日量比至少1.5'}),
  Object.freeze({id:'rsi',label:'信号日RSI14在50–62'}),
  Object.freeze({id:'atr',label:'信号日ATR占收盘价不超过3.5%'})
 ]);
 function supports(rule,trade){
  const s=trade.signalMetrics;
  if(!s)return false;
  switch(rule){
   case 'baseline':return true;
   case 'ma_gap':return Number.isFinite(s.maGap)&&s.maGap>=.006;
   case 'ma_slope':return Number.isFinite(s.maSlope)&&s.maSlope>=.004;
   case 'volume':return Number.isFinite(s.volRatio)&&s.volRatio>=1.5;
   case 'rsi':return Number.isFinite(s.rsi)&&s.rsi>=50&&s.rsi<=62;
   case 'atr':return Number.isFinite(s.atrPct)&&s.atrPct<=.035;
   default:throw new Error('Unknown rule '+rule);
  }
 }
 function annotate(trade, bars){
  const index=trade.signalIndex,p=bars[index],prior=bars[index-1];
  if(!p||!prior)throw new Error('Missing signal bar');
  const s={
   maGap:(p.ma5-p.ma10)/p.close,
   maSlope:(p.ma5-prior.ma5)/p.close,
   volRatio:p.volRatio,
   rsi:p.rsi14,
   atrPct:p.atr14/p.close
  };
  return {...trade,signalMetrics:s};
 }
 function stats(trades){
  let gross=0,net=0,pl=0,wins=0,positive=0,negative=0,flat=0;
  let gain=0,loss=0,exitTrend=0;
  const stocks=new Set(),details={};
  for(const t of trades){
   stocks.add(t.code);
   const priceIn=t.entry/1.001,priceOut=t.exit/.999;
   const grossPct=100*(priceOut-priceIn)/priceIn;
   const netPct=t.returnPct;
   gross+=grossPct;net+=netPct;pl+=t.pl;
   if(t.pl>0){wins++;positive++;gain+=t.pl;}
   else if(t.pl<0){negative++;loss-=t.pl;}else flat++;
   if(t.reason==='趋势转弱')exitTrend++;
   let e=details[t.reason];
   if(!e)e=details[t.reason]={count:0,returns:0,stocks:new Set()};
   e.count++;e.returns+=netPct;e.stocks.add(t.code);
  }
  const count=trades.length;
  const reasons=Object.entries(details).map(([name,v])=>({
   reason:name,count:v.count,sharePct:count?100*v.count/count:null,
   avgNetPct:v.count?v.returns/v.count:null,distinctStocks:v.stocks.size
  })).sort((a,b)=>b.count-a.count);
  return {count,distinctStocks:stocks.size,
   avgGrossPct:count?gross/count:null,avgNetPct:count?net/count:null,
   avgCostDragPp:count?(gross-net)/count:null,
   winRatePct:count?100*wins/count:null,
   profitFactor:count?(loss>0?gain/loss:gain>0?'∞':null):null,
   totalPnlYuan:count?pl:null, trendExitPct:count?100*exitTrend/count:null,reasons};
 }
 function select(trades,rule){return trades.filter(t=>supports(rule,t))}
 function evaluateRuleTables(train,test){
  return RULES.map(r=>{
   const t=stats(select(train,r.id)),v=stats(select(test,r.id));
   return {id:r.id,label:r.label,train:t,test:v,
    note:'历史研究，不是已获前瞻验证的新策略'};
  });
 }
 function prospectiveState(trades,start='2026-11-20'){
  const actual=trades.filter(t=>t.entryDate>=start);
  const n=actual.length,codes=new Set(actual.map(t=>t.code)).size;
  return {startDate:start,completedPairedSignals:n,distinctStocks:codes,
   minimumPairedSignals:100,minimumDistinctStocks:30,
   status:n>=100&&codes>=30?'FORWARD_DATED_REVIEW_REQUIRED':'WAIT_FOR_FUTURE_SAMPLES',
   caveat:'仅凭历史文件里的入场日期无法证明信号当时已被实时记录。真正前瞻确认还需要不可回填的信号快照。',
   autoApply:false};
 }
 return {RULES,supports,annotate,stats,select,evaluateRuleTables,prospectiveState};
});
