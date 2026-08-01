"""Device-local state and iMessage delivery for Feimi price alerts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


CHECK_INTERVAL_MINUTES = 30
STATE_DIRECTORY = Path(
    os.getenv("FEIMI_RUNTIME_STATE_DIR", Path(__file__).resolve().parent / ".runtime-state")
)
STATE_FILE = STATE_DIRECTORY / "price-alerts.json"
PHONE_PATTERN = re.compile(r"^\+?\d{7,20}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def default_state() -> dict[str, Any]:
    return {
        "settings": {"enabled": False, "recipient": ""},
        "watches": [],
        "favoriteHistory": [],
        "status": {"lastCheckAt": None, "lastError": None, "lastSentAt": None},
    }


def load_state() -> dict[str, Any]:
    try:
        stored = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default_state()
    state = default_state()
    if isinstance(stored, dict):
        if isinstance(stored.get("settings"), dict):
            state["settings"].update(stored["settings"])
        if isinstance(stored.get("watches"), list):
            state["watches"] = [item for item in stored["watches"] if isinstance(item, dict)]
        if isinstance(stored.get("favoriteHistory"), list):
            state["favoriteHistory"] = [item for item in stored["favoriteHistory"] if isinstance(item, dict)]
        if isinstance(stored.get("status"), dict):
            state["status"].update(stored["status"])
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_DIRECTORY, 0o700)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE_FILE)
    os.chmod(STATE_FILE, 0o600)


def normalize_recipient(value: str) -> str:
    recipient = re.sub(r"[\s()-]", "", value.strip())
    if PHONE_PATTERN.fullmatch(recipient) or EMAIL_PATTERN.fullmatch(recipient):
        return recipient
    raise ValueError("请输入有效的 iMessage 手机号（建议含国家区号）或 Apple ID 邮箱")


def mask_recipient(recipient: str) -> str:
    if not recipient:
        return ""
    if "@" in recipient:
        name, domain = recipient.split("@", 1)
        return f"{name[:2]}***@{domain}"
    return f"{recipient[:3]}***{recipient[-4:]}" if len(recipient) > 7 else "***"


def imsg_path() -> str | None:
    candidates = [
        os.getenv("IMSG_PATH"),
        str(STATE_DIRECTORY.parent / "bin/imsg"),
        "/opt/homebrew/bin/imsg",
        "/usr/local/bin/imsg",
        shutil.which("imsg"),
    ]
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def send_imessage(recipient: str, message: str) -> None:
    executable = imsg_path()
    if not executable:
        raise RuntimeError("imsg 尚未安装")
    completed = subprocess.run(
        [
            executable,
            "send",
            "--to",
            recipient,
            "--text",
            message,
            "--service",
            "imessage",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"imsg 发送失败（状态 {completed.returncode}）")


def flight_key(segments: list[dict[str, Any]]) -> str:
    return "|".join(
        f"{segment.get('flightNo', '')}@{segment.get('departTime', '')}>{segment.get('arriveTime', '')}"
        for segment in segments
    )


def watch_id(payload: dict[str, Any]) -> str:
    identity = "|".join(
        [
            str(payload.get("origin") or ""),
            str(payload.get("destination") or ""),
            str(payload.get("date") or ""),
            str(payload.get("provider") or ""),
            flight_key(payload.get("segments") or []),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def upsert_watch(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    identifier = watch_id(payload)
    current = next((item for item in state["watches"] if item.get("id") == identifier), None)
    checked_at = now_iso()
    metadata = {
        "id": identifier,
        "clientOfferId": payload["clientOfferId"],
        "origin": payload["origin"],
        "destination": payload["destination"],
        "transfer": payload.get("transfer"),
        "transferCity": payload.get("transferCity"),
        "date": payload["date"],
        "throughOnly": bool(payload.get("throughOnly")),
        "provider": payload["provider"],
        "segments": payload["segments"],
        "purchaseUrl": payload["purchaseUrl"],
        "totalMinutes": payload["totalMinutes"],
        "transferMinutes": payload.get("transferMinutes"),
        "updatedAt": checked_at,
    }
    if current is None:
        current = {
            **metadata,
            "baselinePrice": payload["price"],
            "lastPrice": payload["price"],
            "lastCheckedPrice": payload["price"],
            "createdAt": checked_at,
            "lastCheckedAt": checked_at,
            "lastNotifiedAt": None,
        }
        state["watches"].append(current)
    else:
        current.update(metadata)
    return current


def remove_watch(state: dict[str, Any], client_offer_id: str) -> bool:
    removed = [item for item in state["watches"] if item.get("clientOfferId") == client_offer_id]
    if not removed:
        return False
    state["watches"] = [item for item in state["watches"] if item.get("clientOfferId") != client_offer_id]
    removed_at = now_iso()
    for item in removed:
        state["favoriteHistory"].insert(
            0,
            {"historyId": uuid.uuid4().hex, "removedAt": removed_at, **item},
        )
    state["favoriteHistory"] = state["favoriteHistory"][:200]
    return True


def delete_history_item(state: dict[str, Any], history_id: str) -> bool:
    before = len(state["favoriteHistory"])
    state["favoriteHistory"] = [
        item for item in state["favoriteHistory"] if item.get("historyId") != history_id
    ]
    return len(state["favoriteHistory"]) != before


def favorite_records(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    active = sorted(state["watches"], key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    history = sorted(state["favoriteHistory"], key=lambda item: str(item.get("removedAt") or ""), reverse=True)
    return {"favorites": active, "history": history}


def public_status(state: dict[str, Any]) -> dict[str, Any]:
    recipient = str(state["settings"].get("recipient") or "")
    return {
        "available": True,
        "enabled": bool(state["settings"].get("enabled")),
        "recipientConfigured": bool(recipient),
        "recipientMasked": mask_recipient(recipient),
        "imsgAvailable": imsg_path() is not None,
        "intervalMinutes": CHECK_INTERVAL_MINUTES,
        "watchCount": len(state["watches"]),
        "watchedOfferIds": [item.get("clientOfferId") for item in state["watches"]],
        "lastCheckAt": state["status"].get("lastCheckAt"),
        "lastSentAt": state["status"].get("lastSentAt"),
        "lastError": state["status"].get("lastError"),
    }


def format_duration(minutes: int | None) -> str:
    if minutes is None:
        return ""
    hours, remainder = divmod(int(minutes), 60)
    return f"{hours}小时{f'{remainder}分' if remainder else ''}"


def price_change_message(watch: dict[str, Any], new_offer: dict[str, Any], new_price: float) -> str:
    old_price = float(watch["lastPrice"])
    difference = new_price - old_price
    direction = "上涨" if difference > 0 else "下降"
    symbol = "↑" if difference > 0 else "↓"
    flights = " + ".join(segment["flightNo"] for segment in watch["segments"])
    route = " → ".join(
        [watch["segments"][0]["from"]["city"]]
        + [segment["to"]["city"] for segment in watch["segments"]]
    )
    transfer = (
        f"转机 {format_duration(watch.get('transferMinutes'))} · "
        if watch.get("transferMinutes") is not None
        else "直飞 · "
    )
    return "\n".join(
        [
            f"【飞觅价格提醒】{symbol} 收藏航班价格{direction} ¥{abs(difference):g}",
            f"{watch['date']}  {route}",
            flights,
            f"原价 ¥{old_price:g} → 现价 ¥{new_price:g}",
            f"{transfer}全程 {format_duration(watch.get('totalMinutes'))}",
            str(new_offer.get("purchaseUrl") or watch.get("purchaseUrl") or ""),
            "票价和余票以出票页面为准。",
        ]
    )
