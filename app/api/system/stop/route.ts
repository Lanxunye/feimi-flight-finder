import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST() {
  const crawlerUrl = process.env.FLIGHT_CRAWLER_URL?.replace(/\/$/, "");
  if (!crawlerUrl) {
    return NextResponse.json({ error: "关闭功能仅在飞觅本地版可用" }, { status: 503 });
  }
  try {
    const response = await fetch(`${crawlerUrl}/api/system/stop`, { method: "POST", cache: "no-store" });
    const data = await response.json() as { detail?: string };
    if (!response.ok) {
      return NextResponse.json({ ...data, error: data.detail || "关闭服务失败" }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "关闭服务失败" }, { status: 503 });
  }
}
