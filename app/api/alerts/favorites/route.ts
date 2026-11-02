import { NextRequest } from "next/server";
import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const recipientId = request.nextUrl.searchParams.get("recipientId");
  const query = recipientId ? `?recipient_id=${encodeURIComponent(recipientId)}` : "";
  return alertProxy(`/api/alerts/favorites${query}`, { method: "GET" });
}
