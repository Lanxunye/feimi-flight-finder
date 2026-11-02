import tempfile
import unittest
from datetime import date, timedelta
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
        "date": (date.today() + timedelta(days=30)).isoformat(),
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


def state_with_recipient(address="+8613800138000"):
    state = price_alerts.default_state()
    recipient, _ = price_alerts.add_recipient(state, address)
    return state, recipient


class PriceAlertTests(unittest.TestCase):
    def test_persists_private_settings_and_keeps_existing_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(price_alerts, "STATE_DIRECTORY", Path(directory)), patch.object(
                price_alerts, "STATE_FILE", Path(directory) / "price-alerts.json"
            ):
                state, _ = state_with_recipient()
                first = price_alerts.upsert_watch(state, watch_payload(800))
                second = price_alerts.upsert_watch(state, watch_payload(760))
                self.assertEqual(first["id"], second["id"])
                self.assertEqual(second["lastPrice"], 800)
                price_alerts.save_state(state)
                self.assertEqual(price_alerts.load_state()["watches"][0]["baselinePrice"], 800)
                self.assertEqual((Path(directory) / "price-alerts.json").stat().st_mode & 0o777, 0o600)

    def test_formats_rise_and_drop_notifications(self):
        state, _ = state_with_recipient()
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        lower = price_alerts.price_change_message(watch, {"purchaseUrl": "https://flights.ctrip.com/new"}, 720)
        higher = price_alerts.price_change_message(watch, {}, 860)
        self.assertIn("价格下降 ¥80", lower)
        self.assertIn("CZ3859 + CZ2311", lower)
        self.assertIn("购票平台：携程", lower)
        self.assertIn("https://flights.ctrip.com/new", lower)
        self.assertIn("价格上涨 ¥60", higher)

    def test_validates_and_masks_recipient(self):
        self.assertEqual(price_alerts.normalize_recipient("+86 138-0013-8000"), "+8613800138000")
        self.assertEqual(price_alerts.normalize_recipient("8613800138000"), "+8613800138000")
        self.assertEqual(price_alerts.mask_recipient("+8613800138000"), "+86***8000")
        with self.assertRaises(ValueError):
            price_alerts.normalize_recipient("not-a-recipient")

    def test_favorite_can_be_archived_and_history_deleted(self):
        state, _ = state_with_recipient()
        watch = price_alerts.upsert_watch(state, watch_payload(800))
        self.assertEqual(len(price_alerts.favorite_records(state)["favorites"]), 1)
        self.assertTrue(price_alerts.remove_watch(state, watch["clientOfferId"]))
        records = price_alerts.favorite_records(state)
        self.assertEqual(records["favorites"], [])
        self.assertEqual(len(records["history"]), 1)
        self.assertIn("removedAt", records["history"][0])
        self.assertTrue(price_alerts.delete_history_item(state, records["history"][0]["historyId"]))
        self.assertEqual(price_alerts.favorite_records(state)["history"], [])

    def test_two_recipients_own_and_move_separate_favorites(self):
        state, first = state_with_recipient("+8613800138000")
        second, _ = price_alerts.add_recipient(state, "+8613900000000")
        first_payload = watch_payload(800)
        first_payload["recipientId"] = first["id"]
        second_payload = watch_payload(900)
        second_payload.update({"clientOfferId": "offer-2", "date": (date.today() + timedelta(days=31)).isoformat(), "recipientId": second["id"]})
        price_alerts.upsert_watch(state, first_payload)
        price_alerts.upsert_watch(state, second_payload)

        self.assertEqual(len(price_alerts.favorite_records(state, first["id"])["favorites"]), 1)
        self.assertEqual(len(price_alerts.favorite_records(state, second["id"])["favorites"]), 1)
        self.assertTrue(price_alerts.move_watch(state, "offer-1", second["id"]))
        self.assertEqual(price_alerts.favorite_records(state, first["id"])["favorites"], [])
        self.assertEqual(len(price_alerts.favorite_records(state, second["id"])["favorites"]), 2)
        self.assertTrue(price_alerts.remove_recipient(state, second["id"], first["id"]))
        self.assertEqual(len(price_alerts.favorite_records(state, first["id"])["favorites"]), 2)

    def test_favorite_copy_is_independent_between_recipients(self):
        state, first = state_with_recipient("+8613800138000")
        second, _ = price_alerts.add_recipient(state, "+8613900000000")
        payload = watch_payload(800)
        payload["recipientId"] = first["id"]
        source = price_alerts.upsert_watch(state, payload)

        copied, created = price_alerts.copy_watch(
            state, source["clientOfferId"], first["id"], second["id"]
        )
        self.assertTrue(created)
        self.assertIsNotNone(copied)
        self.assertNotEqual(source["id"], copied["id"])
        self.assertEqual(len(price_alerts.favorite_records(state, first["id"])["favorites"]), 1)
        self.assertEqual(len(price_alerts.favorite_records(state, second["id"])["favorites"]), 1)

        repeated, created_again = price_alerts.copy_watch(
            state, source["clientOfferId"], first["id"], second["id"]
        )
        self.assertFalse(created_again)
        self.assertEqual(repeated["id"], copied["id"])
        self.assertTrue(price_alerts.remove_watch(state, source["clientOfferId"], first["id"]))
        self.assertEqual(price_alerts.favorite_records(state, first["id"])["favorites"], [])
        self.assertEqual(len(price_alerts.favorite_records(state, second["id"])["favorites"]), 1)

    def test_migrates_legacy_recipient_and_favorites(self):
        state = price_alerts.default_state()
        state["settings"]["recipient"] = "+8613800138000"
        state["watches"].append({"clientOfferId": "legacy-offer"})
        price_alerts.ensure_state_schema(state)
        self.assertEqual(len(state["recipients"]), 1)
        self.assertEqual(state["watches"][0]["recipientId"], state["recipients"][0]["id"])


class PriceAlertCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_endpoint_keeps_source_and_target_independent(self) -> None:
        state, first = state_with_recipient("+8613800138000")
        second, _ = price_alerts.add_recipient(state, "+8613900000000")
        payload = watch_payload(800)
        payload["recipientId"] = first["id"]
        price_alerts.upsert_watch(state, payload)

        with patch.object(main, "load_alert_state", return_value=state), patch.object(
            main, "save_alert_state"
        ):
            result = await main.copy_alert_watch(
                "offer-1",
                main.AlertWatchCopyRequest(
                    sourceRecipientId=first["id"], targetRecipientId=second["id"]
                ),
            )
            first_folder = await main.list_alert_favorites(first["id"])
            second_folder = await main.list_alert_favorites(second["id"])
            await main.delete_alert_watch("offer-1", first["id"])
            second_after_source_removal = await main.list_alert_favorites(second["id"])

        self.assertTrue(result["copied"])
        self.assertEqual(len(first_folder["favorites"]), 1)
        self.assertEqual(len(second_folder["favorites"]), 1)
        self.assertEqual(len(second_after_source_removal["favorites"]), 1)

    async def test_enabling_alert_sends_one_automatic_test(self) -> None:
        state, _ = state_with_recipient()
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
        state, _ = state_with_recipient()
        state["settings"]["enabled"] = True
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
        state, _ = state_with_recipient()
        state["settings"]["enabled"] = True
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
