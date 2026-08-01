import { NextRequest } from "next/server";
import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return alertProxy("/api/alerts/watch", { method: "POST", body: await request.text() });
}

export async function DELETE(request: NextRequest) {
  const offerId = request.nextUrl.searchParams.get("id") || "";
  if (!offerId) return Response.json({ error: "缺少收藏航班编号" }, { status: 400 });
  return alertProxy(`/api/alerts/watch/${encodeURIComponent(offerId)}`, { method: "DELETE" });
}
