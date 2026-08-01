import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import main
import price_alerts


def watch_payload(price=800):
    return {
        "clientOfferId": "offer-1",
        "origin": "SWA",
        "destination": "URC",
        "transfer": "CKG",
        "transferCity": "重庆",
        "date": "2026-08-07",
        "throughOnly": True,
        "provider": "携程",
        "price": price,
        "segments": [
            {"flightNo": "CZ3859", "departTime": "08:00", "arriveTime": "10:00", "from": {"city": "揭阳"}, "to": {"city": "重庆"}},
            {"flightNo": "CZ2311", "departTime": "15:25", "arriveTime": "19:30", "from": {"city": "重庆"}, "to": {"city": "乌鲁木齐"}},
        ],
        "purchaseUrl": "https://flights.ctrip.com/example",
        "totalMinutes": 690,
        "transferMinutes": 325,
    }


class PriceAlertTests(unittest.TestCase):
    def test_persists_private_settings_and_keeps_existing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(price_alerts, "STATE_DIRECTORY", Path(directory)), patch.object(
                price_alerts, "STATE_FILE", Path(directory) / "price-alerts.json"
            ):
                state = price_alerts.default_state()
                first = price_alerts.upsert_watch(state, watch_payload(800))
                second = price_alerts.upsert_watch(state, watch_payload(760))
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(second["lastPrice"], 800)
                price_alerts.save_state(state)
                self.assertEqual(price_alerts.load_state()["watches"][0]["baselinePrice"], 800)
                self.assertEqual((Path(directory) / "price-alerts.json").stat().st_mode & 0o777, 0o600)

    def test_formats_rise_and_drop_notifications(self):
        state = price_alerts.default_state()
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        lower = price_alerts.price_change_message(watch, {"purchaseUrl": "https://flights.ctrip.com/new"}, 720)
        higher = price_alerts.price_change_message(watch, {}, 860)
        self.assertIn("价格下降 ¥80", lower)
        self.assertIn("CZ3859 + CZ2311", lower)
        self.assertIn("价格上涨 ¥60", higher)

    def test_validates_and_masks_recipient(self):
        self.assertEqual(price_alerts.normalize_recipient("+86 138-0013-8000"), "+8613800138000")
        self.assertEqual(price_alerts.mask_recipient("+8613800138000"), "+86***8000")
        with self.assertRaises(ValueError):
            price_alerts.normalize_recipient("not-a-recipient")

    def test_favorite_can_be_archived_and_history_deleted(self):
        state = price_alerts.default_state()
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        self.assertEqual(len(price_alerts.favorite_records(state)["favorites"]), 1)
        self.assertTrue(price_alerts.remove_watch(state, watch["clientOfferId"]))
        records = price_alerts.favorite_records(state)
        self.assertEqual(records["favorites"], [])
        self.assertEqual(len(records["history"]), 1)
        self.assertIn("removedAt", records["history"][0])
        self.assertTrue(price_alerts.delete_history_item(state, records["history"][0]["historyId"]))
        self.assertEqual(price_alerts.favorite_records(state)["history"], [])


class PriceAlertCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabling_alert_sends_one_automatic_test(self) -> None:
        state = price_alerts.default_state()
        state["settings"]["recipient"] = "+8613800138000"
        with patch.object(main, "load_alert_state", return_value=state), patch.object(
            main, "save_alert_state"
        ), patch.object(main, "imsg_path", return_value="/tmp/imsg"), patch.object(
            main.asyncio, "to_thread", new=AsyncMock()
        ) as to_thread:
            result = await main.update_alert_settings(main.AlertSettingsRequest(enabled=True))
            repeated = await main.update_alert_settings(main.AlertSettingsRequest(enabled=True))

        self.assertTrue(result["autoTestSent"])
        self.assertFalse(repeated["autoTestSent"])
        self.assertTrue(state["settings"]["enabled"])
        to_thread.assert_awaited_once()

    async def test_changed_price_sends_once_and_advances_notification_baseline(self) -> None:
        state = price_alerts.default_state()
        state["settings"] = {"enabled": True, "recipient": "+8613800138000"}
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        current_offer = {
            "provider": watch["provider"],
            "price": 720,
            "segments": watch["segments"],
            "purchaseUrl": watch["purchaseUrl"],
        }
        sender = Mock()
        with patch.object(main, "load_alert_state", return_value=state), patch.object(
            main, "save_alert_state"
        ), patch.object(main, "imsg_path", return_value="/tmp/imsg"), patch.object(
            main, "search", new=AsyncMock(return_value={"offers": [current_offer]})
        ), patch.object(main, "send_imessage", sender):
            result = await main.check_price_alerts()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["sent"], 1)
        self.assertEqual(watch["lastPrice"], 720)
        sender.assert_called_once()

    async def test_unchanged_price_does_not_send(self) -> None:
        state = price_alerts.default_state()
        state["settings"] = {"enabled": True, "recipient": "+8613800138000"}
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        current_offer = {
            "provider": watch["provider"],
            "price": 800,
            "segments": watch["segments"],
            "purchaseUrl": watch["purchaseUrl"],
        }
        sender = Mock()
        with patch.object(main, "load_alert_state", return_value=state), patch.object(
            main, "save_alert_state"
        ), patch.object(main, "imsg_path", return_value="/tmp/imsg"), patch.object(
            main, "search", new=AsyncMock(return_value={"offers": [current_offer]})
        ), patch.object(main, "send_imessage", sender):
            result = await main.check_price_alerts()

        self.assertEqual(result["sent"], 0)
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
