"""Dedicated Qunar browser adapter for Feimi.

The adapter connects only to the isolated Qunar Chrome profile on localhost.
It captures the structured itinerary response and reads the prices rendered by
Qunar's own page, because the response deliberately obfuscates raw price
fields. Cookies, credentials, local storage, and form values are never read.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import urllib.request
from datetime import datetime
from typing import Any
from urllib.parse import urlencode


CDP_URL = os.getenv("QUNAR_CDP_URL", "http://127.0.0.1:9224")
SEARCH_RESPONSE_FRAGMENT = "/touch/api/domestic/wbdflightlist"
MAX_TOTAL_MINUTES = 16 * 60
MIN_PROTECTED_THROUGH_TRANSFER_MINUTES = 90
THROUGH_SERVICE_STANDARD = ["一次支付", "一次值机", "一次安检", "行李直挂", "航变保障"]


def qunar_url(
    origin: str,
    destination: str,
    date: str,
    origin_city: str | None = None,
    destination_city: str | None = None,
) -> str:
    return "https://flight.qunar.com/site/oneway_list.htm?" + urlencode(
        {
            "searchDepartureAirport": origin_city or origin,
            "searchArrivalAirport": destination_city or destination,
            "searchDepartureTime": date,
            "nextNDays": "0",
            "startSearch": "true",
            "fromCode": origin,
            "toCode": destination,
            "from": "flight_dom_search",
        }
    )


def cdp_available() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL.rstrip('/')}/json/version", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


async def _rendered_prices(page: Any, expected_total: int = 0) -> dict[str, list[float]]:
    """Read every rendered result page and return displayed prices by flight code."""

    prices: dict[str, list[float]] = {}
    if expected_total > 20:
        try:
            await page.wait_for_selector('a.page-link:has-text("下一页")', timeout=5_000)
        except Exception:
            pass
    for _ in range(50):
        page_prices = await page.evaluate(
            """() => {
              const decoded = [];
              for (const item of document.querySelectorAll('.b-airfly')) {
                const code = [...item.querySelectorAll('.num .n')]
                  .map((node) => (node.textContent || '').trim())
                  .filter((text) => /^[A-Z0-9]{2}\\d{2,5}$/.test(text))
                  .join('/');
                const price = item.querySelector('.fix_price');
                if (!code || !price) continue;
                const slots = new Map();
                for (const digit of price.querySelectorAll('i, b')) {
                  const text = (digit.textContent || '').trim();
                  if (!/^\\d$/.test(text)) continue;
                  const rect = digit.getBoundingClientRect();
                  if (rect.width <= 0 || rect.height <= 0) continue;
                  slots.set(Math.round(rect.x), text);
                }
                let value = [...slots.entries()]
                  .sort((left, right) => left[0] - right[0])
                  .map((entry) => entry[1])
                  .join('');
                if (!/^\\d{2,5}$/.test(value)) {
                  const candidates = [...price.querySelectorAll('b')]
                    .map((node) => (node.textContent || '').trim())
                    .filter((text) => /^\\d{2,5}$/.test(text));
                  value = candidates.at(-1) || '';
                }
                const amount = Number(value);
                if (Number.isFinite(amount) && amount > 0) decoded.push([code, amount]);
              }
              return decoded;
            }"""
        )
        for code, price in page_prices:
            prices.setdefault(str(code), []).append(float(price))

        next_page = page.locator('a.page-link:has-text("下一页")')
        if await next_page.count() == 0:
            break
        await next_page.click()
        await page.wait_for_timeout(250)
    return prices


class QunarSessionClient:
    """Serialize access to the user's dedicated Qunar browser profile."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None

    async def _connect(self) -> Any:
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(CDP_URL, timeout=12_000)
        return self._browser

    async def query(
        self,
        origin: str,
        destination: str,
        date: str,
        origin_city: str | None = None,
        destination_city: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            browser = await self._connect()
            if not browser.contexts:
                raise RuntimeError("Qunar Chrome profile has no browser context")
            page = await browser.contexts[0].new_page()
            loop = asyncio.get_running_loop()
            captured: asyncio.Future[dict[str, Any]] = loop.create_future()

            async def capture_response(response: Any) -> None:
                if SEARCH_RESPONSE_FRAGMENT not in response.url or captured.done():
                    return
                try:
                    payload = await response.json()
                    if int(payload.get("code", -1)) != 0:
                        raise RuntimeError("Qunar search did not return an authenticated result")
                    captured.set_result(payload)
                except Exception as error:
                    if not captured.done():
                        captured.set_exception(error)

            page.on("response", lambda response: asyncio.create_task(capture_response(response)))
            try:
                await page.goto(
                    qunar_url(origin, destination, date, origin_city, destination_city),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                response = await asyncio.wait_for(captured, timeout=60)
                await page.wait_for_selector(".b-airfly .fix_price", timeout=30_000)
                total = int((response.get("data") or {}).get("total") or 0)
                response["_feimiRenderedPrices"] = await _rendered_prices(page, total)
                return response
            finally:
                await page.close()


def _parse_datetime(date: Any, time: Any) -> datetime:
    return datetime.fromisoformat(f"{str(date).strip()}T{str(time).strip()}")


def _labels_text(flight: dict[str, Any]) -> str:
    parts: list[str] = []
    for label in flight.get("priceLabel") or []:
        if not isinstance(label, dict):
            continue
        parts.append(str(label.get("name") or ""))
        note = label.get("note")
        if isinstance(note, list):
            parts.extend(str(item) for item in note)
        elif note:
            parts.append(str(note))
    return "\n".join(parts)


def _explicit_through(flight: dict[str, Any]) -> bool:
    text = _labels_text(flight)
    return "通程" in text or "行李直挂" in text or ("联程" in text and "航变" in text)


def _station(info: dict[str, Any], prefix: str, fallback_code: str) -> dict[str, str]:
    airport = str(info.get(f"{prefix}Airport") or "")
    terminal = str(info.get(f"{prefix}Terminal") or "")
    return {
        "code": str(info.get(f"{prefix}AirportCode") or fallback_code).upper(),
        "city": str(info.get(f"{prefix}City") or airport.replace("国际机场", "").replace("机场", "")),
        "airport": f"{airport}{terminal}",
    }


def normalize_qunar_response(
    payload: Any,
    response: dict[str, Any],
    check_name: str,
) -> dict[str, dict[str, Any]]:
    checked_at = datetime.now().astimezone().isoformat()
    rendered_prices = response.get("_feimiRenderedPrices") or {}
    price_positions: dict[str, int] = {}
    root = response.get("data") if isinstance(response.get("data"), dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    purchase_url = qunar_url(
        payload.origin,
        payload.destination,
        payload.date,
        getattr(payload, "origin_city", None),
        getattr(payload, "destination_city", None),
    )

    for flight in root.get("flights") or []:
        if not isinstance(flight, dict):
            continue
        infos = [flight.get("binfo")] if isinstance(flight.get("binfo"), dict) else [
            flight.get("binfo1"),
            flight.get("binfo2"),
        ]
        infos = [info for info in infos if isinstance(info, dict)]
        if not infos or len(infos) > 2:
            continue
        code = "/".join(str(info.get("airCode") or "").replace(" ", "") for info in infos)
        prices = rendered_prices.get(code) or []
        price_index = price_positions.get(code, 0)
        if price_index >= len(prices):
            continue
        price_positions[code] = price_index + 1
        try:
            price = float(prices[price_index])
            departures = [_parse_datetime(info.get("depDate") or info.get("date"), info.get("depTime")) for info in infos]
            arrivals = [_parse_datetime(info.get("arrDate") or info.get("date"), info.get("arrTime")) for info in infos]
        except (TypeError, ValueError):
            continue
        if price <= 0 or departures[0].date().isoformat() != payload.date:
            continue
        total_minutes = int((arrivals[-1] - departures[0]).total_seconds() // 60)
        if total_minutes <= 0 or total_minutes > MAX_TOTAL_MINUTES:
            continue

        segments: list[dict[str, Any]] = []
        valid = True
        for index, info in enumerate(infos):
            duration = int((arrivals[index] - departures[index]).total_seconds() // 60)
            flight_no = str(info.get("airCode") or "").replace(" ", "")
            if not flight_no or duration <= 0:
                valid = False
                break
            segments.append(
                {
                    "from": _station(info, "dep", payload.origin if index == 0 else ""),
                    "to": _station(info, "arr", payload.destination if index == len(infos) - 1 else ""),
                    "departTime": departures[index].strftime("%H:%M"),
                    "arriveTime": arrivals[index].strftime("%H:%M"),
                    "departDate": departures[index].date().isoformat(),
                    "arriveDate": arrivals[index].date().isoformat(),
                    "flightNo": flight_no,
                    "airline": str(info.get("fullName") or info.get("name") or flight_no[:2]),
                    "durationMinutes": duration,
                }
            )
        if not valid:
            continue

        through_flight = len(segments) == 2 and _explicit_through(flight)
        transfer_minutes = None
        if len(segments) == 2:
            transfer_minutes = int((departures[1] - arrivals[0]).total_seconds() // 60)
            minimum = MIN_PROTECTED_THROUGH_TRANSFER_MINUTES if through_flight else payload.min_transfer_minutes
            if transfer_minutes < minimum:
                continue
            transfer_code = segments[0]["to"]["code"]
            segments[1]["from"]["code"] = transfer_code
            transfer_city = str(flight.get("transCity") or segments[0]["to"]["city"])
            if payload.transfer and transfer_code != payload.transfer and transfer_city != payload.transfer_city:
                continue
        elif payload.transfer:
            continue
        if payload.through_only and not through_flight:
            continue

        signature = "|".join(
            f"{segment['flightNo']}@{segment['departDate']}T{segment['departTime']}>{segment['arriveDate']}T{segment['arriveTime']}"
            for segment in segments
        )
        normalized[signature] = {
            "price": price,
            "segments": segments,
            "transferMinutes": transfer_minutes,
            "totalMinutes": total_minutes,
            "crossDay": arrivals[-1].date() != departures[0].date(),
            "throughFlight": through_flight,
            "throughServices": THROUGH_SERVICE_STANDARD if through_flight else [],
            "purchaseUrl": purchase_url,
            "evidence": {
                "source": f"去哪儿-{check_name}",
                "provider": "去哪儿",
                "checkId": f"qunar-session-{check_name}",
                "price": price,
                "checkedAt": checked_at,
                "url": purchase_url,
            },
        }
    return normalized


def reconcile_qunar(
    first: dict[str, dict[str, Any]],
    second: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for signature, candidate in first.items():
        confirmation = second.get(signature)
        if confirmation is None:
            continue
        same_price = abs(candidate["price"] - confirmation["price"]) < 0.01
        tags = [
            "两次价格一致" if same_price else "价格有变动·请人工选择",
            "去哪儿登录态实时查询",
            "可跳转购买",
        ]
        if candidate.get("throughFlight"):
            tags = ["通程航班·去哪儿明确标识", "行李直挂·航变保障", *tags]
        offers.append(
            {
                "id": f"qunar-session-{hashlib.sha256(signature.encode()).hexdigest()[:16]}",
                "price": confirmation["price"],
                "provider": "去哪儿",
                "tags": tags,
                "segments": candidate["segments"],
                "transferMinutes": candidate["transferMinutes"],
                "totalMinutes": candidate["totalMinutes"],
                "crossDay": candidate["crossDay"],
                "throughFlight": bool(candidate.get("throughFlight")),
                "throughServices": candidate.get("throughServices") or [],
                "purchaseUrl": confirmation["purchaseUrl"],
                "updatedAt": confirmation["evidence"]["checkedAt"],
                "evidence": [candidate["evidence"], confirmation["evidence"]],
                "signature": signature,
            }
        )
    return offers
