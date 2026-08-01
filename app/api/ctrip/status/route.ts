import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const crawlerUrl = process.env.FLIGHT_CRAWLER_URL;
  if (!crawlerUrl) {
    return NextResponse.json({ connected: false, message: "仅桌面版支持携程登录态" });
  }
  try {
    const response = await fetch(`${crawlerUrl.replace(/\/$/, "")}/api/ctrip/status`, { cache: "no-store" });
    if (!response.ok) throw new Error(`crawler status ${response.status}`);
    return NextResponse.json(await response.json());
  } catch {
    return NextResponse.json({ connected: false, message: "携程专用浏览器未连接" });
  }
}
