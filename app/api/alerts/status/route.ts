import { NextRequest } from "next/server";
import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function GET() {
  return alertProxy("/api/alerts/status", { method: "GET" });
}

export async function PUT(request: NextRequest) {
  return alertProxy("/api/alerts/settings", { method: "PUT", body: await request.text() });
}
