import test from "node:test";
import assert from "node:assert/strict";
import { checkAndDispatch, beijingClock } from "../src/index.mjs";

const FIRST = new Date("2026-11-23T11:45:00.000Z"); // 19:45 Beijing
const SECOND = new Date("2026-11-23T13:45:00.000Z"); // 21:45 Beijing
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" }
});
const screen = ({
  asof = "2026-11-20",
  scope = "FULL_A",
  status = "partial",
  covered = 300,
  eligible = 3053
} = {}) => ({
  schema: 1, asof, board_scope: scope, status,
  covered_count: covered, eligible_count: eligible, rows: []
});
const mock = ({ snapshot = screen(), runs = [], failure = false } = {}) => {
  const calls = [];
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("raw.githubusercontent.com")) return json(snapshot);
    if (url.includes("/runs?")) return json({ workflow_runs: runs });
    if (options.method === "POST") {
      return failure ? new Response("token denied", { status: 403 }) : new Response(null, { status: 204 });
    }
    throw new Error("Unexpected request: " + url);
  };
  return { calls, fetcher };
};

test("Beijing clock and weekend guard", async () => {
  assert.equal(beijingClock(FIRST).date, "2026-11-23");
  const m = mock();
  const result = await checkAndDispatch({
    now: new Date("2026-11-22T11:45:00Z"), secret: "test", fetcher: m.fetcher
  });
  assert.equal(result.status, "MARKET_WEEKEND");
  assert.equal(m.calls.length, 0);
});

test("complete main-board screen for today's date does not dispatch", async () => {
  const m = mock({
    snapshot: screen({
      asof: "2026-11-23", scope: "SH_SZ_MAIN", status: "complete",
      covered: 3053, eligible: 3053
    })
  });
  const result = await checkAndDispatch({ now: FIRST, secret: "test", fetcher: m.fetcher });
  assert.equal(result.status, "EOD_COMPLETE");
  assert.equal(m.calls.length, 1);
});

test("same-day main-board screen with partial 300/3053 coverage is NOT complete", async () => {
  const m = mock({
    snapshot: screen({
      asof: "2026-11-23", scope: "SH_SZ_MAIN", status: "partial",
      covered: 300, eligible: 3053
    })
  });
  const result = await checkAndDispatch({
    now: FIRST, secret: "test", fetcher: m.fetcher, log: { info() {} }
  });
  assert.equal(result.status, "DISPATCHED");
  assert.equal(result.covered, 300);
  assert.equal(m.calls.filter(c => c.options.method === "POST").length, 1);
});

test("active scheduled run suppresses a duplicate dispatch", async () => {
  const m = mock({
    runs: [{
      event: "schedule", status: "in_progress", head_branch: "main",
      created_at: "2026-11-23T10:20:00Z"
    }]
  });
  const result = await checkAndDispatch({ now: FIRST, secret: "test", fetcher: m.fetcher });
  assert.equal(result.status, "EOD_IN_PROGRESS");
  assert.ok(m.calls.every(c => !c.options.method));
});

test("first-slot manual dispatch suppresses another dispatch in the same slot", async () => {
  const m = mock({
    runs: [{
      event: "workflow_dispatch", status: "completed", conclusion: "failure",
      head_branch: "main", created_at: "2026-11-23T11:44:00Z"
    }]
  });
  const result = await checkAndDispatch({ now: FIRST, secret: "test", fetcher: m.fetcher });
  assert.equal(result.status, "DISPATCH_ALREADY_RECORDED");
  assert.ok(m.calls.every(c => !c.options.method));
});

test("failed first-slot dispatch does not block the 21:45 retry slot", async () => {
  const m = mock({
    runs: [{
      event: "workflow_dispatch", status: "completed", conclusion: "failure",
      head_branch: "main", created_at: "2026-11-23T11:47:00Z"
    }]
  });
  const result = await checkAndDispatch({
    now: SECOND, secret: "test", fetcher: m.fetcher, log: { info() {} }
  });
  assert.equal(result.status, "DISPATCHED");
  assert.equal(result.slot, 21);
  assert.equal(m.calls.filter(c => c.options.method === "POST").length, 1);
});

test("second-slot dispatch is deduplicated", async () => {
  const m = mock({
    runs: [{
      event: "workflow_dispatch", status: "completed", conclusion: "failure",
      head_branch: "main", created_at: "2026-11-23T13:44:00Z"
    }]
  });
  const result = await checkAndDispatch({ now: SECOND, secret: "test", fetcher: m.fetcher });
  assert.equal(result.status, "DISPATCH_ALREADY_RECORDED");
  assert.ok(m.calls.every(c => !c.options.method));
});

test("stale screen dispatches only the fixed workflow on main", async () => {
  const m = mock();
  const result = await checkAndDispatch({
    now: FIRST, secret: "local-test-secret", fetcher: m.fetcher, log: { info() {} }
  });
  assert.equal(result.status, "DISPATCHED");
  const calls = m.calls.filter(c => c.options.method === "POST");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url,
    "https://api.github.com/repos/gritechomepm-art/ashare-quant-personal/actions/workflows/baostock-backfill.yml/dispatches");
  assert.deepEqual(JSON.parse(calls[0].options.body), { ref: "main" });
  assert.equal(calls[0].options.headers.Authorization, "Bearer local-test-secret");
});

test("missing secret and GitHub permission errors fail closed", async () => {
  const m = mock();
  await assert.rejects(
    () => checkAndDispatch({ now: FIRST, fetcher: m.fetcher }),
    /secret not configured/
  );
  const denied = mock({ failure: true });
  await assert.rejects(
    () => checkAndDispatch({ now: FIRST, secret: "dummy", fetcher: denied.fetcher }),
    /HTTP 403/
  );
});

test("malformed screen and run list never become a false success", async () => {
  const malformedScreen = async () => json({ schema: 2, asof: "2026-11-20", rows: [] });
  await assert.rejects(
    () => checkAndDispatch({ now: FIRST, secret: "dummy", fetcher: malformedScreen }),
    /Malformed screen/
  );
  const malformedRuns = async url => url.includes("raw.githubusercontent.com")
    ? json(screen())
    : json({ workflow_runs: null });
  await assert.rejects(
    () => checkAndDispatch({ now: FIRST, secret: "dummy", fetcher: malformedRuns }),
    /Malformed EOD run list/
  );
});
