import { NextRequest, NextResponse } from "next/server";
import { cityMap } from "../../airports";
import { filterVerifiedOffers, type VerifiableOffer } from "./verification";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const origin = request.nextUrl.searchParams.get("origin")?.toUpperCase() || "";
  const destination = request.nextUrl.searchParams.get("destination")?.toUpperCase() || "";
  const transfer = request.nextUrl.searchParams.get("transfer")?.toUpperCase() || null;
  const requestedTransferCity = request.nextUrl.searchParams.get("transfer_city")?.trim() || "";
  const date = request.nextUrl.searchParams.get("date") || "";
  const throughOnly = request.nextUrl.searchParams.get("through_only") === "true";
  const codes = [origin, destination, ...(transfer ? [transfer] : [])];

  if (!date || codes.some((code) => !cityMap[code])) {
    return NextResponse.json({ error: "请提供有效的城市和出发日期。" }, { status: 400 });
  }
  if (new Set(codes).size !== codes.length) {
    return NextResponse.json({ error: "出发地、转机地和到达地不能重复。" }, { status: 400 });
  }
  if (requestedTransferCity.length > 40) {
    return NextResponse.json({ error: "转机城市名称无效。" }, { status: 400 });
  }

  const crawlerUrl = process.env.FLIGHT_CRAWLER_URL;
  if (crawlerUrl) {
    try {
      const response = await fetch(`${crawlerUrl.replace(/\/$/, "")}/api/search`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          origin,
          origin_city: cityMap[origin].city,
          destination,
          destination_city: cityMap[destination].city,
          transfer,
          transfer_city: transfer ? requestedTransferCity || cityMap[transfer].city : null,
          date,
          min_transfer_minutes: 120,
          through_only: throughOnly,
        }),
      });
      if (!response.ok) throw new Error(`crawler status ${response.status}`);
      const data = (await response.json()) as { offers?: VerifiableOffer[] };
      const offers = filterVerifiedOffers(data.offers || [], 120, throughOnly);
      if (offers.length) return NextResponse.json({ ...data, offers, mode: "verified", searchedAt: new Date().toISOString() });
    } catch (error) {
      console.error("Realtime crawler unavailable", error);
    }
  }

  return NextResponse.json({
    error: throughOnly
      ? "未找到携程明确标注且完成两次价格确认的通程航班，请更换日期或关闭通程筛选。"
      : "直飞及自动转机均未取得两次可人工对比的同航班报价，请更换日期后重试。",
    code: "PRICE_NOT_DOUBLE_VERIFIED",
  }, { status: 503 });
}
