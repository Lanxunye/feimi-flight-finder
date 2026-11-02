"""Crawl4AI flight-price adapter for the Feimi web UI.

The service intentionally keeps provider parsing isolated: airline and OTA pages
change often, and operators must confirm each provider permits automated access.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ctrip_session import (
    CtripSessionClient,
    cdp_available,
    normalize_ctrip_response,
    reconcile_ctrip,
)
from qunar_session import (
    QunarSessionClient,
    cdp_available as qunar_cdp_available,
    normalize_qunar_response,
    reconcile_qunar,
)
from price_alerts import (
    CHECK_INTERVAL_MINUTES,
    add_recipient,
    recipient_address,
    flight_key,
    imsg_path,
    load_state as load_alert_state,
    normalize_recipient,
    now_iso as alert_now_iso,
    delete_history_item,
    copy_watch,
    favorite_records,
    price_change_message,
    public_status as public_alert_status,
    remove_watch,
    remove_recipient,
    save_state as save_alert_state,
    send_imessage,
    upsert_watch,
    move_watch,
)

app = FastAPI(title="Feimi Crawl4AI adapter", version="1.0.0")

SERVICE_DIRECTORY = Path(__file__).resolve().parent
PRICE_TOLERANCE_RATE = 0.08
PRICE_TOLERANCE_YUAN = 50
MAX_TOTAL_MINUTES = 16 * 60
RANKING_WEIGHTS = {"price": 0.55, "duration": 0.35, "stops": 0.10}
CTRIP_SESSION = CtripSessionClient()
QUNAR_SESSION = QunarSessionClient()
ALERTS_LOCK = asyncio.Lock()

OTA_BROWSERS = {
    "ctrip": {
        "label": "携程",
        "agent": "com.feimi.ctrip-browser",
        "port": 9223,
        "url": "https://flights.ctrip.com/online/channel/domestic",
    },
    "qunar": {
        "label": "去哪儿",
        "agent": "com.feimi.qunar-browser",
        "port": 9224,
        "url": "https://flight.qunar.com/",
    },
    "meituan": {
        "label": "美团",
        "agent": "com.feimi.meituan-browser",
        "port": 9225,
        "url": "https://passport.meituan.com/useraccount/login",
    },
}
FEIMI_LAUNCH_AGENTS = (
    "com.feimi.web",
    "com.feimi.crawler",
    "com.feimi.ctrip-browser",
    "com.feimi.qunar-browser",
    "com.feimi.meituan-browser",
    "com.feimi.price-monitor",
)


class SearchRequest(BaseModel):
    origin: str = Field(pattern=r"^[A-Z]{3}$")
    origin_city: str | None = Field(default=None, min_length=1, max_length=40)
    destination: str = Field(pattern=r"^[A-Z]{3}$")
    destination_city: str | None = Field(default=None, min_length=1, max_length=40)
    transfer: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    transfer_city: str | None = Field(default=None, min_length=1, max_length=40)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    min_transfer_minutes: int = Field(default=120, ge=120)
    through_only: bool = False


class AlertStation(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{3}$")
    city: str = Field(min_length=1, max_length=40)


class AlertSegment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    flight_no: str = Field(alias="flightNo", pattern=r"^[A-Z0-9]{2}\d{2,5}$")
    depart_time: str = Field(alias="departTime", pattern=r"^[0-2]\d:[0-5]\d$")
    arrive_time: str = Field(alias="arriveTime", pattern=r"^[0-2]\d:[0-5]\d$")
    from_station: AlertStation = Field(alias="from")
    to: AlertStation


class AlertWatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_offer_id: str = Field(alias="clientOfferId", min_length=1, max_length=160)
    origin: str = Field(pattern=r"^[A-Z]{3}$")
    origin_city: str | None = Field(default=None, alias="originCity", max_length=40)
    destination: str = Field(pattern=r"^[A-Z]{3}$")
    destination_city: str | None = Field(default=None, alias="destinationCity", max_length=40)
    transfer: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    transfer_city: str | None = Field(default=None, alias="transferCity", max_length=40)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    through_only: bool = Field(default=False, alias="throughOnly")
    provider: str = Field(min_length=1, max_length=40)
    price: float = Field(gt=0)
    segments: list[AlertSegment] = Field(min_length=1, max_length=2)
    purchase_url: str = Field(alias="purchaseUrl", min_length=1, max_length=2048)
    total_minutes: int = Field(alias="totalMinutes", gt=0, le=MAX_TOTAL_MINUTES)
    transfer_minutes: int | None = Field(default=None, alias="transferMinutes", ge=90)
    recipient_id: str | None = Field(default=None, alias="recipientId", min_length=16, max_length=64)


class AlertSettingsRequest(BaseModel):
    enabled: bool
    recipient: str | None = Field(default=None, max_length=160)
    active_recipient_id: str | None = Field(default=None, alias="activeRecipientId", min_length=16, max_length=64)


class AlertRecipientRequest(BaseModel):
    recipient: str = Field(min_length=7, max_length=160)


class AlertRecipientRemovalRequest(BaseModel):
    move_to_recipient_id: str | None = Field(default=None, alias="moveToRecipientId", min_length=16, max_length=64)


class AlertWatchRecipientRequest(BaseModel):
    recipient_id: str = Field(alias="recipientId", min_length=16, max_length=64)
    source_recipient_id: str | None = Field(default=None, alias="sourceRecipientId", min_length=16, max_length=64)


class AlertWatchCopyRequest(BaseModel):
    source_recipient_id: str = Field(alias="sourceRecipientId", min_length=16, max_length=64)
    target_recipient_id: str = Field(alias="targetRecipientId", min_length=16, max_length=64)


class AlertTestRequest(BaseModel):
    recipient_id: str | None = Field(default=None, alias="recipientId", min_length=16, max_length=64)


def provider_url(origin: str, destination: str, date: str) -> str:
    return (
        "https://flights.ctrip.com/online/list/oneway-"
        f"{origin.lower()}-{destination.lower()}?depdate={date}"
    )


def parse_clock(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat()


def flyai_runtime() -> tuple[str, str]:
    node_candidates = [
        os.getenv("FLYAI_NODE_PATH"),
        shutil.which("node"),
        str(Path.home() / ".nvm/versions/node/v24.18.0/bin/node"),
    ]
    bundle_candidates = [
        os.getenv("FLYAI_CLI_PATH"),
        str(SERVICE_DIRECTORY.parent / "node_modules/@fly-ai/flyai-cli/dist/flyai-bundle.cjs"),
        str(SERVICE_DIRECTORY.parent / "web/node_modules/@fly-ai/flyai-cli/dist/flyai-bundle.cjs"),
    ]
    node = next((candidate for candidate in node_candidates if candidate and Path(candidate).exists()), "")
    bundle = next((candidate for candidate in bundle_candidates if candidate and Path(candidate).exists()), "")
    if not node or not bundle:
        raise RuntimeError("FlyAI CLI runtime is unavailable")
    return node, bundle


def run_flyai(payload: SearchRequest, journey_type: str | None = None) -> dict[str, Any]:
    if not os.getenv("FLYAI_API_KEY"):
        raise RuntimeError("FLYAI_API_KEY is not configured")
    node, bundle = flyai_runtime()
    command = [
        node,
        "--require",
        str(SERVICE_DIRECTORY / "flyai-homedir.cjs"),
        bundle,
        "search-flight",
        "--origin",
        payload.origin,
        "--destination",
        payload.destination,
        "--dep-date",
        payload.date,
        "--journey-type",
        journey_type or ("2" if payload.transfer else "1"),
        "--sort-type",
        "3",
    ]
    if payload.transfer and (journey_type or "2") == "2":
        command.extend(["--transfer-city", payload.transfer_city or payload.transfer])
    environment = os.environ.copy()
    environment["FEIMI_RUNTIME_STATE_DIR"] = environment.get(
        "FEIMI_RUNTIME_STATE_DIR", str(SERVICE_DIRECTORY / ".runtime-state")
    )
    completed = subprocess.run(
        command,
        cwd=SERVICE_DIRECTORY,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(completed.stdout)


def segment_signature(segments: list[dict[str, Any]]) -> str:
    return "|".join(
        f"{segment.get('marketingTransportNo', '')}@{segment.get('depDateTime', '')}>{segment.get('arrDateTime', '')}"
        for segment in segments
    )


def sort_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not offers:
        return []

    prices = [float(offer["price"]) for offer in offers]
    durations = [int(offer["totalMinutes"]) for offer in offers]
    stops = [max(0, len(offer.get("segments", [])) - 1) for offer in offers]

    def normalized(value: float, values: list[float] | list[int]) -> float:
        low, high = min(values), max(values)
        return 0 if high == low else (value - low) / (high - low)

    for offer, price, duration, stop_count in zip(offers, prices, durations, stops):
        offer["rankingScore"] = round(
            normalized(price, prices) * RANKING_WEIGHTS["price"]
            + normalized(duration, durations) * RANKING_WEIGHTS["duration"]
            + normalized(stop_count, stops) * RANKING_WEIGHTS["stops"],
            6,
        )
    return sorted(offers, key=lambda item: (item["rankingScore"], item["price"], item["totalMinutes"]))


def normalize_flyai(
    payload: SearchRequest,
    response: dict[str, Any],
    check_name: str,
    allow_unspecified_transfer: bool = False,
) -> dict[str, dict[str, Any]]:
    checked_at = iso_now()
    normalized: dict[str, dict[str, Any]] = {}
    data = response.get("data") or {}
    for item in data.get("itemList", []):
        segments = [
            segment
            for journey in item.get("journeys", [])
            for segment in journey.get("segments", [])
        ]
        if not segments or len(segments) > 2:
            continue
        if segments[0].get("depStationCode") != payload.origin or segments[-1].get("arrStationCode") != payload.destination:
            continue
        if payload.transfer:
            if len(segments) != 2:
                continue
            if segments[0].get("arrStationCode") != payload.transfer or segments[1].get("depStationCode") != payload.transfer:
                continue
        elif allow_unspecified_transfer:
            if len(segments) != 2 or segments[0].get("arrStationCode") != segments[1].get("depStationCode"):
                continue
        elif len(segments) != 1:
            continue
        try:
            price = float(item["ticketPrice"])
            departures = [datetime.fromisoformat(segment["depDateTime"]) for segment in segments]
            arrivals = [datetime.fromisoformat(segment["arrDateTime"]) for segment in segments]
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or departures[0].date().isoformat() != payload.date:
            continue
        total_minutes = int((arrivals[-1] - departures[0]).total_seconds() // 60)
        if total_minutes <= 0 or total_minutes > MAX_TOTAL_MINUTES:
            continue
        transfer_minutes = None
        if len(segments) == 2:
            transfer_minutes = int((departures[1] - arrivals[0]).total_seconds() // 60)
            if transfer_minutes < payload.min_transfer_minutes:
                continue
        signature = segment_signature(segments)
        jump_url = str(item.get("jumpUrl", ""))
        if not jump_url.startswith(("https://a.feizhu.com/", "https://www.fliggy.com/", "https://sjipiao.fliggy.com/")):
            continue
        normalized[signature] = {
            "rawSegments": segments,
            "price": price,
            "transferMinutes": transfer_minutes,
            "totalMinutes": total_minutes,
            "crossDay": arrivals[-1].date() != departures[0].date(),
            "purchaseUrl": jump_url,
            "evidence": {
                "source": f"飞猪-{check_name}",
                "provider": "飞猪",
                "checkId": check_name,
                "price": price,
                "checkedAt": checked_at,
                "url": jump_url,
            },
        }
    return normalized


def reconcile_flyai(first: dict[str, dict[str, Any]], second: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    offers: list[dict[str, Any]] = []
    for signature, candidate in first.items():
        confirmation = second.get(signature)
        if not confirmation:
            continue
        raw_segments = candidate["rawSegments"]
        segments = []
        for segment in raw_segments:
            depart = datetime.fromisoformat(segment["depDateTime"])
            arrive = datetime.fromisoformat(segment["arrDateTime"])
            segments.append(
                {
                    "from": {
                        "code": segment["depStationCode"],
                        "city": segment.get("depCityName") or segment["depStationCode"],
                        "airport": segment.get("depStationShortName") or segment.get("depStationName") or "",
                    },
                    "to": {
                        "code": segment["arrStationCode"],
                        "city": segment.get("arrCityName") or segment["arrStationCode"],
                        "airport": segment.get("arrStationShortName") or segment.get("arrStationName") or "",
                    },
                    "departTime": depart.strftime("%H:%M"),
                    "arriveTime": arrive.strftime("%H:%M"),
                    "departDate": depart.date().isoformat(),
                    "arriveDate": arrive.date().isoformat(),
                    "flightNo": segment["marketingTransportNo"],
                    "airline": segment.get("marketingTransportName") or segment["marketingTransportNo"][:2],
                    "durationMinutes": int(segment.get("duration") or (arrive - depart).total_seconds() // 60),
                }
            )
        same_price = abs(candidate["price"] - confirmation["price"]) < 0.01
        offers.append(
            {
                "id": f"flyai-verified-{hashlib.sha256(signature.encode()).hexdigest()[:16]}",
                "price": confirmation["price"],
                "provider": "飞猪",
                "tags": ["两次价格一致" if same_price else "价格有变动·请人工选择", "可跳转购买"],
                "segments": segments,
                "transferMinutes": candidate["transferMinutes"],
                "totalMinutes": candidate["totalMinutes"],
                "crossDay": candidate["crossDay"],
                "purchaseUrl": confirmation["purchaseUrl"],
                "updatedAt": confirmation["evidence"]["checkedAt"],
                "evidence": [candidate["evidence"], confirmation["evidence"]],
                "signature": signature,
            }
        )
    return sort_offers(offers)


def review_with_qwen(payload: SearchRequest, offers: list[dict[str, Any]]) -> str:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        return "not_configured"
    if not offers:
        return "no_offers"
    review_items = [
        {
            "id": offer["id"],
            "price": offer["price"],
            "flights": [segment["flightNo"] for segment in offer["segments"]],
            "airports": [offer["segments"][0]["from"]["code"], offer["segments"][-1]["to"]["code"]],
            "transferMinutes": offer["transferMinutes"],
            "sourceDomain": "a.feizhu.com",
            "date": payload.date,
        }
        for offer in offers[:10]
    ]
    request_body = {
        "model": "qwen-plus",
        "input": {
            "messages": [
                {
                    "role": "system",
                    "content": "你是机票结果安全审查器。使用联网搜索辅助检查航班号、机场和日期是否语义一致。禁止生成或改写价格。若没有发现明确冲突，回复PASS；发现明确冲突才回复REJECT。只回复一个英文单词。",
                },
                {
                    "role": "user",
                    "content": f"当前日期是{datetime.now().date().isoformat()}。查询条件：{payload.model_dump_json()}。候选结果：{json.dumps(review_items, ensure_ascii=False)}",
                },
            ]
        },
        "parameters": {
            "result_format": "message",
            "enable_search": True,
            "search_options": {"enable_source": True, "search_strategy": "turbo"},
        },
    }
    request = urllib.request.Request(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=55) as response:
            result = json.loads(response.read())
        content = result["output"]["choices"][0]["message"]["content"].strip().upper()
        return "reject" if content == "REJECT" else "pass"
    except Exception:
        return "unavailable"


def parse_page(markdown: str, origin: str, destination: str, purchase_url: str) -> list[dict[str, Any]]:
    """Best-effort extraction; keep selectors and regexes provider-specific here."""
    prices = [int(value) for value in re.findall(r"(?:¥|￥)\s*([3-9]\d{2,4})", markdown)]
    times = re.findall(r"(?<!\d)([0-2]\d:[0-5]\d)(?!\d)", markdown)
    flight_numbers = re.findall(r"\b(CA|MU|CZ|3U|HU|ZH|MF)\s?(\d{3,4})\b", markdown)
    carriers = {"CA": "中国国航", "MU": "东方航空", "CZ": "南方航空", "3U": "四川航空", "HU": "海南航空", "ZH": "深圳航空", "MF": "厦门航空"}

    offers: list[dict[str, Any]] = []
    count = min(len(prices), len(times) // 2, len(flight_numbers))
    for index in range(count):
        depart_time, arrive_time = times[index * 2 : index * 2 + 2]
        duration = (parse_clock(arrive_time) - parse_clock(depart_time)) % (24 * 60)
        if not 45 <= duration <= 720:
            continue
        prefix, number = flight_numbers[index]
        offers.append(
            {
                "price": prices[index],
                "provider": "携程",
                "tags": ["实时抓取", "价格以出票页为准"],
                "segments": [
                    {
                        "from": {"code": origin, "city": origin, "airport": ""},
                        "to": {"code": destination, "city": destination, "airport": ""},
                        "departTime": depart_time,
                        "arriveTime": arrive_time,
                        "flightNo": f"{prefix}{number}",
                        "airline": carriers.get(prefix, prefix),
                        "durationMinutes": duration,
                    }
                ],
                "transferMinutes": None,
                "totalMinutes": duration,
                "crossDay": parse_clock(arrive_time) < parse_clock(depart_time),
                "purchaseUrl": purchase_url,
                "updatedAt": datetime.now().astimezone().isoformat(),
                "evidence": [
                    {
                        "source": "携程-Crawl4AI",
                        "provider": "携程",
                        "checkId": f"ctrip-{index}",
                        "price": prices[index],
                        "checkedAt": datetime.now().astimezone().isoformat(),
                        "url": purchase_url,
                    }
                ],
            }
        )
    return offers


async def crawl_route(crawler: AsyncWebCrawler, origin: str, destination: str, date: str) -> list[dict[str, Any]]:
    url = provider_url(origin, destination, date)
    config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=45_000,
        delay_before_return_html=3.0,
        remove_overlay_elements=True,
    )
    result = await crawler.arun(url=url, config=config)
    if not result.success:
        return []
    markdown = result.markdown.raw_markdown if hasattr(result.markdown, "raw_markdown") else str(result.markdown)
    return parse_page(markdown, origin, destination, url)


def combine_transfer(
    first_legs: list[dict[str, Any]],
    second_legs: list[dict[str, Any]],
    transfer_code: str,
    min_transfer: int,
) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for first in first_legs:
        for second in second_legs:
            first_segment = first["segments"][0]
            second_segment = second["segments"][0]
            connection = (parse_clock(second_segment["departTime"]) - parse_clock(first_segment["arriveTime"])) % (24 * 60)
            if not min_transfer <= connection <= 8 * 60:
                continue
            total = first_segment["durationMinutes"] + connection + second_segment["durationMinutes"]
            if total > MAX_TOTAL_MINUTES:
                continue
            combined.append(
                {
                    **first,
                    "id": f"live-{first_segment['flightNo']}-{second_segment['flightNo']}",
                    "price": first["price"] + second["price"],
                    "segments": [first_segment, second_segment],
                    "transferMinutes": connection,
                    "totalMinutes": total,
                    "crossDay": parse_clock(first_segment["departTime"]) + total >= 24 * 60,
                    "purchaseUrl": first["purchaseUrl"],
                    "tags": ["实时抓取", f"{transfer_code} 转机 ≥ {min_transfer // 60}h"],
                    "evidence": [
                        {
                            "source": "携程-Crawl4AI",
                            "provider": "携程",
                            "checkId": f"ctrip-{first_segment['flightNo']}-{second_segment['flightNo']}",
                            "price": first["price"] + second["price"],
                            "checkedAt": datetime.now().astimezone().isoformat(),
                            "url": first["purchaseUrl"],
                        }
                    ],
                }
            )
    return sort_offers(combined)


def ctrip_match_key(offer: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (segment["flightNo"], segment["departTime"], segment["arriveTime"])
        for segment in offer.get("segments", [])
    )


def attach_ctrip_confirmation(
    flyai_offers: list[dict[str, Any]], ctrip_offers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge matching sources and preserve mismatches for manual comparison."""
    ctrip_by_route = {ctrip_match_key(offer): offer for offer in ctrip_offers}
    merged = list(flyai_offers)
    consumed: set[tuple[tuple[str, str, str], ...]] = set()
    for offer in flyai_offers:
        route_key = ctrip_match_key(offer)
        matched = ctrip_by_route.get(route_key)
        if not matched:
            continue
        reference = max(offer["price"], matched["price"])
        if abs(offer["price"] - matched["price"]) > max(
            PRICE_TOLERANCE_YUAN, reference * PRICE_TOLERANCE_RATE
        ):
            continue
        offer["evidence"].extend(matched["evidence"])
        offer["tags"] = [offer["tags"][0], "跨平台确认", "可跳转购买"]
        consumed.add(route_key)
    merged.extend(
        offer for offer in ctrip_offers if ctrip_match_key(offer) not in consumed
    )
    return sort_offers(merged)


async def checked_ctrip_session(payload: SearchRequest) -> list[dict[str, Any]]:
    """Run two independent navigations in the user's isolated Ctrip profile."""
    try:
        first_raw = await CTRIP_SESSION.query(payload.origin, payload.destination, payload.date)
        await asyncio.sleep(1)
        second_raw = await CTRIP_SESSION.query(payload.origin, payload.destination, payload.date)
        first = normalize_ctrip_response(payload, first_raw, "实时查询")
        second = normalize_ctrip_response(payload, second_raw, "实时复核")
        return reconcile_ctrip(first, second)
    except Exception as error:
        print(f"Ctrip session unavailable: {type(error).__name__}")
        return []


async def checked_qunar_session(payload: SearchRequest) -> list[dict[str, Any]]:
    """Run two independent navigations in the user's isolated Qunar profile."""
    try:
        first_raw = await QUNAR_SESSION.query(
            payload.origin,
            payload.destination,
            payload.date,
            payload.origin_city,
            payload.destination_city,
        )
        await asyncio.sleep(1)
        second_raw = await QUNAR_SESSION.query(
            payload.origin,
            payload.destination,
            payload.date,
            payload.origin_city,
            payload.destination_city,
        )
        first = normalize_qunar_response(payload, first_raw, "实时查询")
        second = normalize_qunar_response(payload, second_raw, "实时复核")
        return reconcile_qunar(first, second)
    except Exception as error:
        print(f"Qunar session unavailable: {type(error).__name__}")
        return []


async def crawl_ctrip(payload: SearchRequest) -> list[dict[str, Any]]:
    browser = BrowserConfig(
        headless=True,
        verbose=False,
        chrome_channel="chrome",
        channel="chrome",
        enable_stealth=True,
    )
    try:
        async with AsyncWebCrawler(config=browser) as crawler:
            if payload.transfer:
                first, second = await asyncio.gather(
                    crawl_route(crawler, payload.origin, payload.transfer, payload.date),
                    crawl_route(crawler, payload.transfer, payload.destination, payload.date),
                )
                return combine_transfer(first, second, payload.transfer, payload.min_transfer_minutes)
            offers = await crawl_route(crawler, payload.origin, payload.destination, payload.date)
            for index, offer in enumerate(offers):
                offer["id"] = f"live-{offer['segments'][0]['flightNo']}-{index}"
            return offers
    except Exception:
        return []


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "ctripBrowser": "connected" if cdp_available() else "offline",
        "qunarBrowser": "connected" if qunar_cdp_available() else "offline",
    }


@app.get("/api/ctrip/status")
async def ctrip_status() -> dict[str, bool | str]:
    return {
        "connected": cdp_available(),
        "qunarConnected": qunar_cdp_available(),
        "message": "携程专用浏览器已连接" if cdp_available() else "请在飞觅页面打开携程登录",
    }


def _browser_cdp_available(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


@app.get("/api/ota/status")
async def ota_status() -> dict[str, Any]:
    return {
        "providers": {
            key: {"label": item["label"], "connected": _browser_cdp_available(int(item["port"]))}
            for key, item in OTA_BROWSERS.items()
        }
    }


@app.post("/api/ota/open/{provider}")
async def open_ota_browser(provider: str) -> dict[str, Any]:
    item = OTA_BROWSERS.get(provider)
    if item is None:
        raise HTTPException(status_code=404, detail="不支持的登录平台")
    user_domain = f"gui/{os.getuid()}"
    agent = str(item["agent"])
    plist = Path.home() / "Library" / "LaunchAgents" / f"{agent}.plist"
    if subprocess.run(
        ["/bin/launchctl", "print", f"{user_domain}/{agent}"],
        capture_output=True,
        check=False,
    ).returncode != 0:
        if not plist.exists():
            raise HTTPException(status_code=503, detail=f"{item['label']}隔离浏览器尚未安装")
        subprocess.run(
            ["/bin/launchctl", "bootstrap", user_domain, str(plist)],
            capture_output=True,
            check=False,
        )
    subprocess.run(
        ["/bin/launchctl", "kickstart", f"{user_domain}/{agent}"],
        capture_output=True,
        check=False,
    )
    port = int(item["port"])
    for _ in range(20):
        if _browser_cdp_available(port):
            break
        await asyncio.sleep(0.25)
    if not _browser_cdp_available(port):
        raise HTTPException(status_code=503, detail=f"{item['label']}浏览器启动失败")
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(str(item['url']), safe='')}",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=3):
            pass
    except Exception:
        pass
    subprocess.run(["/usr/bin/open", "-a", "Google Chrome"], capture_output=True, check=False)
    return {"opened": True, "provider": provider, "label": item["label"], "connected": True}


@app.post("/api/system/stop")
async def stop_feimi() -> dict[str, bool | str]:
    """Stop the local Feimi services after the HTTP response has been sent."""
    user_domain = f"gui/{os.getuid()}"
    commands = " ".join(
        f"/bin/launchctl bootout {user_domain}/{agent} 2>/dev/null || true;"
        for agent in FEIMI_LAUNCH_AGENTS
    )
    subprocess.Popen(
        ["/bin/zsh", "-c", f"/bin/sleep 1; {commands}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"stopping": True, "message": "飞觅将在数秒内停止运行"}


@app.post("/api/search")
async def search(payload: SearchRequest) -> dict[str, Any]:
    ctrip_session_task = asyncio.create_task(checked_ctrip_session(payload))
    qunar_session_task = asyncio.create_task(checked_qunar_session(payload))
    crawl4ai_task = asyncio.create_task(crawl_ctrip(payload)) if not payload.through_only else None

    async def checked_offers(journey_type: str, allow_unspecified_transfer: bool = False) -> list[dict[str, Any]]:
        try:
            first_raw = await asyncio.to_thread(run_flyai, payload, journey_type)
            # Prevent an immediate cached replay from being mistaken for a second check.
            await asyncio.sleep(1)
            second_raw = await asyncio.to_thread(run_flyai, payload, journey_type)
            first = normalize_flyai(payload, first_raw, "实时查询", allow_unspecified_transfer)
            second = normalize_flyai(payload, second_raw, "实时复核", allow_unspecified_transfer)
            return reconcile_flyai(first, second)
        except Exception:
            return []

    route_mode = "through" if payload.through_only else "selected-transfer" if payload.transfer else "direct"
    offers = [] if payload.through_only else await checked_offers("2" if payload.transfer else "1")
    if not offers and not payload.transfer and not payload.through_only:
        offers = await checked_offers("2", allow_unspecified_transfer=True)
        if offers:
            route_mode = "auto-transfer"
            for offer in offers:
                transfer_city = offer["segments"][0]["to"]["city"]
                transfer_code = offer["segments"][0]["to"]["code"]
                offer["tags"].insert(0, f"自动经{transfer_city or transfer_code}转机")

    ctrip_session_offers = await ctrip_session_task
    qunar_session_offers = await qunar_session_task
    if not payload.transfer and not payload.through_only:
        direct_offers = [
            offer
            for offer in [*offers, *ctrip_session_offers, *qunar_session_offers]
            if len(offer["segments"]) == 1
        ]
        if direct_offers:
            offers = [offer for offer in offers if len(offer["segments"]) == 1]
            ctrip_session_offers = [offer for offer in ctrip_session_offers if len(offer["segments"]) == 1]
            qunar_session_offers = [offer for offer in qunar_session_offers if len(offer["segments"]) == 1]
            route_mode = "direct"
        else:
            offers = [offer for offer in offers if len(offer["segments"]) == 2]
            ctrip_session_offers = [offer for offer in ctrip_session_offers if len(offer["segments"]) == 2]
            qunar_session_offers = [offer for offer in qunar_session_offers if len(offer["segments"]) == 2]
            if ctrip_session_offers or qunar_session_offers:
                route_mode = "auto-transfer"
                for offer in [*ctrip_session_offers, *qunar_session_offers]:
                    transfer_city = offer["segments"][0]["to"]["city"]
                    transfer_code = offer["segments"][0]["to"]["code"]
                    offer["tags"].insert(0, f"自动经{transfer_city or transfer_code}转机")

    offers = attach_ctrip_confirmation(offers, ctrip_session_offers)
    offers = sort_offers([*offers, *qunar_session_offers])
    if crawl4ai_task is not None:
        crawl4ai_offers = await crawl4ai_task
        offers = attach_ctrip_confirmation(offers, crawl4ai_offers)
    llm_review = await asyncio.to_thread(review_with_qwen, payload, offers)
    if llm_review == "reject":
        for offer in offers:
            offer["tags"].append("Qwen 提示出票页复核")
    elif llm_review == "pass":
        for offer in offers:
            offer["tags"].append("Qwen 异常检查通过")

    offers = sort_offers(offers)

    for offer in offers:
        offer.pop("signature", None)
    return {
        "offers": offers,
        "source": "flyai+ctrip-session+qunar-session+crawl4ai",
        "verificationMode": "two-live-checks",
        "routeMode": route_mode,
        "llmReview": llm_review,
    }


@app.get("/api/alerts/status")
async def alert_status() -> dict[str, Any]:
    async with ALERTS_LOCK:
        return public_alert_status(load_alert_state())


@app.put("/api/alerts/settings")
async def update_alert_settings(payload: AlertSettingsRequest) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        was_enabled = bool(state["settings"].get("enabled"))
        if payload.recipient is not None and payload.recipient.strip():
            try:
                recipient, _ = add_recipient(state, normalize_recipient(payload.recipient))
                state["settings"]["activeRecipientId"] = recipient["id"]
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        if payload.active_recipient_id is not None:
            if not recipient_address(state, payload.active_recipient_id):
                raise HTTPException(status_code=400, detail="提醒号码不存在")
            state["settings"]["activeRecipientId"] = payload.active_recipient_id
        if payload.enabled and not state["recipients"]:
            raise HTTPException(status_code=400, detail="启用提醒前请至少添加一个 iMessage 收件号码")
        auto_test_sent = False
        if payload.enabled and not was_enabled:
            if imsg_path() is None:
                raise HTTPException(status_code=503, detail="imsg 尚未安装完成，无法启用提醒")
            try:
                for item in state["recipients"]:
                    await asyncio.to_thread(
                        send_imessage,
                        str(item["address"]),
                        "【飞觅测试】价格提醒已成功启用。此号码只接收其收藏航班的价格变化。",
                    )
            except Exception as error:
                state["settings"]["enabled"] = False
                state["status"]["lastError"] = f"启用测试发送失败：{type(error).__name__}"
                save_alert_state(state)
                raise HTTPException(status_code=503, detail="自动测试信息发送失败，提醒尚未启用；请检查‘信息’登录和自动化权限") from error
            state["status"]["lastSentAt"] = alert_now_iso()
            auto_test_sent = True
        state["settings"]["enabled"] = payload.enabled
        state["status"]["lastError"] = None
        save_alert_state(state)
        return {"autoTestSent": auto_test_sent, **public_alert_status(state)}


@app.post("/api/alerts/recipients")
async def create_alert_recipient(payload: AlertRecipientRequest) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        try:
            recipient, created = add_recipient(state, payload.recipient)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if created:
            if imsg_path() is None:
                raise HTTPException(status_code=503, detail="imsg 尚未安装完成，无法验证新号码")
            try:
                await asyncio.to_thread(
                    send_imessage,
                    str(recipient["address"]),
                    "【飞觅测试】此号码已接入价格提醒。收藏航班将按号码分别管理。",
                )
            except Exception as error:
                raise HTTPException(status_code=503, detail="新号码测试信息发送失败，未保存该号码") from error
            state["status"]["lastSentAt"] = alert_now_iso()
        save_alert_state(state)
        return {"added": created, "testSent": created, **public_alert_status(state)}


@app.delete("/api/alerts/recipients/{recipient_id}")
async def delete_alert_recipient(recipient_id: str, payload: AlertRecipientRemovalRequest | None = None) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        try:
            removed = remove_recipient(state, recipient_id, payload.move_to_recipient_id if payload else None)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        save_alert_state(state)
        return {"removed": removed, **public_alert_status(state)}


@app.post("/api/alerts/watch")
async def add_alert_watch(payload: AlertWatchRequest) -> dict[str, Any]:
    if not payload.purchase_url.startswith(
        (
            "https://flights.ctrip.com/",
            "https://flight.qunar.com/",
            "https://a.feizhu.com/",
            "https://www.fliggy.com/",
            "https://sjipiao.fliggy.com/",
        )
    ):
        raise HTTPException(status_code=400, detail="购票链接来源无效")
    data = payload.model_dump(by_alias=True)
    async with ALERTS_LOCK:
        state = load_alert_state()
        try:
            watch = upsert_watch(state, data)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        save_alert_state(state)
        return {"watchId": watch["id"], **public_alert_status(state)}


@app.delete("/api/alerts/watch/{client_offer_id}")
async def delete_alert_watch(client_offer_id: str, recipient_id: str | None = None) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        removed = remove_watch(state, client_offer_id, recipient_id)
        save_alert_state(state)
        return {"removed": removed, **public_alert_status(state)}


@app.put("/api/alerts/watch/{client_offer_id}/recipient")
async def move_alert_watch(client_offer_id: str, payload: AlertWatchRecipientRequest) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        try:
            moved = move_watch(state, client_offer_id, payload.recipient_id, payload.source_recipient_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        save_alert_state(state)
        return {"moved": moved, **public_alert_status(state)}


@app.put("/api/alerts/watch/{client_offer_id}/copy")
async def copy_alert_watch(client_offer_id: str, payload: AlertWatchCopyRequest) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        try:
            copied_watch, copied = copy_watch(
                state,
                client_offer_id,
                payload.source_recipient_id,
                payload.target_recipient_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if copied_watch is None:
            raise HTTPException(status_code=404, detail="当前号码中未找到该收藏航班")
        save_alert_state(state)
        return {"copied": copied, "watchId": copied_watch["id"], **public_alert_status(state)}


@app.get("/api/alerts/favorites")
async def list_alert_favorites(recipient_id: str | None = None) -> dict[str, Any]:
    async with ALERTS_LOCK:
        return favorite_records(load_alert_state(), recipient_id)


@app.delete("/api/alerts/history/{history_id}")
async def delete_alert_history(history_id: str) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        removed = delete_history_item(state, history_id)
        save_alert_state(state)
        return {"removed": removed, **favorite_records(state)}


@app.post("/api/alerts/test")
async def test_alert_delivery(payload: AlertTestRequest | None = None) -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        selected_id = payload.recipient_id if payload and payload.recipient_id else state["settings"].get("activeRecipientId")
        recipient = recipient_address(state, selected_id)
        if not recipient:
            raise HTTPException(status_code=400, detail="请先选择 iMessage 提醒号码")
        if imsg_path() is None:
            raise HTTPException(status_code=503, detail="imsg 尚未安装完成")
        try:
            await asyncio.to_thread(
                send_imessage,
                recipient,
                "【飞觅测试】iMessage 价格提醒已连接。此后仅在收藏航班价格上涨或下降时通知。",
            )
        except Exception as error:
            state["status"]["lastError"] = f"测试发送失败：{type(error).__name__}"
            save_alert_state(state)
            raise HTTPException(status_code=503, detail="测试信息发送失败，请检查‘信息’登录和自动化权限") from error
        state["status"]["lastSentAt"] = alert_now_iso()
        state["status"]["lastError"] = None
        save_alert_state(state)
        return {"sent": True, **public_alert_status(state)}


@app.post("/api/alerts/check")
async def check_price_alerts() -> dict[str, Any]:
    async with ALERTS_LOCK:
        state = load_alert_state()
        checked_at = alert_now_iso()
        state["status"]["lastCheckAt"] = checked_at
        if not state["settings"].get("enabled"):
            save_alert_state(state)
            return {"checked": 0, "sent": 0, "skipped": "disabled", **public_alert_status(state)}
        if not state.get("recipients") or imsg_path() is None:
            state["status"]["lastError"] = "iMessage 提醒号码或 imsg 尚未就绪"
            save_alert_state(state)
            return {"checked": 0, "sent": 0, "skipped": "not_ready", **public_alert_status(state)}

        active_watches = [
            watch
            for watch in state["watches"]
            if str(watch.get("date") or "") >= datetime.now().date().isoformat()
        ]
        grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for watch in active_watches:
            key = (
                watch.get("origin"),
                watch.get("originCity"),
                watch.get("destination"),
                watch.get("destinationCity"),
                watch.get("transfer"),
                watch.get("transferCity"),
                watch.get("date"),
                bool(watch.get("throughOnly")),
            )
            grouped.setdefault(key, []).append(watch)

        checked = 0
        sent = 0
        errors: list[str] = []
        for key, watches in grouped.items():
            origin, origin_city, destination, destination_city, transfer, transfer_city, date, through_only = key
            try:
                result = await search(
                    SearchRequest(
                        origin=origin,
                        origin_city=origin_city,
                        destination=destination,
                        destination_city=destination_city,
                        transfer=transfer,
                        transfer_city=transfer_city,
                        date=date,
                        min_transfer_minutes=120,
                        through_only=through_only,
                    )
                )
            except Exception as error:
                errors.append(f"{origin}-{destination}: {type(error).__name__}")
                continue
            offers = result.get("offers") or []
            for watch in watches:
                checked += 1
                current = next(
                    (
                        offer
                        for offer in offers
                        if offer.get("provider") == watch.get("provider")
                        and flight_key(offer.get("segments") or []) == flight_key(watch.get("segments") or [])
                    ),
                    None,
                )
                watch["lastCheckedAt"] = checked_at
                if current is None:
                    continue
                current_price = float(current["price"])
                watch["lastCheckedPrice"] = current_price
                watch["purchaseUrl"] = current.get("purchaseUrl") or watch.get("purchaseUrl")
                if abs(current_price - float(watch["lastPrice"])) < 0.01:
                    continue
                recipient = recipient_address(state, watch.get("recipientId"))
                if not recipient:
                    errors.append(f"{watch.get('id')}: RecipientMissing")
                    continue
                try:
                    await asyncio.to_thread(
                        send_imessage,
                        recipient,
                        price_change_message(watch, current, current_price),
                    )
                except Exception as error:
                    errors.append(f"{watch.get('id')}: {type(error).__name__}")
                    continue
                watch["lastPrice"] = current_price
                watch["lastNotifiedAt"] = checked_at
                sent += 1

        state["status"]["lastError"] = "；".join(errors[:3]) if errors else None
        if sent:
            state["status"]["lastSentAt"] = checked_at
        save_alert_state(state)
        return {
            "checked": checked,
            "sent": sent,
            "intervalMinutes": CHECK_INTERVAL_MINUTES,
            **public_alert_status(state),
        }
