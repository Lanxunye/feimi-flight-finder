import { NextRequest } from "next/server";
import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return alertProxy("/api/alerts/watch", { method: "POST", body: await request.text() });
}

export async function DELETE(request: NextRequest) {
  const offerId = request.nextUrl.searchParams.get("id") || "";
  const recipientId = request.nextUrl.searchParams.get("recipientId") || "";
  if (!offerId) return Response.json({ error: "缺少收藏航班编号" }, { status: 400 });
  const query = recipientId ? `?recipient_id=${encodeURIComponent(recipientId)}` : "";
  return alertProxy(`/api/alerts/watch/${encodeURIComponent(offerId)}${query}`, { method: "DELETE" });
}
