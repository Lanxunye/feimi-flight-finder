import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

function crawlerUrl() {
  return process.env.FLIGHT_CRAWLER_URL?.replace(/\/$/, "") || "";
}

export async function GET() {
  const base = crawlerUrl();
  if (!base) {
    return NextResponse.json({ available: false, providers: {}, message: "登录入口仅在飞觅桌面版可用" });
  }
  try {
    const response = await fetch(`${base}/api/ota/status`, { cache: "no-store" });
    if (!response.ok) throw new Error(`crawler status ${response.status}`);
    return NextResponse.json({ available: true, ...(await response.json()) });
  } catch {
    return NextResponse.json({ available: false, providers: {}, message: "本机登录服务暂不可用" });
  }
}

export async function POST(request: NextRequest) {
  const base = crawlerUrl();
  if (!base) return NextResponse.json({ error: "登录入口仅在飞觅桌面版可用" }, { status: 503 });
  const body = await request.json() as { provider?: string };
  if (!body.provider || !["ctrip", "qunar", "meituan"].includes(body.provider)) {
    return NextResponse.json({ error: "请选择有效平台" }, { status: 400 });
  }
  try {
    const response = await fetch(`${base}/api/ota/open/${body.provider}`, { method: "POST", cache: "no-store" });
    const data = await response.json() as { detail?: string };
    if (!response.ok) return NextResponse.json({ ...data, error: data.detail || "登录窗口打开失败" }, { status: response.status });
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: "登录窗口打开失败" }, { status: 503 });
  }
}
