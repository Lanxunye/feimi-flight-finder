"""Device-local state and iMessage delivery for Feimi price alerts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from copy import deepcopy
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
        "settings": {"enabled": False, "activeRecipientId": None},
        "recipients": [],
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
        if isinstance(stored.get("recipients"), list):
            state["recipients"] = [item for item in stored["recipients"] if isinstance(item, dict)]
        if isinstance(stored.get("watches"), list):
            state["watches"] = [item for item in stored["watches"] if isinstance(item, dict)]
        if isinstance(stored.get("favoriteHistory"), list):
            state["favoriteHistory"] = [item for item in stored["favoriteHistory"] if isinstance(item, dict)]
        if isinstance(stored.get("status"), dict):
            state["status"].update(stored["status"])
    return ensure_state_schema(state)


def save_state(state: dict[str, Any]) -> None:
    ensure_state_schema(state)
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(STATE_DIRECTORY, 0o700)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, STATE_FILE)
    os.chmod(STATE_FILE, 0o600)


def normalize_recipient(value: str) -> str:
    recipient = re.sub(r"[\s()-]", "", value.strip())
    if re.fullmatch(r"86\d{11}", recipient):
        recipient = f"+{recipient}"
    elif re.fullmatch(r"1\d{10}", recipient):
        recipient = f"+86{recipient}"
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


def recipient_id(address: str) -> str:
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]


def ensure_state_schema(state: dict[str, Any]) -> dict[str, Any]:
    settings = state.setdefault("settings", {})
    state.setdefault("recipients", [])
    state.setdefault("watches", [])
    state.setdefault("favoriteHistory", [])
    state.setdefault("status", {"lastCheckAt": None, "lastError": None, "lastSentAt": None})
    legacy_address = str(settings.pop("recipient", "") or "")
    if legacy_address:
        normalized = normalize_recipient(legacy_address)
        identifier = recipient_id(normalized)
        if not any(item.get("id") == identifier for item in state["recipients"]):
            state["recipients"].append({"id": identifier, "address": normalized, "createdAt": now_iso()})
        settings["activeRecipientId"] = settings.get("activeRecipientId") or identifier
    if not settings.get("activeRecipientId") and state["recipients"]:
        settings["activeRecipientId"] = state["recipients"][0].get("id")
    active_id = settings.get("activeRecipientId")
    for item in [*state["watches"], *state["favoriteHistory"]]:
        item.setdefault("recipientId", active_id)
    return state


def add_recipient(state: dict[str, Any], value: str) -> tuple[dict[str, Any], bool]:
    ensure_state_schema(state)
    address = normalize_recipient(value)
    identifier = recipient_id(address)
    current = next((item for item in state["recipients"] if item.get("id") == identifier), None)
    if current is not None:
        state["settings"]["activeRecipientId"] = identifier
        return current, False
    current = {"id": identifier, "address": address, "createdAt": now_iso()}
    state["recipients"].append(current)
    state["settings"]["activeRecipientId"] = identifier
    return current, True


def recipient_address(state: dict[str, Any], identifier: str | None) -> str:
    ensure_state_schema(state)
    item = next((item for item in state["recipients"] if item.get("id") == identifier), None)
    return str(item.get("address") or "") if item else ""


def _find_watch(
    state: dict[str, Any], client_offer_id: str, source_recipient_id: str | None = None
) -> dict[str, Any] | None:
    matches = [
        item
        for item in state["watches"]
        if item.get("clientOfferId") == client_offer_id
        and (source_recipient_id is None or item.get("recipientId") == source_recipient_id)
    ]
    if source_recipient_id is None and len(matches) > 1:
        raise ValueError("该航班已属于多个号码，请指定来源号码")
    return matches[0] if matches else None


def copy_watch(
    state: dict[str, Any],
    client_offer_id: str,
    source_recipient_id: str,
    target_recipient_id: str,
) -> tuple[dict[str, Any] | None, bool]:
    ensure_state_schema(state)
    if source_recipient_id == target_recipient_id:
        raise ValueError("目标号码不能与当前号码相同")
    if not recipient_address(state, target_recipient_id):
        raise ValueError("目标提醒号码不存在")
    source = _find_watch(state, client_offer_id, source_recipient_id)
    if source is None:
        return None, False
    existing = _find_watch(state, client_offer_id, target_recipient_id)
    if existing is not None:
        return existing, False
    copied = deepcopy(source)
    copied["recipientId"] = target_recipient_id
    copied["id"] = watch_id(copied, target_recipient_id)
    copied["createdAt"] = now_iso()
    copied["updatedAt"] = copied["createdAt"]
    copied["lastNotifiedAt"] = None
    state["watches"].append(copied)
    return copied, True


def move_watch(
    state: dict[str, Any],
    client_offer_id: str,
    target_recipient_id: str,
    source_recipient_id: str | None = None,
) -> bool:
    ensure_state_schema(state)
    if not recipient_address(state, target_recipient_id):
        raise ValueError("目标提醒号码不存在")
    watch = _find_watch(state, client_offer_id, source_recipient_id)
    if watch is None:
        return False
    if watch.get("recipientId") == target_recipient_id:
        return True
    existing = _find_watch(state, client_offer_id, target_recipient_id)
    if existing is not None:
        state["watches"].remove(watch)
        return True
    watch["recipientId"] = target_recipient_id
    watch["id"] = watch_id(watch, target_recipient_id)
    watch["updatedAt"] = now_iso()
    return True


def remove_recipient(state: dict[str, Any], identifier: str, move_to: str | None = None) -> bool:
    ensure_state_schema(state)
    if not recipient_address(state, identifier):
        return False
    linked = [item for item in state["watches"] if item.get("recipientId") == identifier]
    if linked and (not move_to or not recipient_address(state, move_to) or move_to == identifier):
        raise ValueError("该号码仍有收藏机票，请先选择接收收藏的其他号码")
    if move_to:
        for item in list(linked):
            move_watch(state, str(item.get("clientOfferId") or ""), move_to, identifier)
        for item in state["favoriteHistory"]:
            if item.get("recipientId") == identifier:
                item["recipientId"] = move_to
    state["recipients"] = [item for item in state["recipients"] if item.get("id") != identifier]
    if state["settings"].get("activeRecipientId") == identifier:
        state["settings"]["activeRecipientId"] = move_to or (state["recipients"][0]["id"] if state["recipients"] else None)
    return True


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


def watch_id(payload: dict[str, Any], assigned_recipient_id: str | None = None) -> str:
    identity = "|".join(
        [
            str(assigned_recipient_id or payload.get("recipientId") or ""),
            str(payload.get("origin") or ""),
            str(payload.get("destination") or ""),
            str(payload.get("date") or ""),
            str(payload.get("provider") or ""),
            flight_key(payload.get("segments") or []),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def upsert_watch(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    ensure_state_schema(state)
    assigned_recipient_id = payload.get("recipientId") or state["settings"].get("activeRecipientId")
    if not recipient_address(state, assigned_recipient_id):
        raise ValueError("请先添加提醒号码")
    identifier = watch_id(payload, assigned_recipient_id)
    current = next(
        (
            item
            for item in state["watches"]
            if item.get("clientOfferId") == payload.get("clientOfferId")
            and item.get("recipientId") == assigned_recipient_id
        ),
        None,
    )
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
        "recipientId": assigned_recipient_id,
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


def remove_watch(
    state: dict[str, Any], client_offer_id: str, selected_recipient_id: str | None = None
) -> bool:
    ensure_state_schema(state)
    removed = [
        item
        for item in state["watches"]
        if item.get("clientOfferId") == client_offer_id
        and (selected_recipient_id is None or item.get("recipientId") == selected_recipient_id)
    ]
    if not removed:
        return False
    removed_ids = {id(item) for item in removed}
    state["watches"] = [item for item in state["watches"] if id(item) not in removed_ids]
    removed_at = now_iso()
    for item in removed:
        state["favoriteHistory"].insert(
            0,
            {"historyId": uuid.uuid4().hex, "removedAt": removed_at, **item},
        )
    state["favoriteHistory"] = state["favoriteHistory"][:200]
    return True


def delete_history_item(state: dict[str, Any], history_id: str) -> bool:
    ensure_state_schema(state)
    before = len(state["favoriteHistory"])
    state["favoriteHistory"] = [
        item for item in state["favoriteHistory"] if item.get("historyId") != history_id
    ]
    return len(state["favoriteHistory"]) != before


def favorite_records(state: dict[str, Any], selected_recipient_id: str | None = None) -> dict[str, Any]:
    ensure_state_schema(state)
    selected = selected_recipient_id or state["settings"].get("activeRecipientId")
    active = sorted(
        [item for item in state["watches"] if item.get("recipientId") == selected],
        key=lambda item: str(item.get("updatedAt") or ""),
        reverse=True,
    )
    history = sorted(
        [item for item in state["favoriteHistory"] if item.get("recipientId") == selected],
        key=lambda item: str(item.get("removedAt") or ""),
        reverse=True,
    )
    return {"recipientId": selected, "favorites": active, "history": history}


def public_status(state: dict[str, Any]) -> dict[str, Any]:
    ensure_state_schema(state)
    active_id = state["settings"].get("activeRecipientId")
    active_address = recipient_address(state, active_id)
    recipients = [
        {
            "id": item.get("id"),
            "masked": mask_recipient(str(item.get("address") or "")),
            "watchCount": sum(1 for watch in state["watches"] if watch.get("recipientId") == item.get("id")),
        }
        for item in state["recipients"]
    ]
    active_watches = [item for item in state["watches"] if item.get("recipientId") == active_id]
    return {
        "available": True,
        "enabled": bool(state["settings"].get("enabled")),
        "recipientConfigured": bool(active_address),
        "recipientMasked": mask_recipient(active_address),
        "activeRecipientId": active_id,
        "recipients": recipients,
        "imsgAvailable": imsg_path() is not None,
        "intervalMinutes": CHECK_INTERVAL_MINUTES,
        "watchCount": len(active_watches),
        "totalWatchCount": len(state["watches"]),
        "watchedOfferIds": [item.get("clientOfferId") for item in active_watches],
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
    provider = str(new_offer.get("provider") or watch.get("provider") or "原收藏平台")
    purchase_url = str(new_offer.get("purchaseUrl") or watch.get("purchaseUrl") or "")
    return "\n".join(
        [
            f"【飞觅价格提醒】{symbol} 收藏航班价格{direction} ¥{abs(difference):g}",
            f"{watch['date']}  {route}",
            flights,
            f"原价 ¥{old_price:g} → 现价 ¥{new_price:g}",
            f"{transfer}全程 {format_duration(watch.get('totalMinutes'))}",
            f"购票平台：{provider}",
            purchase_url,
            "票价和余票以出票页面为准。",
        ]
    )
