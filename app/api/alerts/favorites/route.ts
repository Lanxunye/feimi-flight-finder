import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function GET() {
  return alertProxy("/api/alerts/favorites", { method: "GET" });
}
