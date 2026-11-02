import { NextRequest } from "next/server";
import { alertProxy } from "../../../proxy";

export const dynamic = "force-dynamic";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ offerId: string }> }) {
  const { offerId } = await params;
  return alertProxy(`/api/alerts/watch/${encodeURIComponent(offerId)}/copy`, { method: "PUT", body: await request.text() });
}
