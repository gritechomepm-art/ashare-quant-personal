/**
 * A-share realtime-ish quote proxy. Not an exchange-grade feed.
 * GET /v1/quotes?codes=603217,603211&...
 * GET /health
 *
 * Tencent qt.gtimg.cn is an unofficial endpoint and may reject Worker egress.
 * Fail closed when quotes are stale; never invent a price or timestamp.
 */
const DEFAULT_ALLOWED_ORIGIN = 'https://gritechomepm-art.github.io';
const MAX_CODES = 50;
const CACHE_SECONDS = 3;

function symbol(code) {
  if (!/^\d{6}$/.test(code)) return null;
  if (code.startsWith('6')) return 'sh' + code;
  if (code.startsWith('0') || code.startsWith('3')) return 'sz' + code;
  if (code.startsWith('4') || code.startsWith('8') || code.startsWith('92')) return 'bj' + code;
  return null;
}

function chinaClock(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai', weekday: 'short', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit',
    minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date);
  const obj = {};
  for (const p of parts) obj[p.type] = p.value;
  return { day: `${obj.year}-${obj.month}-${obj.day}`,
    minute: Number(obj.hour) * 60 + Number(obj.minute),
    weekday: obj.weekday };
}

function isTradeWindow(now) {
  const b = chinaClock(now);
  if (b.weekday === 'Sat' || b.weekday === 'Sun') return false;
  return (b.minute >= 570 && b.minute <= 690) ||
    (b.minute >= 780 && b.minute <= 900);
}

function sourceTime(text) {
  if (!/^\d{14}$/.test(text || '')) return null;
  const iso = `${text.slice(0,4)}-${text.slice(4,6)}-${text.slice(6,8)}T${text.slice(8,10)}:${text.slice(10,12)}:${text.slice(12,14)}+08:00`;
  return Number.isFinite(Date.parse(iso)) ? iso : null;
}

function parseTencent(body, allowed) {
  const result = {};
  const allowedCodes = new Set(allowed);
  const regex = /v_(?:sh|sz|bj)(\d{6})="([^"]*)"/g;
  let match;
  while ((match = regex.exec(body)) !== null) {
    const code = match[1];
    if (!allowedCodes.has(code)) continue;
    const f = match[2].split('~');
    if (f.length < 35 || f[2] !== code) continue;
    const price = Number(f[3]), prev = Number(f[4]),
      open = Number(f[5]), volume = Number(f[6]),
      change = Number(f[31]), changePct = Number(f[32]),
      high = Number(f[33]), low = Number(f[34]);
    const stamp = sourceTime(f[30]);
    if (!(price > 0 && prev > 0 && low > 0 && high >= low && stamp)) continue;
    if (![price, prev, open, volume, change, changePct, high, low].every(Number.isFinite)) continue;
    result[code] = { name: f[1].trim(), price, prev_close: prev,
      open, volume_lots: volume, change, change_pct: changePct,
      high, low, quote_time: stamp, source: 'Tencent qt.gtimg.cn',
      market_symbol: symbol(code) };
  }
  return result;
}

function cors(origin, allowed) {
  const h = new Headers({ 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', 'Vary': 'Origin',
    'X-Content-Type-Options': 'nosniff' });
  if (origin && origin === allowed) h.set('Access-Control-Allow-Origin', origin);
  return h;
}

function json(data, status, origin, allowed) {
  return new Response(JSON.stringify(data), {
    status, headers: cors(origin, allowed) });
}

async function handle(request, env = {}, context = {}) {
  const origin = request.headers.get('Origin');
  const allowed = env.ALLOWED_ORIGIN || DEFAULT_ALLOWED_ORIGIN;
  if (origin && origin !== allowed) return json({ ok: false, error: 'origin_not_allowed' }, 403, origin, allowed);
  const url = new URL(request.url);
  if (request.method === 'OPTIONS') {
    const headers = cors(origin, allowed);
    headers.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
    headers.set('Access-Control-Allow-Headers', 'Accept, Content-Type');
    headers.set('Access-Control-Max-Age', '3600');
    return new Response(null, { status: 204, headers });
  }
  if (request.method !== 'GET') return json({ ok: false, error: 'method_not_allowed' }, 405, origin, allowed);
  if (url.pathname === '/health') {
    return json({ ok: true, service: 'ashare-realtime', provider: 'Tencent unofficial',
      note: 'Health checks the Worker only, not Tencent availability' }, 200, origin, allowed);
  }
  if (url.pathname !== '/v1/quotes') return json({ ok: false, error: 'not_found' }, 404, origin, allowed);
  // Browser-only use. Origin is not cryptographic authentication; configure
  // Cloudflare edge rate limiting before broad public distribution.
  if (!origin || origin !== allowed) return json({ ok: false, error: 'origin_required' }, 403, origin, allowed);
  const raw = url.searchParams.get('codes') || '';
  if (raw.length > 400) return json({ ok: false, error: 'too_many_characters' }, 400, origin, allowed);
  const codes = [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))].sort();
  if (!codes.length || codes.length > MAX_CODES || codes.some(c => !symbol(c))) {
    return json({ ok: false, error: 'invalid_codes', max_codes: MAX_CODES }, 400, origin, allowed);
  }

  const cacheUrl = new URL(url);
  cacheUrl.searchParams.set('codes', codes.join(','));
  const cacheKey = new Request(cacheUrl.toString(), { method: 'GET' });
  const cache = typeof caches !== 'undefined' ? caches.default : null;
  if (cache) {
    const hit = await cache.match(cacheKey);
    if (hit) {
      const cached = new Response(hit.body, hit);
      cached.headers.set('X-Quote-Cache', 'HIT');
      if (origin && origin === allowed) cached.headers.set('Access-Control-Allow-Origin', origin);
      return cached;
    }
  }
  const upstreamUrl = 'https://qt.gtimg.cn/q=' + codes.map(symbol).join(',');
  let rawBody;
  try {
    const upstream = await fetch(upstreamUrl, {
      headers: { 'Accept': '*/*', 'Referer': 'https://gu.qq.com/',
        'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(4500) });
    if (!upstream.ok) throw new Error('http_' + upstream.status);
    const buf = await upstream.arrayBuffer();
    if (buf.byteLength > 180000) throw new Error('upstream_response_too_large');
    rawBody = new TextDecoder('gb18030').decode(buf);
  } catch (e) {
    return json({ ok: false, status: 'unavailable',
      error: 'provider_unavailable', detail: String(e.message || e).slice(0,100),
      requested_count: codes.length }, 503, origin, allowed);
  }
  const now = new Date();
  const quotes = parseTencent(rawBody, codes);
  const count = Object.keys(quotes).length;
  const times = Object.values(quotes).map(q => q.quote_time);
  const latest = times.sort().at(-1) || null;
  const fresh = Object.values(quotes).filter(q => {
    const minutes = (now.getTime() - Date.parse(q.quote_time)) / 60000;
    return minutes >= -5 && minutes <= 7;
  }).length;
  const coverage = 100 * count / codes.length;
  const freshPct = 100 * fresh / codes.length;
  const inSession = isTradeWindow(now);
  const status = count === 0 || (inSession && fresh / codes.length < 0.6)
    ? 'stale' : 'ok';
  const payload = {
    schema: 1, status, source: 'Tencent qt.gtimg.cn (unofficial)',
    scope: 'Explicit requested A-share codes; not a full-market screener',
    fetched_at: now.toISOString(), quote_time_latest: latest,
    count, requested_count: codes.length, coverage_pct: Number(coverage.toFixed(2)),
    fresh_quote_count: fresh, fresh_quote_pct: Number(freshPct.toFixed(2)),
    quotes, market_timezone: 'Asia/Shanghai',
    warning: 'Snapshot polling, not exchange tick data. Timestamp is the provider quote time. Do not trade from stale values.'
  };
  const response = json(payload, status === 'ok' ? 200 : 503, origin, allowed);
  if (cache && status === 'ok') {
    const stored = new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Cache-Control': `public, max-age=${CACHE_SECONDS}`,
        'Content-Type': 'application/json; charset=utf-8' } });
    context.waitUntil?.(cache.put(cacheKey, stored));
  }
  return response;
}

export default { fetch: handle };
export { handle, parseTencent, symbol, chinaClock, isTradeWindow };
