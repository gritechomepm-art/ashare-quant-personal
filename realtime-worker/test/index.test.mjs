import test from 'node:test';
import assert from 'node:assert/strict';
import { handle, parseTencent, symbol, isTradeWindow } from '../src/index.mjs';

const ORIGIN = 'https://gritechomepm-art.github.io';

function quoteLine(code='603217', time='20261112100305') {
  const f = Array(40).fill('0');
  f[1] = 'TEST'; f[2] = code; f[3] = '23.05'; f[4] = '22.55';
  f[5] = '22.9'; f[6] = '12345';
  f[30] = time; f[31] = '0.5'; f[32] = '2.22'; f[33] = '23.5'; f[34] = '22.8';
  return `v_sh${code}="${f.join('~')}";`;
}

test('validates Shenzhen Shanghai Beijing symbols', () => {
  assert.equal(symbol('603217'), 'sh603217');
  assert.equal(symbol('002532'), 'sz002532');
  assert.equal(symbol('830799'), 'bj830799');
  assert.equal(symbol('abc123'), null);
  assert.equal(symbol('00123'), null);
});

test('parses fields from Tencent format including actual source time', () => {
  const q = parseTencent(quoteLine(), ['603217']);
  assert.equal(q['603217'].price, 23.05);
  assert.equal(q['603217'].quote_time, '2026-11-12T10:03:05+08:00');
  assert.equal(q['603217'].volume_lots, 12345);
  assert.equal(parseTencent(quoteLine(), ['603211'])['603217'], undefined);
});

test('requires a valid source timestamp and data', () => {
  assert.deepEqual(parseTencent(quoteLine('603217', 'xxxxxxxxxxxxxx'), ['603217']), {});
});

test('trade-window boundaries are Beijing time', () => {
  assert.equal(isTradeWindow(new Date('2026-11-12T02:00:00Z')), true);
  assert.equal(isTradeWindow(new Date('2026-11-12T03:35:00Z')), false);
  assert.equal(isTradeWindow(new Date('2026-11-12T05:04:00Z')), true);
  assert.equal(isTradeWindow(new Date('2026-11-12T08:00:00Z')), false);
});

test('health is not misrepresented as upstream health', async () => {
  const r = await handle(new Request('https://worker.example/health'));
  assert.equal(r.status, 200);
  const body=await r.json();
  assert.match(body.note, /not Tencent availability/);
});

test('CORS restricts untrusted website origin', async () => {
  const r = await handle(new Request('https://worker.example/v1/quotes?codes=603217', {
    headers: { Origin: 'https://attacker.example' },
  }));
  assert.equal(r.status, 403);
});

test('invalid and giant code batches are rejected before outbound requests', async () => {
  const a = await handle(new Request('https://worker.example/v1/quotes?codes=000001,ABC'));
  assert.equal(a.status, 400);
  const b = await handle(new Request('https://worker.example/v1/quotes?codes=' +
    Array.from({length: 51}, (_,i)=>String(600000+i)).join(',')));
  assert.equal(b.status, 400);
});

test('successful quote includes fields, provider timestamp, and honest stale status', async () => {
  const oldFetch=globalThis.fetch;
  try {
    globalThis.fetch=async (url)=> {
      assert.match(url, /qt.gtimg.cn/);
      const data=new TextEncoder().encode(quoteLine());
      return new Response(data, { status: 200 });
    };
    // Sample quote from Nov 12 becomes stale on any future trading day.
    const r=await handle(new Request('https://worker.example/v1/quotes?codes=603217', {
      headers: { Origin: ORIGIN },
    }));
    const body=await r.json();
    assert.equal(body.count,1);
    assert.equal(body.quote_time_latest,'2026-11-12T10:03:05+08:00');
    assert.equal(body.quotes['603217'].price,23.05);
    assert.equal(r.headers.get('Access-Control-Allow-Origin'),ORIGIN);
    assert.notEqual(body.fetched_at,body.quote_time_latest);
  } finally {
    globalThis.fetch=oldFetch;
  }
});

test('provider failure is surfaced rather than inventing or reusing prices', async () => {
  const oldFetch=globalThis.fetch;
  try {
    globalThis.fetch=async ()=>{throw new Error('blocked');};
    const r=await handle(new Request('https://worker.example/v1/quotes?codes=603217'));
    assert.equal(r.status, 503);
    assert.equal((await r.json()).error,'provider_unavailable');
  } finally {
    globalThis.fetch=oldFetch;
  }
});
