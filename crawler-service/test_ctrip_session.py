import unittest

from ctrip_session import normalize_ctrip_response, reconcile_ctrip


class Payload:
    origin = "PEK"
    destination = "CTU"
    transfer = None
    date = "2026-07-26"
    min_transfer_minutes = 120
    through_only = False


def unit(number: str, origin: str, destination: str, departure: str, arrival: str):
    return {
        "flightNo": number,
        "marketAirlineName": "测试航司",
        "departureAirportCode": origin,
        "arrivalAirportCode": destination,
        "departureCityName": origin,
        "arrivalCityName": destination,
        "departureDateTime": departure,
        "arrivalDateTime": arrival,
    }


def response(price: int, second_arrival: str = "2026-07-26 15:00:00"):
    return {
        "data": {
            "flightItineraryList": [
                {
                    "flightSegments": [
                        {
                            "flightList": [
                                unit("CA1001", "PEK", "CTU", "2026-07-26 08:00:00", "2026-07-26 11:00:00")
                            ]
                        }
                    ],
                    "priceList": [{"adultPrice": price, "adultTax": 50}],
                },
                {
                    "flightSegments": [
                        {
                            "flightList": [
                                unit("MU2001", "PEK", "XIY", "2026-07-26 08:00:00", "2026-07-26 10:00:00"),
                                unit("MU2002", "XIY", "CTU", "2026-07-26 12:30:00", second_arrival),
                            ]
                        }
                    ],
                    "priceList": [{"sortPrice": price + 100}],
                },
            ]
        }
    }


class CtripSessionTests(unittest.TestCase):
    def test_reconciles_different_prices_and_enforces_route_limits(self):
        first = normalize_ctrip_response(Payload(), response(600), "实时查询")
        second = normalize_ctrip_response(Payload(), response(630), "实时复核")
        offers = reconcile_ctrip(first, second)
        self.assertEqual(len(offers), 2)
        transfer = next(offer for offer in offers if len(offer["segments"]) == 2)
        self.assertEqual(transfer["transferMinutes"], 150)
        self.assertEqual(transfer["totalMinutes"], 420)
        self.assertEqual([item["price"] for item in transfer["evidence"]], [700, 730])
        self.assertEqual(transfer["tags"][0], "价格有变动·请人工选择")

        long_journey = normalize_ctrip_response(
            Payload(), response(600, "2026-07-27 00:01:00"), "实时查询"
        )
        self.assertEqual(len(long_journey), 1)

    def test_filters_to_an_explicit_transfer(self):
        payload = Payload()
        payload.transfer = "XIY"
        selected = normalize_ctrip_response(payload, response(600), "实时查询")
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(next(iter(selected.values()))["segments"]), 2)

    def test_through_filter_requires_an_explicit_label_and_uses_the_through_fare(self):
        payload = Payload()
        payload.through_only = True
        raw = response(600)
        itinerary = raw["data"]["flightItineraryList"][1]
        itinerary["priceList"] = [
            {"sortPrice": 700},
            {
                "sortPrice": 860,
                "priceTags": [
                    {
                        "data": {
                            "tag": "通程值机",
                            "desc": "一次支付、一次值机、一次安检、行李直挂、全程无忧",
                        }
                    }
                ],
            },
        ]
        selected = normalize_ctrip_response(payload, raw, "实时查询")
        self.assertEqual(len(selected), 1)
        offer = next(iter(selected.values()))
        self.assertEqual(offer["price"], 860)
        self.assertTrue(offer["throughFlight"])
        self.assertIn("行李直挂", offer["throughServices"])

        itinerary["priceList"] = [{"sortPrice": 700}]
        self.assertEqual(normalize_ctrip_response(payload, raw, "实时查询"), {})

    def test_protected_through_flight_can_use_a_100_minute_airline_connection(self):
        payload = Payload()
        payload.origin = "SWA"
        payload.destination = "URC"
        payload.date = "2026-07-24"
        payload.through_only = True
        itinerary = {
            "itineraryTags": [{"label": "通程", "type": "ApprovedVirtualFlight"}],
            "flightSegments": [
                {
                    "flightList": [
                        unit("3U6758", "SWA", "TFU", "2026-07-24 11:05:00", "2026-07-24 13:40:00"),
                        unit("3U6515", "TFU", "URC", "2026-07-24 15:20:00", "2026-07-24 18:40:00"),
                    ]
                }
            ],
            "priceList": [
                {
                    "sortPrice": 1680,
                    "priceTags": [
                        {
                            "data": {
                                "tag": "通程快线",
                                "desc": "一次支付、一次值机、一次安检、行李直挂、全程无忧",
                            }
                        }
                    ],
                }
            ],
        }
        selected = normalize_ctrip_response(
            payload,
            {"data": {"flightItineraryList": [itinerary]}},
            "实时查询",
        )
        self.assertEqual(len(selected), 1)
        offer = next(iter(selected.values()))
        self.assertEqual([segment["flightNo"] for segment in offer["segments"]], ["3U6758", "3U6515"])
        self.assertEqual(offer["transferMinutes"], 100)
        self.assertTrue(offer["throughFlight"])

        itinerary["itineraryTags"] = []
        itinerary["priceList"] = [{"sortPrice": 1680}]
        self.assertEqual(
            normalize_ctrip_response(
                payload,
                {"data": {"flightItineraryList": [itinerary]}},
                "实时查询",
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
