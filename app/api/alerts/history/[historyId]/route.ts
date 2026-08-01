import { NextRequest } from "next/server";
import { alertProxy } from "../../proxy";

export const dynamic = "force-dynamic";

export async function DELETE(_request: NextRequest, { params }: { params: Promise<{ historyId: string }> }) {
  const { historyId } = await params;
  return alertProxy(`/api/alerts/history/${encodeURIComponent(historyId)}`, { method: "DELETE" });
}
