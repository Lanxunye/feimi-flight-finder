import { NextRequest } from "next/server";
import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return alertProxy("/api/alerts/recipients", { method: "POST", body: await request.text() });
}
