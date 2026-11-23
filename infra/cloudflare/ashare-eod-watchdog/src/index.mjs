/*
 * AShare EOD independent scheduler, Cloudflare Cron. No HTTP dispatch endpoint.
 * Repo is fixed; Action dispatch token is an encrypted Worker secret.
 * No trading rules, histories, or signal data are modified here.
 */
const REPO="gritechomepm-art/ashare-quant-personal";
const WORKFLOW="baostock-backfill.yml";
const API="https://api.github.com/repos/"+REPO;
const HEADERS={"Accept":"application/vnd.github+json","User-Agent":"ashare-eod-watchdog/1.0","X-GitHub-Api-Version":"2022-11-28"};
const two=n=>String(n).padStart(2,"0");

export function beijingClock(now=new Date()){
  const dt=new Date(now.getTime()+8*60*60*1000);
  return {date:dt.getUTCFullYear()+"-"+two(dt.getUTCMonth()+1)+"-"+two(dt.getUTCDate()),
    weekday:dt.getUTCDay(),hours:dt.getUTCHours(),minute:dt.getUTCMinutes(),
    timestamp:dt.getTime()};
}

export async function checkAndDispatch({fetcher=fetch,now=new Date(),secret,log=console}={}){
  const today=beijingClock(now);
  if(today.weekday===0||today.weekday===6)return {status:"MARKET_WEEKEND",date:today.date};
  if(today.hours<19)return {status:"BEFORE_WATCHDOG_WINDOW",date:today.date};
  const rawURL="https://raw.githubusercontent.com/"+REPO+"/main/data/screen.json?v="+encodeURIComponent(now.toISOString());
  const er=await fetcher(rawURL,{headers:HEADERS,redirect:"follow"});
  if(!er.ok)throw Error("Cannot verify published EOD file (HTTP "+er.status+")");
  const screen=await er.json();
  if(!screen||screen.schema!==1||typeof screen.asof!=="string")throw Error("Malformed screen data, refusing dispatch decision");
  if(screen.asof===today.date&&screen.board_scope==="SH_SZ_MAIN")
    return {status:"EOD_FRESH",date:today.date,asof:screen.asof,board:screen.board_scope};
  const rr=await fetcher(API+"/actions/workflows/"+WORKFLOW+"/runs?per_page=40",{headers:HEADERS});
  if(!rr.ok)throw Error("Cannot verify existing EOD runs (HTTP "+rr.status+")");
  const entries=(await rr.json()).workflow_runs;
  if(!Array.isArray(entries))throw Error("Malformed EOD run list, refusing duplicate dispatch");
  const start=Date.parse(today.date+"T09:00:00Z"); // 17:00 Beijing on trade date
  const sameDay=entries.filter(r=>Date.parse(r.created_at)>=start&&Date.parse(r.created_at)<=now.getTime()&&r.head_branch==="main");
  // Never compete with an in-flight real schedule, manual run, or backup run.
  if(sameDay.some(r=>["queued","waiting","pending","requested","in_progress"].includes(r.status)))
    return {status:"EOD_IN_PROGRESS",date:today.date,asof:screen.asof};
  // Maximum one external dispatch per China market date. Avoid duplicate
  // expensive BaoStock scans if GitHub schedule/API becomes slow.
  if(sameDay.some(r=>r.event==="workflow_dispatch"))
    return {status:"DISPATCH_ALREADY_RECORDED",date:today.date,asof:screen.asof};
  if(!secret||typeof secret!=="string")throw Error("GITHUB_ACTIONS_TOKEN secret not configured; no dispatch attempted");
  const dispatch=await fetcher(API+"/actions/workflows/"+WORKFLOW+"/dispatches",{
    method:"POST",
    headers:{...HEADERS,"Authorization":"Bearer "+secret,"Content-Type":"application/json"},
    body:JSON.stringify({ref:"main"})
  });
  if(dispatch.status!==204){
    const body=(await dispatch.text()).slice(0,200);
    throw Error("GitHub workflow_dispatch HTTP "+dispatch.status+": "+body);
  }
  log.info?.("EOD watchdog dispatched workflow for "+today.date+"; prior asof="+screen.asof);
  return {status:"DISPATCHED",date:today.date,asof:screen.asof};
}
export default {
  async scheduled(_controller,env,ctx){
    const run=checkAndDispatch({secret:env.GITHUB_ACTIONS_TOKEN});
    ctx.waitUntil(run.then(x=>console.log(JSON.stringify(x))).catch(err=>{
      console.error("AShare EOD watchdog ERROR:",err?.message||String(err));
      throw err;
    }));
  },
  async fetch(){return new Response("Not found",{status:404});}
};
