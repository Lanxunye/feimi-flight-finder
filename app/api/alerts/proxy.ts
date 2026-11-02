import { NextResponse } from "next/server";

export async function alertProxy(path: string, init?: RequestInit) {
  const crawlerUrl = process.env.FLIGHT_CRAWLER_URL;
  if (!crawlerUrl) {
    return NextResponse.json({
      available: false,
      desktopOnly: true,
      enabled: false,
      imsgAvailable: false,
      intervalMinutes: 30,
      watchCount: 0,
      watchedOfferIds: [],
      recipients: [],
      activeRecipientId: null,
      totalWatchCount: 0,
      message: "iMessage 价格提醒仅在飞觅桌面版运行",
    }, { status: init?.method && init.method !== "GET" ? 503 : 200 });
  }
  try {
    const response = await fetch(`${crawlerUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "content-type": "application/json" },
    });
    const data = await response.json() as { detail?: string };
    if (!response.ok) {
      return NextResponse.json({ ...data, error: data.detail || "价格提醒服务暂不可用" }, { status: response.status });
    }
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "价格提醒服务暂不可用" }, { status: 503 });
  }
}
