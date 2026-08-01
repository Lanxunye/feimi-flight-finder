import assert from "node:assert/strict";
import test from "node:test";
import { filterVerifiedOffers, verifiedEvidence } from "../app/api/flights/verification.ts";
import { buildBookingReference } from "../app/booking-reference.ts";

async function worker() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  return (await import(workerUrl.href)).default;
}

const env = {
  ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
};
const context = { waitUntil() {}, passThroughOnException() {} };

test("server-renders the flight finder", async () => {
  const response = await (await worker()).fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), env, context);
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /飞觅｜国内低价机票聚合/);
  assert.match(html, /平铺选择出发地/);
  assert.match(html, /搜索城市或区县/);
  assert.match(html, /覆盖[\s\S]*260[\s\S]*个通航机场/);
  assert.match(html, /3181[\s\S]*城市\/区县/);
  assert.match(html, /按城市智能匹配/);
  assert.match(html, /全部机场/);
  assert.match(html, /苏州/);
  assert.match(html, /WUX/);
  assert.match(html, /选择转机地，当前西安/);
  assert.match(html, /选择到达地，当前成都/);
  assert.match(html, /普通转机不足 2 小时不展示/);
  assert.match(html, /通程保障最低 90 分钟/);
  assert.match(html, /仅看通程航班/);
  assert.match(html, /一次支付·行李直挂·航变保障/);
  assert.match(html, /双价人工复核/);
  assert.match(html, /两次价格都展示/);
  assert.match(html, /无直飞自动转机/);
  assert.match(html, /总行程不超过 16 小时/);
  assert.match(html, /价格 55%/);
  assert.match(html, /收藏机票价格提醒/);
  assert.match(html, /收藏夹/);
  assert.match(html, /每 30 分钟检查/);
  assert.match(html, /价格上涨或下降才通知/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("does not fabricate prices when two live checks are unavailable", async () => {
  const url = "http://localhost/api/flights?origin=PEK&transfer=XIY&destination=CTU&date=2026-07-26";
  const response = await (await worker()).fetch(new Request(url), env, context);
  assert.equal(response.status, 503);
  const data = await response.json();
  assert.equal(data.code, "PRICE_NOT_DOUBLE_VERIFIED");
  assert.match(data.error, /两次可人工对比/);
});

test("rejects repeated cities", async () => {
  const url = "http://localhost/api/flights?origin=PEK&transfer=PEK&destination=CTU&date=2026-07-26";
  const response = await (await worker()).fetch(new Request(url), env, context);
  assert.equal(response.status, 400);
  const data = await response.json();
  assert.match(data.error, /不能重复/);
});

test("the nationwide airport directory accepts less common airports without inventing a fare", async () => {
  const url = "http://localhost/api/flights?origin=JZH&transfer=XIY&destination=KHG&date=2026-07-26";
  const response = await (await worker()).fetch(new Request(url), env, context);
  assert.equal(response.status, 503);
  const data = await response.json();
  assert.equal(data.code, "PRICE_NOT_DOUBLE_VERIFIED");
});

test("keeps different prices from two separate checks for manual review and enforces 120-minute transfers", () => {
  const checkedAt = new Date().toISOString();
  const accepted = {
    price: 660,
    transferMinutes: 125,
    evidence: [
      { source: "飞猪-实时查询", provider: "飞猪", checkId: "first", price: 620, checkedAt },
      { source: "飞猪-实时复核", provider: "飞猪", checkId: "second", price: 660, checkedAt },
    ],
  };
  const oneSource = { ...accepted, evidence: [accepted.evidence[0]] };
  const largeSpread = {
    ...accepted,
    price: 820,
    evidence: [accepted.evidence[0], { source: "飞猪-实时复核", provider: "飞猪", checkId: "second", price: 820, checkedAt }],
  };
  const repeatedCheck = {
    ...accepted,
    evidence: [accepted.evidence[0], { ...accepted.evidence[0], price: 640 }],
  };
  const shortTransfer = { ...accepted, transferMinutes: 119 };
  const longJourney = { ...accepted, totalMinutes: 961 };

  assert.equal(verifiedEvidence(accepted.evidence).length, 2);
  assert.deepEqual(filterVerifiedOffers([accepted, oneSource, largeSpread, repeatedCheck, shortTransfer, longJourney]), [accepted, largeSpread]);
});

test("builds a copyable Ctrip lookup reference for every flight segment", () => {
  const reference = buildBookingReference([
    { from: { city: "揭阳", code: "SWA" }, to: { city: "成都", code: "TFU" }, departTime: "08:10", arriveTime: "10:45", departDate: "2026-08-07", arriveDate: "2026-08-07", flightNo: "CA4321", airline: "中国国航" },
    { from: { city: "成都", code: "TFU" }, to: { city: "乌鲁木齐", code: "URC" }, departTime: "13:00", arriveTime: "16:40", departDate: "2026-08-07", arriveDate: "2026-08-07", flightNo: "CA4207", airline: "中国国航" },
  ], "2026-08-07", 510, 135);

  assert.match(reference, /CA4321/);
  assert.match(reference, /CA4207/);
  assert.match(reference, /揭阳\(SWA\).*成都\(TFU\)/);
  assert.match(reference, /转机：2小时15分/);
  assert.match(reference, /请在携程按航班号及起降时间核对/);
});

test("enforces the explicit through-flight marker when requested", () => {
  const checkedAt = new Date().toISOString();
  const evidence = [
    { source: "携程-实时查询", checkId: "first", price: 880, checkedAt },
    { source: "携程-实时复核", checkId: "second", price: 880, checkedAt },
  ];
  const through = { price: 880, totalMinutes: 430, transferMinutes: 140, throughFlight: true, evidence };
  const ordinary = { ...through, throughFlight: false };
  const protectedShortConnection = { ...through, transferMinutes: 100 };
  const unprotectedShortConnection = { ...ordinary, transferMinutes: 100 };
  const unsafeThroughConnection = { ...through, transferMinutes: 89 };
  assert.deepEqual(
    filterVerifiedOffers([through, ordinary, protectedShortConnection, unprotectedShortConnection, unsafeThroughConnection], 120, true),
    [through, protectedShortConnection],
  );
});
