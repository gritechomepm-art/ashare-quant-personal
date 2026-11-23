# AShare EOD Cloudflare Cron watchdog — deployment required

This is **independent scheduling only**, NOT a market data fetcher, screener, or backtester. It checks the published GitHub `data/screen.json`; if it is not today's `board_scope=SH_SZ_MAIN` and no current BaoStock run is in progress / no `workflow_dispatch` has been recorded today, it dispatches the **existing** GitHub Actions workflow on current `main`. It does not push source, rewrite cache or fabricate signal dates.

## Cloudflare one-time setup (not yet deployed)

1. In GitHub, create a **fine-grained personal access token** limited to `gritechomepm-art/ashare-quant-personal`, repository permission **Actions: Read and write** (minimum needed for workflow dispatch), with short expiry. Keep the token private; never paste it into chat, source code, `wrangler.toml` or GitHub logs.
2. From an authorized local Cloudflare CLI session:
   ```sh
   cd infra/cloudflare/ashare-eod-watchdog
   npx wrangler deploy
   npx wrangler secret put GITHUB_ACTIONS_TOKEN
   ```
   Provide the token at the local masked terminal prompt. Do not run deploy until the account and secret are available. Verify the Worker has exactly the two cron triggers and no HTTP route. Cloudflare Cron changes can take several minutes to propagate.
3. Observe the next working day in Workers → Logs: outcomes `EOD_FRESH`, `EOD_IN_PROGRESS`, `DISPATCH_ALREADY_RECORDED` or `DISPATCHED` (or explicit error); then confirm the dispatched GitHub run and the resulting **main** `data/screen.json` `asof`, `board_scope`, `covered_count`.
4. Cloudflare 19:45/21:45 Beijing are **watchdog retries only**; GitHub 17:37/18:17 scheduled jobs stay unchanged. At most one externally dispatched workflow per Beijing date; never compete with a queued or active GH run. During Chinese trading holidays a retry may be unnecessary; BaoStock's trade calendar is the authority for the final asof.

## Operational limits

- No Cloudflare API credentials or GitHub Actions fine-grained token are available in this conversation. This is source/config, **not a live Cloudflare Cron**.
- A `204` from GitHub means dispatch accepted, **not** that the data was published successfully. Verify run outcome + file content separately.
- GitHub token expiry or API permission errors are logged as errors; do not silently claim success.
- Keep the original strategy, backtesting, 100-share execution, historical evidence ledger, original `data/screen.json` cache, prices and 5-minute intraday polling unchanged.
- No HTTP access to the dispatch workflow: HTTP requests to the Worker receive `404`.
- The independent stale-data check/alert is a separate scheduled ChatGPT monitor; Cloudflare Cron by itself is a retry trigger, not notification delivery.
