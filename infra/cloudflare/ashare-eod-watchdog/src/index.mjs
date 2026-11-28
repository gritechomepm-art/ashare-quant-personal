/*
 * AShare EOD watchdog.
 * It only checks the published EOD snapshot and dispatches the existing
 * BaoStock GitHub workflow when the current SH/SZ main-board screen is stale
 * or incomplete. It never fetches market data or changes trading rules.
 */
const REPO = "gritechomepm-art/ashare-quant-personal";
const WORKFLOW = "baostock-backfill.yml";
const API = "https://api.github.com/repos/" + REPO;
const HEADERS = {
  "Accept": "application/vnd.github+json",
  "User-Agent": "ashare-eod-watchdog/1.1",
  "X-GitHub-Api-Version": "2022-11-28"
};
const two = n => String(n).padStart(2, "0");

export function beijingClock(now = new Date()) {
  const dt = new Date(now.getTime() + 8 * 60 * 60 * 1000);
  return {
    date: dt.getUTCFullYear() + "-" + two(dt.getUTCMonth() + 1) + "-" + two(dt.getUTCDate()),
    weekday: dt.getUTCDay(),
    hours: dt.getUTCHours(),
    minute: dt.getUTCMinutes()
  };
}

function hasCompleteMainboardScreen(screen, date) {
  return screen.asof === date
    && screen.board_scope === "SH_SZ_MAIN"
    && screen.status !== "partial"
    && Number.isFinite(screen.eligible_count)
    && screen.eligible_count > 0
    && Number.isFinite(screen.covered_count)
    && screen.covered_count >= screen.eligible_count;
}

/**
 * @param {{ fetcher?: typeof fetch, now?: Date, secret?: string, log?: Console }} [options]
 */
export async function checkAndDispatch(options = {}) {
  const { fetcher = fetch, now = new Date(), secret, log = console } = options;
  const today = beijingClock(now);
  if (today.weekday === 0 || today.weekday === 6) {
    return { status: "MARKET_WEEKEND", date: today.date };
  }
  if (today.hours < 19) {
    return { status: "BEFORE_WATCHDOG_WINDOW", date: today.date };
  }

  const rawURL = "https://raw.githubusercontent.com/" + REPO
    + "/main/data/screen.json?v=" + encodeURIComponent(now.toISOString());
  const screenResponse = await fetcher(rawURL, { headers: HEADERS, redirect: "follow" });
  if (!screenResponse.ok) {
    throw new Error("Cannot verify published EOD file (HTTP " + screenResponse.status + ")");
  }
  const screen = await screenResponse.json();
  if (!screen || screen.schema !== 1 || typeof screen.asof !== "string"
      || !Array.isArray(screen.rows)) {
    throw new Error("Malformed screen data; refusing dispatch decision");
  }

  if (hasCompleteMainboardScreen(screen, today.date)) {
    return {
      status: "EOD_COMPLETE",
      date: today.date,
      asof: screen.asof,
      covered: screen.covered_count,
      eligible: screen.eligible_count
    };
  }

  const runsResponse = await fetcher(
    API + "/actions/workflows/" + WORKFLOW + "/runs?per_page=40",
    { headers: HEADERS }
  );
  if (!runsResponse.ok) {
    throw new Error("Cannot verify existing EOD runs (HTTP " + runsResponse.status + ")");
  }
  const runs = (await runsResponse.json()).workflow_runs;
  if (!Array.isArray(runs)) {
    throw new Error("Malformed EOD run list; refusing duplicate dispatch");
  }

  // 09:00 UTC = 17:00 Beijing. Only consider this Beijing calendar date.
  const dayStart = Date.parse(today.date + "T09:00:00Z");
  const sameDay = runs.filter(run =>
    Date.parse(run.created_at) >= dayStart
    && Date.parse(run.created_at) <= now.getTime()
    && run.head_branch === "main"
  );

  if (sameDay.some(run =>
    ["queued", "waiting", "pending", "requested", "in_progress"].includes(run.status)
  )) {
    return { status: "EOD_IN_PROGRESS", date: today.date, asof: screen.asof };
  }

  // Cron slots: 19:45 and 21:45 Beijing. Each slot can dispatch at most once.
  // A failed/partial first attempt does not block the second-slot retry.
  const slotStartHour = today.hours >= 21 ? 21 : 19;
  const dispatchAlreadyInThisSlot = sameDay.some(run => {
    if (run.event !== "workflow_dispatch") return false;
    const created = Date.parse(run.created_at);
    if (!Number.isFinite(created)) return false;
    const beijingHour = new Date(created + 8 * 60 * 60 * 1000).getUTCHours();
    return beijingHour >= slotStartHour && beijingHour < slotStartHour + 2;
  });
  if (dispatchAlreadyInThisSlot) {
    return { status: "DISPATCH_ALREADY_RECORDED", date: today.date, slot: slotStartHour };
  }

  if (!secret || typeof secret !== "string") {
    throw new Error("GITHUB_ACTIONS_TOKEN secret not configured; no dispatch attempted");
  }

  const dispatch = await fetcher(API + "/actions/workflows/" + WORKFLOW + "/dispatches", {
    method: "POST",
    headers: {
      ...HEADERS,
      "Authorization": "Bearer " + secret,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ ref: "main" })
  });
  if (dispatch.status !== 204) {
    const body = (await dispatch.text()).slice(0, 200);
    throw new Error("GitHub workflow_dispatch HTTP " + dispatch.status + ": " + body);
  }

  log.info?.("EOD watchdog dispatched " + today.date + " slot " + slotStartHour
    + "; prior asof=" + screen.asof + "; coverage="
    + String(screen.covered_count) + "/" + String(screen.eligible_count));
  return {
    status: "DISPATCHED",
    date: today.date,
    slot: slotStartHour,
    asof: screen.asof,
    covered: screen.covered_count,
    eligible: screen.eligible_count
  };
}

export default {
  async scheduled(_controller, env, ctx) {
    const token = /** @type {{ GITHUB_ACTIONS_TOKEN?: string }} */ (env).GITHUB_ACTIONS_TOKEN;
    ctx.waitUntil(
      checkAndDispatch({ secret: token })
        .then(result => console.log(JSON.stringify(result)))
        .catch(error => console.error("AShare EOD watchdog ERROR:", error?.message || String(error)))
    );
  },
  async fetch() {
    return new Response("Not found", { status: 404 });
  }
};
