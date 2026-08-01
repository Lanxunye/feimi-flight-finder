export type BookingReferenceSegment = {
  from: { city: string; code: string };
  to: { city: string; code: string };
  departTime: string;
  arriveTime: string;
  departDate?: string;
  arriveDate?: string;
  flightNo: string;
  airline: string;
};

export function buildBookingReference(
  segments: BookingReferenceSegment[],
  fallbackDate: string,
  totalMinutes: number,
  transferMinutes: number | null,
) {
  const duration = `${Math.floor(totalMinutes / 60)}小时${totalMinutes % 60 ? `${totalMinutes % 60}分` : ""}`;
  const lines = ["飞觅 · 携程购票核对信息", `全程：${duration}`];

  segments.forEach((segment, index) => {
    const departDate = segment.departDate || fallbackDate;
    const arriveDate = segment.arriveDate || departDate;
    lines.push(
      `第${index + 1}程：${segment.airline} ${segment.flightNo}`,
      `${departDate} ${segment.departTime} ${segment.from.city}(${segment.from.code}) → ${arriveDate} ${segment.arriveTime} ${segment.to.city}(${segment.to.code})`,
    );
    if (index === 0 && transferMinutes) {
      lines.push(`转机：${Math.floor(transferMinutes / 60)}小时${transferMinutes % 60 ? `${transferMinutes % 60}分` : ""}`);
    }
  });

  lines.push("请在携程按航班号及起降时间核对，最终价格以出票页为准。");
  return lines.join("\n");
}
