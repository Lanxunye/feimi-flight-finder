import { NextRequest } from "next/server";
import { alertProxy } from "../../proxy";

export const dynamic = "force-dynamic";

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ recipientId: string }> }) {
  const { recipientId } = await params;
  return alertProxy(`/api/alerts/recipients/${encodeURIComponent(recipientId)}`, { method: "DELETE", body: await request.text() || "{}" });
}
