import unittest

from qunar_session import normalize_qunar_response, reconcile_qunar


class Payload:
    origin = "PEK"
    origin_city = "北京"
    destination = "CTU"
    destination_city = "成都"
    transfer = None
    transfer_city = None
    date = "2026-07-26"
    min_transfer_minutes = 120
    through_only = False


def info(number: str, origin: str, destination: str, departure: str, arrival: str):
    dep_date, dep_time = departure.split("T")
    arr_date, arr_time = arrival.split("T")
    return {
        "airCode": number,
        "depAirport": f"{origin}机场",
        "depAirportCode": origin,
        "depDate": dep_date,
        "depTime": dep_time,
        "arrAirport": f"{destination}机场",
        "arrAirportCode": destination,
        "arrDate": arr_date,
        "arrTime": arr_time,
        "fullName": "测试航司",
    }


def response(direct_price: int, transfer_price: int):
    return {
        "data": {
            "flights": [
                {
                    "binfo": info("CA1001", "PEK", "CTU", "2026-07-26T08:00", "2026-07-26T11:00"),
                    "code": "CA1001",
                    "priceLabel": [],
                },
                {
                    "binfo1": info("MU2001", "PEK", "XIY", "2026-07-26T08:00", "2026-07-26T10:00"),
                    "binfo2": info("MU2002", "XIY", "CTU", "2026-07-26T12:30", "2026-07-26T15:00"),
                    "code": "MU2001/MU2002",
                    "transCity": "西安",
                    "priceLabel": [{"name": "取消延误免费改", "note": ["航班调整可免费办理另一程改签"]}],
                },
            ]
        },
        "_feimiRenderedPrices": {
            "CA1001": [direct_price],
            "MU2001/MU2002": [transfer_price],
        },
    }


class QunarSessionTests(unittest.TestCase):
    def test_uses_rendered_prices_and_keeps_both_live_checks(self):
        first = normalize_qunar_response(Payload(), response(470, 690), "实时查询")
        second = normalize_qunar_response(Payload(), response(490, 710), "实时复核")
        offers = reconcile_qunar(first, second)
        self.assertEqual(len(offers), 2)
        direct = next(offer for offer in offers if len(offer["segments"]) == 1)
        self.assertEqual([item["price"] for item in direct["evidence"]], [470, 490])
        self.assertEqual(direct["tags"][0], "价格有变动·请人工选择")
        transfer = next(offer for offer in offers if len(offer["segments"]) == 2)
        self.assertEqual(transfer["transferMinutes"], 150)
        self.assertEqual(transfer["totalMinutes"], 420)
        self.assertFalse(transfer["throughFlight"])

    def test_selected_transfer_and_safety_filter(self):
        payload = Payload()
        payload.transfer = "XIY"
        payload.transfer_city = "西安"
        selected = normalize_qunar_response(payload, response(470, 690), "实时查询")
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(next(iter(selected.values()))["segments"]), 2)

        payload.transfer = "WUH"
        payload.transfer_city = "武汉"
        self.assertEqual(normalize_qunar_response(payload, response(470, 690), "实时查询"), {})

    def test_through_filter_requires_explicit_protection(self):
        payload = Payload()
        payload.through_only = True
        raw = response(470, 690)
        self.assertEqual(normalize_qunar_response(payload, raw, "实时查询"), {})
        transfer = raw["data"]["flights"][1]
        transfer["priceLabel"] = [{"name": "通程值机", "note": ["一次支付，行李直挂，航变保障"]}]
        selected = normalize_qunar_response(payload, raw, "实时查询")
        self.assertEqual(len(selected), 1)
        self.assertTrue(next(iter(selected.values()))["throughFlight"])


if __name__ == "__main__":
    unittest.main()
