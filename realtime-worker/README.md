# V2 realtime-ish A-share Worker proxy (not yet deployed)

This is an **optional** backend for `https://gritechomepm-art.github.io/ashare-quant-personal/`.
It uses Tencent Finance's **unofficial and unsupported** `qt.gtimg.cn` endpoint. Tencent may block or change the endpoint, especially from Cloudflare egress. Do not claim live data until a real trading-session probe succeeds.

## Behavior

- `GET /health`: worker process health, **not** upstream provider health
- `GET /v1/quotes?codes=603217,603211,002532`: validated quotes, per-stock source timestamps, explicit local request time; max 50 codes per request; invalid codes rejected
- Origin allowlist: `https://gritechomepm-art.github.io` (change `ALLOWED_ORIGIN` before launching at another URL)
- Cached public quote response at Cloudflare edge for about 3 seconds per code batch
- Upstream request timeout 4.5 seconds. Old source quotes are not relabelled as fresh. Returns HTTP 503 on provider failure or insufficient fresh coverage during Beijing trading hours
- Avoids exposing a general public URL proxy: upstream host and query format are fixed
- **No stock account connection, no trades, no personal holding details stored in GitHub.** The browser DOES transmit requested ticker codes to Cloudflare/Tencent; use only with informed consent.

## Local tests

```bash
node --test realtime-worker/test/*.test.mjs
```

## Deploy (only after tests and explicit production approval)

1. From `realtime-worker/`, execute `npx wrangler login` or use a restricted Cloudflare deploy API token in a secure CI secret. Do **not** paste API tokens into ChatGPT or commit them.
2. `npx wrangler deploy`. Capture the actual deployed `workers.dev` URL.
3. Test `/health` and query 2 known tickers during the A-share trading session; independently verify prices and `quote_time` against a trusted source. Verify preflight CORS, stale-source handling, and mobile network.
4. Set the actual URL in the repository root `realtime-config.js` and deploy GitHub Pages through its ordinary validated workflow.
5. On a phone, confirm 5-second polling **updates SOURCE time and price**, not just request time, over multiple intervals. Verify Worker quota and error/blocked-provider handling.

## Safety / remaining scope

- Query polling is *near real-time snapshots*, not exchange-authorized tick-by-tick data or Level-2.
- Frontend request transport is an optional replacement for stale quote-feed display. A separate reliable ledger sink is required if **every frontend-observed intraday warning** must be persisted; the existing quote-feed recorder is still a separate 5-minute best-effort process.
- Free Workers plan currently has 100,000 inbound requests/day. Five-second polling for 4 trading hours is ~2,880 requests **per 50-stock batch per client per trading day**; 120 stocks use three batches and ~8,640 requests per client/day. Actual costs/limits vary; add user limits, cache and monitoring before exposing to many users.
- If Tencent denies Cloudflare Worker outbound access, use a permitted licensed quote provider; **do not** claim switching the URL alone can cure access restrictions.
