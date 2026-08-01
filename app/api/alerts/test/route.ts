import { alertProxy } from "../proxy";

export const dynamic = "force-dynamic";

export async function POST() {
  return alertProxy("/api/alerts/test", { method: "POST" });
}
