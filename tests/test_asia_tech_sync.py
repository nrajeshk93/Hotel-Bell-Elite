"""Asia Tech read-only sync: normalizer, filter, and safety checks."""

from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest import mock

import asia_tech_client
import asia_tech_http


class AsiaTechNormalizerTests(unittest.TestCase):
    def test_normalize_asia_tech_like_payload(self):
        row = asia_tech_client._normalize_reservation(
            {
                "BookingId": "AT-9911",
                "GuestName": "Ravi Kumar",
                "CheckIn": "12-09-2026",
                "CheckOut": "15-09-2026",
                "RoomName": "Deluxe Sea View",
                "TotalAmount": "12500.50",
                "Status": "Confirmed",
                "Channel": "Booking.com",
                "Mobile": "9876543210",
                "Pax": 2,
            }
        )
        self.assertEqual(row["id"], "AT-9911")
        self.assertEqual(row["guestName"], "Ravi Kumar")
        self.assertEqual(row["checkInDate"], "2026-09-12")
        self.assertEqual(row["checkOutDate"], "2026-09-15")
        self.assertEqual(row["nights"], 3)
        self.assertEqual(row["amount"], 12500.5)
        self.assertEqual(row["status"], "upcoming")
        self.assertEqual(row["source"], "booking_com")
        self.assertEqual(row["roomTypeLabel"], "Deluxe Sea View")
        self.assertEqual(row["mobile"], "9876543210")
        self.assertEqual(row["guests"], 2)
        self.assertEqual(row["totalRooms"], 1)

    def test_normalize_total_rooms_from_count_and_room_detail(self):
        from_count = asia_tech_client._normalize_reservation(
            {
                "id": "RM-17",
                "guestName": "Group",
                "checkInDate": "2026-08-14",
                "checkOutDate": "2026-08-15",
                "NoOfRooms": 17,
            }
        )
        self.assertEqual(from_count["totalRooms"], 17)
        from_detail = asia_tech_client._normalize_reservation(
            {
                "id": "RM-3",
                "guestName": "Family",
                "checkInDate": "2026-08-14",
                "checkOutDate": "2026-08-15",
                "room_detail": [{"roomname": "Deluxe"}, {"roomname": "Deluxe"}, {"roomname": "Suite"}],
            }
        )
        self.assertEqual(from_detail["totalRooms"], 3)

    def test_assigned_room_count_from_ids_and_numbers(self):
        self.assertEqual(asia_tech_client.assigned_room_count({}), 0)
        self.assertEqual(
            asia_tech_client.assigned_room_count({"roomId": "room-101", "totalRooms": 17}),
            1,
        )
        self.assertEqual(
            asia_tech_client.assigned_room_ids(
                {"roomId": "room-101", "roomIds": ["room-101", "room-103"]}
            ),
            ["room-101", "room-103"],
        )
        self.assertEqual(
            asia_tech_client.assigned_room_count({"roomNumber": "101", "roomNumbers": ["101"]}),
            1,
        )

    def test_normalize_getbooking_payload(self):
        row = asia_tech_client._normalize_reservation(
            {
                "bookingsource": "Offline-Booking",
                "guestname": "Rahul",
                "checkin": "2026-10-14",
                "checkout": "2026-10-15",
                "bookingid": "FDR01191785411888",
                "bookingstatus": "cancelled",
                "paymentstatus": 1,
                "totalrate": 15540,
                "adults": 6,
                "guestemail": "rahul45@gmail.com",
                "guestmobile": "099876543",
                "guestinfo": "Late arrival after 10 PM",
                "room_detail": [
                    {
                        "rooms": 1,
                        "roomid": 405,
                        "roomname": "Standard Room",
                        "mealplanid": 2,
                        "mealplan": "CP",
                    }
                ],
            }
        )
        self.assertEqual(row["id"], "FDR01191785411888")
        self.assertEqual(row["guestName"], "Rahul")
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(row["source"], "direct")
        self.assertEqual(row["amount"], 15540.0)
        self.assertEqual(row["paymentStatus"], "paid")
        self.assertEqual(row["roomTypeLabel"], "Standard Room")
        self.assertEqual(row["mobile"], "099876543")
        self.assertEqual(row["email"], "rahul45@gmail.com")
        self.assertEqual(row["guests"], 6)
        self.assertEqual(row["mealPlan"], "CP · Breakfast")
        self.assertEqual(row["specialNotes"], "Late arrival after 10 PM")

    def test_meal_plan_to_rate_plan_extracts_codes(self):
        self.assertEqual(asia_tech_client.meal_plan_to_rate_plan("CP · Breakfast"), "CP")
        self.assertEqual(asia_tech_client.meal_plan_to_rate_plan("AP · All meals"), "AP")
        self.assertEqual(asia_tech_client.meal_plan_to_rate_plan("MAP"), "MAP")
        self.assertEqual(asia_tech_client.meal_plan_to_rate_plan("bb"), "CP")
        self.assertEqual(asia_tech_client.meal_plan_to_rate_plan(""), "")

    def test_provider_status_stays_upcoming_until_local_checkin(self):
        today = date.today()
        row = asia_tech_client._normalize_reservation(
            {
                "bookingid": "IN-HOUSE-1",
                "guestname": "In House",
                "checkin": today.isoformat(),
                "checkout": (today + timedelta(days=1)).isoformat(),
                "bookingstatus": "confirmed",
                "totalrate": 1000,
            }
        )
        self.assertEqual(row["status"], "upcoming")
        future = asia_tech_client._normalize_reservation(
            {
                "bookingid": "FUT-1",
                "guestname": "Future",
                "checkin": (today + timedelta(days=5)).isoformat(),
                "checkout": (today + timedelta(days=7)).isoformat(),
                "bookingstatus": "confirmed",
                "totalrate": 1000,
            }
        )
        self.assertEqual(future["status"], "upcoming")
        past = asia_tech_client._normalize_reservation(
            {
                "bookingid": "PAST-1",
                "guestname": "Past",
                "checkin": (today - timedelta(days=5)).isoformat(),
                "checkout": (today - timedelta(days=2)).isoformat(),
                "bookingstatus": "confirmed",
                "totalrate": 1000,
            }
        )
        self.assertEqual(past["status"], "upcoming")
        local_in = asia_tech_client._normalize_reservation(
            {
                "bookingid": "LOCAL-IN-1",
                "guestname": "Local In",
                "checkin": today.isoformat(),
                "checkout": (today + timedelta(days=1)).isoformat(),
                "status": "checked_in",
                "statusSource": "local",
                "totalrate": 1000,
            }
        )
        self.assertEqual(local_in["status"], "checked_in")
        departed = asia_tech_client._normalize_reservation(
            {
                "bookingid": "OUT-1",
                "guestname": "Departed",
                "checkin": (today - timedelta(days=5)).isoformat(),
                "checkout": (today - timedelta(days=2)).isoformat(),
                "status": "checked_out",
                "statusSource": "local",
                "totalrate": 1000,
            }
        )
        self.assertEqual(departed["status"], "checked_out")
        ignored_api_out = asia_tech_client._normalize_reservation(
            {
                "bookingid": "API-OUT-1",
                "guestname": "Api Out",
                "checkin": (today - timedelta(days=5)).isoformat(),
                "checkout": (today - timedelta(days=2)).isoformat(),
                "bookingstatus": "checkedout",
                "totalrate": 1000,
            }
        )
        self.assertEqual(ignored_api_out["status"], "upcoming")
        ignored_api_in = asia_tech_client._normalize_reservation(
            {
                "bookingid": "API-IN-1",
                "guestname": "Api In",
                "checkin": today.isoformat(),
                "checkout": (today + timedelta(days=1)).isoformat(),
                "bookingstatus": "checkedin",
                "totalrate": 1000,
            }
        )
        self.assertEqual(ignored_api_in["status"], "upcoming")
        kpis = asia_tech_client.compute_kpis(
            [row, future, past, local_in, departed, ignored_api_out, ignored_api_in]
        )
        self.assertEqual(kpis["checked_in"], 1)
        self.assertEqual(kpis["upcoming"], 5)
        self.assertEqual(kpis["checked_out"], 1)

    def test_count_checkouts_for_selected_date(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "out-today",
                    "guestName": "Out Today",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "out-earlier",
                    "guestName": "Out Earlier",
                    "checkInDate": "2026-08-01",
                    "checkOutDate": "2026-08-05",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 200,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "in-house",
                    "guestName": "In House",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 300,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "still-listed-out",
                    "guestName": "Still Listed Out",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 50,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "leaving-today",
                    "guestName": "Leaving Today",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 75,
                }
            ),
        ]
        self.assertEqual(
            asia_tech_client.count_checkouts_for_date(
                rows, date_from="2026-08-12", date_to="2026-08-12"
            ),
            2,
        )
        self.assertEqual(
            asia_tech_client.count_checkouts_for_date(rows, date_from="", date_to=""),
            3,
        )

    def test_filter_checkout_only_matches_checked_out_kpi(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "out-today",
                    "guestName": "Out Today",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "out-earlier",
                    "guestName": "Out Earlier",
                    "checkInDate": "2026-08-01",
                    "checkOutDate": "2026-08-05",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 200,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "in-house",
                    "guestName": "In House",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 300,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "leaving-today",
                    "guestName": "Leaving Today",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 75,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "cancelled-out",
                    "guestName": "Cancelled Out",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "cancelled",
                    "source": "direct",
                    "amount": 10,
                }
            ),
        ]
        filtered = asia_tech_client.filter_reservations(
            rows,
            date_from="2026-08-12",
            date_to="2026-08-12",
            checkout_only=True,
        )
        self.assertEqual(
            {row["id"] for row in filtered},
            {"out-today", "leaving-today"},
        )
        no_date = asia_tech_client.filter_reservations(
            rows, date_from="", date_to="", checkout_only=True
        )
        self.assertEqual(
            {row["id"] for row in no_date},
            {"out-today", "out-earlier"},
        )

    def test_count_upcoming_for_selected_date(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "arrive-today",
                    "guestName": "Arrive Today",
                    "checkInDate": "2026-08-12",
                    "checkOutDate": "2026-08-14",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "arrive-later",
                    "guestName": "Arrive Later",
                    "checkInDate": "2026-08-20",
                    "checkOutDate": "2026-08-22",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 200,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "in-house",
                    "guestName": "In House",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 300,
                }
            ),
        ]
        self.assertEqual(
            asia_tech_client.count_upcoming_for_date(
                rows, date_from="2026-08-12", date_to="2026-08-12"
            ),
            1,
        )
        self.assertEqual(
            asia_tech_client.count_upcoming_for_date(
                rows, date_from="2026-08-20", date_to="2026-08-20"
            ),
            1,
        )
        self.assertEqual(
            asia_tech_client.count_upcoming_for_date(rows, date_from="", date_to=""),
            2,
        )

    def test_count_checked_in_for_selected_date(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "in-house",
                    "guestName": "In House",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "stale-inhouse",
                    "guestName": "Stale Inhouse",
                    "checkInDate": "2026-08-18",
                    "checkOutDate": "2026-08-19",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 200,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "departed",
                    "guestName": "Departed",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_out",
                    "statusSource": "local",
                    "source": "direct",
                    "amount": 300,
                }
            ),
        ]
        self.assertEqual(
            asia_tech_client.count_checked_in_for_date(
                rows, date_from="2026-08-12", date_to="2026-08-12"
            ),
            1,
        )
        self.assertEqual(
            asia_tech_client.count_checked_in_for_date(rows, date_from="", date_to=""),
            2,
        )

    def test_filter_by_status_and_search(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "1",
                    "guestName": "Alpha",
                    "checkInDate": "2026-09-01",
                    "checkOutDate": "2026-09-03",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "2",
                    "guestName": "Beta",
                    "checkInDate": "2026-09-02",
                    "checkOutDate": "2026-09-04",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "expedia",
                    "amount": 200,
                }
            ),
        ]
        filtered = asia_tech_client.filter_reservations(rows, status="checked_in")
        self.assertEqual([r["id"] for r in filtered], ["2"])
        found = asia_tech_client.filter_reservations(rows, q="alpha")
        self.assertEqual([r["id"] for r in found], ["1"])

    def test_filter_hides_cancelled_unless_explicit(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "ok",
                    "guestName": "Confirmed Guest",
                    "checkInDate": "2026-09-01",
                    "checkOutDate": "2026-09-03",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "cx",
                    "guestName": "Cancelled Guest",
                    "checkInDate": "2026-09-01",
                    "checkOutDate": "2026-09-03",
                    "bookingstatus": "cancelled",
                    "source": "direct",
                    "amount": 50,
                }
            ),
        ]
        self.assertEqual(rows[1]["status"], "cancelled")
        shown = asia_tech_client.filter_reservations(rows, status="all")
        self.assertEqual([r["id"] for r in shown], ["ok"])
        only_cx = asia_tech_client.filter_reservations(rows, status="cancelled")
        self.assertEqual([r["id"] for r in only_cx], ["cx"])
        kpis = asia_tech_client.compute_kpis(rows)
        self.assertEqual(kpis["total"], 1)
        self.assertEqual(kpis["upcoming"], 1)

    def test_enrich_reservations_from_hotel_rooms_marks_assigned(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "FDR45021786516297",
                    "guestName": "Mr. Nelson Fernandes",
                    "checkInDate": "2026-08-15",
                    "checkOutDate": "2026-08-16",
                    "status": "upcoming",
                    "source": "asia_tech",
                    "amount": 5000,
                }
            )
        ]
        self.assertFalse(rows[0].get("roomAssigned"))
        enriched = asia_tech_client.enrich_reservations_from_hotel_rooms(
            rows,
            [
                {
                    "id": "room-102",
                    "number": "102",
                    "status": "reserved",
                    "roomTypeLabel": "Premium Room",
                    "stay": {
                        "reservationId": "FDR45021786516297",
                        "guestName": "Mr. Nelson Fernandes",
                    },
                }
            ],
        )
        self.assertTrue(enriched[0]["roomAssigned"])
        self.assertEqual(enriched[0]["roomNumber"], "102")
        self.assertEqual(enriched[0]["roomTypeLabel"], "Premium Room")

    def test_enrich_clears_stale_assignment_when_rooms_vacant(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "FDR45021786686378",
                    "guestName": "Group Guest",
                    "checkInDate": "2026-08-14",
                    "checkOutDate": "2026-08-15",
                    "status": "upcoming",
                    "source": "asia_tech",
                    "amount": 85000,
                    "roomNumber": "103",
                    "roomNumbers": ["103", "101", "104"],
                    "roomIds": ["room-103", "room-101", "room-104"],
                    "roomAssigned": True,
                }
            )
        ]
        enriched = asia_tech_client.enrich_reservations_from_hotel_rooms(
            rows,
            [
                {
                    "id": "room-103",
                    "number": "103",
                    "status": "vacant",
                    "stay": None,
                },
                {
                    "id": "room-101",
                    "number": "101",
                    "status": "vacant",
                },
            ],
        )
        self.assertFalse(enriched[0]["roomAssigned"])
        self.assertEqual(enriched[0]["roomNumbers"], [])
        self.assertEqual(enriched[0]["roomNumber"], "")

    def test_enrich_partial_assignment_keeps_matched_rooms_only(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "FDR45021786686378",
                    "guestName": "Group Guest",
                    "checkInDate": "2026-08-14",
                    "checkOutDate": "2026-08-15",
                    "status": "upcoming",
                    "source": "asia_tech",
                    "amount": 85000,
                    "totalRooms": 17,
                }
            )
        ]
        enriched = asia_tech_client.enrich_reservations_from_hotel_rooms(
            rows,
            [
                {
                    "id": "room-101",
                    "number": "101",
                    "status": "reserved",
                    "roomTypeLabel": "Deluxe with Balcony",
                    "stay": {
                        "reservationId": "FDR45021786686378",
                        "guestName": "Group Guest",
                    },
                },
                {
                    "id": "room-102",
                    "number": "102",
                    "status": "vacant",
                },
            ],
        )
        self.assertTrue(enriched[0]["roomAssigned"])
        self.assertEqual(enriched[0]["roomNumbers"], ["101"])
        self.assertEqual(enriched[0]["totalRooms"], 17)

    def test_enrich_ignores_occupied_room_with_mismatched_guest(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "FDR45021786686378",
                    "guestName": "Manoj Vijayan Antony Kibson",
                    "checkInDate": "2026-08-14",
                    "checkOutDate": "2026-08-15",
                    "status": "upcoming",
                    "source": "asia_tech",
                    "amount": 85000,
                    "totalRooms": 17,
                }
            )
        ]
        enriched = asia_tech_client.enrich_reservations_from_hotel_rooms(
            rows,
            [
                {
                    "id": "room-101",
                    "number": "101",
                    "status": "occupied",
                    "roomTypeLabel": "Deluxe with Balcony",
                    "stay": {
                        "reservationId": "FDR45021786686378",
                        "guestName": "Ratnesh",
                    },
                }
            ],
        )
        self.assertFalse(enriched[0]["roomAssigned"])
        self.assertEqual(enriched[0]["roomNumbers"], [])

    def test_enrich_checked_in_matches_occupied_room_by_guest(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "FDR45021786516084",
                    "guestName": "Mr. Hakam Singh",
                    "checkInDate": "2026-08-15",
                    "checkOutDate": "2026-08-16",
                    "status": "checked_in",
                    "statusSource": "local",
                    "source": "asia_tech",
                    "amount": 5000,
                    "totalRooms": 1,
                }
            )
        ]
        enriched = asia_tech_client.enrich_reservations_from_hotel_rooms(
            rows,
            [
                {
                    "id": "room-201",
                    "number": "201",
                    "status": "occupied",
                    "roomTypeLabel": "Deluxe",
                    "stay": {
                        "guestName": "Mr. Hakam Singh",
                        "reservationId": "",
                    },
                }
            ],
        )
        self.assertTrue(enriched[0]["roomAssigned"])
        self.assertEqual(enriched[0]["roomNumbers"], ["201"])

    def test_heal_skips_occupied_rooms(self):
        settings = {
            "asia_tech_state": {
                "assignments": {
                    "FDR45021786686378": {
                        "roomId": "room-101",
                        "roomNumber": "101",
                        "roomIds": ["room-101"],
                        "roomNumbers": ["101"],
                    }
                }
            }
        }
        rooms = [
            {
                "id": "room-101",
                "number": "101",
                "status": "occupied",
                "stay": {
                    "guestName": "Ratnesh",
                    "reservationId": "",
                },
            }
        ]
        changed = asia_tech_client.heal_assigned_reservation_ids_on_rooms(
            settings, rooms
        )
        self.assertFalse(changed)
        self.assertEqual(rooms[0]["stay"].get("reservationId") or "", "")

    def test_prune_stale_room_assignments_drops_vacant_links(self):
        settings = {
            "asia_tech_state": {
                "assignments": {
                    "FDR45021786686378": {
                        "roomId": "room-103",
                        "roomNumber": "103",
                        "roomIds": ["room-103", "room-101"],
                        "roomNumbers": ["103", "101"],
                        "roomTypeLabel": "Deluxe with Balcony",
                    },
                    "FDR45021786516297": {
                        "roomId": "room-102",
                        "roomNumber": "102",
                        "roomIds": ["room-102"],
                        "roomNumbers": ["102"],
                        "roomTypeLabel": "Premium Room",
                    },
                }
            }
        }
        rooms = [
            {"id": "room-103", "number": "103", "status": "vacant"},
            {"id": "room-101", "number": "101", "status": "vacant"},
            {
                "id": "room-102",
                "number": "102",
                "status": "reserved",
                "stay": {"reservationId": "FDR45021786516297"},
            },
        ]
        nxt = asia_tech_client.prune_stale_room_assignments(settings, rooms)
        self.assertIsNotNone(nxt)
        assignments = asia_tech_client.get_state(nxt).get("assignments") or {}
        self.assertNotIn("FDR45021786686378", assignments)
        self.assertEqual(assignments["FDR45021786516297"]["roomNumbers"], ["102"])

    def test_filter_by_date_range(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "1",
                    "guestName": "Early",
                    "checkInDate": "2026-08-01",
                    "checkOutDate": "2026-08-03",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 100,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "2",
                    "guestName": "Mid",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 200,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "3",
                    "guestName": "Late",
                    "checkInDate": "2026-08-20",
                    "checkOutDate": "2026-08-22",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 300,
                }
            ),
        ]
        filtered = asia_tech_client.filter_reservations(
            rows, date_from="2026-08-09", date_to="2026-08-15"
        )
        self.assertEqual([r["id"] for r in filtered], ["2"])
        single = asia_tech_client.filter_reservations(rows, on_date="2026-08-01")
        self.assertEqual([r["id"] for r in single], ["1"])
        checkout_day = asia_tech_client.filter_reservations(rows, on_date="2026-08-12")
        self.assertEqual([r["id"] for r in checkout_day], ["2"])
        cleared = asia_tech_client.filter_reservations(rows, date_from="", date_to="")
        self.assertEqual(len(cleared), 3)


class AsiaTechLiveListTests(unittest.TestCase):
    def setUp(self):
        asia_tech_http.clear_caches()
        self._env = {
            "ASIA_TECH_USERNAME": os.environ.get("ASIA_TECH_USERNAME"),
            "ASIA_TECH_PASSWORD": os.environ.get("ASIA_TECH_PASSWORD"),
            "ASIA_TECH_HOTEL_ID": os.environ.get("ASIA_TECH_HOTEL_ID"),
            "ASIA_TECH_BASE_URL": os.environ.get("ASIA_TECH_BASE_URL"),
        }
        os.environ["ASIA_TECH_USERNAME"] = "demo_user"
        os.environ["ASIA_TECH_PASSWORD"] = "demo_pass"
        os.environ["ASIA_TECH_HOTEL_ID"] = "119"
        os.environ["ASIA_TECH_BASE_URL"] = "http://provider.asiatech.in"

    def tearDown(self):
        asia_tech_http.clear_caches()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_live_list_merges_provider_and_local(self):
        settings = {
            "panels": {
                "asia_tech": {
                    "values": {
                        "asia_tech_mode": {"kind": "text", "value": "live"},
                    }
                }
            },
            "asia_tech_state": {
                "created": [
                    {
                        "id": "LOC-1",
                        "guestName": "Walk In",
                        "checkInDate": "2026-09-10",
                        "checkOutDate": "2026-09-11",
                        "status": "upcoming",
                        "source": "walk_in",
                        "amount": 500,
                    }
                ],
                "assignments": {},
                "overrides": {},
            },
        }

        def fake_fetch(**kwargs):
            self.assertTrue(kwargs.get("force_refresh") is False or kwargs.get("force_refresh") is True)
            return (
                [
                    {
                        "bookingid": "AT-100",
                        "guestname": "Provider Guest",
                        "checkin": "2026-09-08",
                        "checkout": "2026-09-09",
                        "status": "Confirmed",
                        "channel": "Agoda",
                        "total": 2500,
                    }
                ],
                {
                    "synced_at": "2026-08-12T10:00:00",
                    "cached": False,
                    "rooms_ok": True,
                    "bookings_path": "/json/bookings",
                    "error": "",
                    "base_url": "http://provider.asiatech.in",
                },
            )

        with mock.patch.object(asia_tech_client, "fetch_bookings", side_effect=fake_fetch):
            rows = asia_tech_client.list_provider_reservations(settings)
        ids = {r["id"] for r in rows}
        self.assertIn("AT-100", ids)
        self.assertIn("LOC-1", ids)
        meta = asia_tech_client.get_last_sync_meta()
        self.assertEqual(meta["source"], "asia_tech")
        self.assertEqual(meta["bookings_path"], "/json/bookings")
        self.assertEqual(meta["mode"], "live")

    def test_discovery_error_surfaces_in_meta(self):
        settings = {
            "panels": {
                "asia_tech": {
                    "values": {"asia_tech_mode": {"kind": "text", "value": "live"}}
                }
            }
        }

        with mock.patch.object(
            asia_tech_client,
            "fetch_bookings",
            return_value=(
                [],
                {
                    "synced_at": "2026-08-12T10:00:00",
                    "cached": False,
                    "rooms_ok": True,
                    "bookings_path": None,
                    "error": "Asia Tech bookings endpoint not available — ask vendor for reservations API.",
                    "base_url": "http://provider.asiatech.in",
                },
            ),
        ):
            rows = asia_tech_client.list_provider_reservations(settings)
        self.assertEqual(rows, [])
        meta = asia_tech_client.get_last_sync_meta()
        self.assertIn("bookings endpoint not available", meta["error"])

    def test_list_drops_persisted_rows_from_other_hotel(self):
        settings = {
            "panels": {
                "asia_tech": {
                    "values": {"asia_tech_mode": {"kind": "text", "value": "live"}}
                }
            },
            "asia_tech_state": {
                "provider_hotel_id": "119",
                "provider_rows": [
                    {
                        "id": "FDR0119OLD",
                        "guestName": "Demo Guest",
                        "checkInDate": "2026-08-01",
                        "checkOutDate": "2026-08-02",
                        "status": "upcoming",
                        "amount": 100,
                    }
                ],
                "created": [],
                "assignments": {},
                "overrides": {},
            },
        }
        os.environ["ASIA_TECH_HOTEL_ID"] = "4502"

        with mock.patch.object(
            asia_tech_client,
            "fetch_bookings",
            return_value=(
                [
                    {
                        "bookingid": "FDR4502NEW",
                        "guestname": "Bell Elite Guest",
                        "checkin": "2026-08-12",
                        "checkout": "2026-08-13",
                        "status": "Confirmed",
                        "total": 85000,
                    }
                ],
                {
                    "synced_at": "2026-08-12T10:00:00",
                    "cached": False,
                    "rooms_ok": True,
                    "bookings_path": "/json/getbooking",
                    "error": "",
                    "base_url": "https://provider.asiatech.in",
                },
            ),
        ):
            rows = asia_tech_client.list_provider_reservations(settings)
        ids = {r["id"] for r in rows}
        self.assertIn("FDR4502NEW", ids)
        self.assertNotIn("FDR0119OLD", ids)

    def test_live_sync_meta_includes_asia_tech_lookback(self):
        settings = {
            "panels": {
                "asia_tech": {
                    "values": {"asia_tech_mode": {"kind": "text", "value": "live"}}
                }
            }
        }
        with mock.patch.object(
            asia_tech_client,
            "fetch_bookings",
            return_value=(
                [
                    {
                        "bookingid": "FDR4502NEW",
                        "guestname": "Bell Elite Guest",
                        "checkin": "2026-08-12",
                        "checkout": "2026-08-13",
                        "status": "Confirmed",
                        "total": 1000,
                    }
                ],
                {
                    "synced_at": "2026-08-13T00:10:00",
                    "cached": False,
                    "rooms_ok": True,
                    "bookings_path": "/json/getbooking",
                    "error": "",
                    "base_url": "https://provider.asiatech.in",
                    "fromdate": "2026-08-04",
                    "todate": "2026-08-13",
                    "pulled": 1,
                },
            ),
        ):
            asia_tech_client.list_provider_reservations(settings)
        meta = asia_tech_client.get_last_sync_meta()
        self.assertEqual(meta["fromdate"], "2026-08-04")
        self.assertEqual(meta["todate"], "2026-08-13")
        self.assertEqual(meta["pulled"], 1)
        self.assertIn("last 10 days", meta["coverage"])
        self.assertIn("Channel Manager", meta["coverage"])

    def test_cm_booking_report_rows_merge_into_live_list(self):
        settings = {
            "panels": {
                "asia_tech": {
                    "values": {
                        "asia_tech_mode": {"kind": "text", "value": "live"},
                        "asia_tech_cm_email": {
                            "kind": "text",
                            "value": "front@hotel.com",
                        },
                        "asia_tech_cm_password": {
                            "kind": "text",
                            "value": "cm-secret",
                        },
                    }
                }
            }
        }
        with mock.patch.object(
            asia_tech_client,
            "fetch_bookings",
            return_value=(
                [
                    {
                        "bookingid": "FDR4502API",
                        "guestname": "Api Guest",
                        "checkin": "2026-08-12",
                        "checkout": "2026-08-13",
                        "status": "Confirmed",
                        "total": 1000,
                    }
                ],
                {
                    "synced_at": "2026-08-13T00:10:00",
                    "cached": False,
                    "rooms_ok": True,
                    "bookings_path": "/json/getbooking",
                    "error": "",
                    "base_url": "https://provider.asiatech.in",
                    "fromdate": "2026-08-04",
                    "todate": "2026-08-13",
                    "pulled": 1,
                },
            ),
        ), mock.patch(
            "asia_tech_cm.fetch_checkin_booking_reports",
            return_value=(
                [
                    {
                        "bookingid": "FDR45021785571083",
                        "guestname": "Hemant Nathrao Reddy",
                        "checkin": "2026-08-13",
                        "checkout": "2026-08-14",
                        "bookingstatus": "confirmed",
                        "totalrate": 5000,
                    }
                ],
                {"cm_ok": True, "cm_pulled": 1, "cm_error": "", "cm_days": 1},
            ),
        ):
            rows = asia_tech_client.list_provider_reservations(settings)
        ids = {r["id"] for r in rows}
        self.assertIn("FDR4502API", ids)
        self.assertIn("FDR45021785571083", ids)
        meta = asia_tech_client.get_last_sync_meta()
        self.assertTrue(meta.get("cm_ok"))
        self.assertEqual(meta.get("cm_pulled"), 1)
        self.assertIn("check-in date", meta.get("coverage", "").lower())


class AsiaTechCMParseTests(unittest.TestCase):
    def test_parse_booking_report_html_extracts_checkin_row(self):
        import asia_tech_cm

        html = """
        <table>
          <tr>
            <th>Booking ID</th><th>Guest Name</th><th>Check-In</th><th>Check-Out</th><th>Total</th>
          </tr>
          <tr>
            <td>FDR45021785571083</td>
            <td>Hemant Nathrao Reddy</td>
            <td>13-08-2026</td>
            <td>14-08-2026</td>
            <td>5,000</td>
          </tr>
        </table>
        """
        rows = asia_tech_cm.parse_booking_report_html(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bookingid"], "FDR45021785571083")
        self.assertEqual(rows[0]["guestname"], "Hemant Nathrao Reddy")
        self.assertEqual(rows[0]["checkin"], "2026-08-13")
        self.assertEqual(rows[0]["checkout"], "2026-08-14")
        self.assertEqual(rows[0]["totalrate"], 5000.0)


class AsiaTechSafetyTests(unittest.TestCase):
    def test_http_module_has_no_write_paths(self):
        src_path = asia_tech_http.__file__
        with open(src_path, "r", encoding="utf-8") as handle:
            src = handle.read().lower()
        forbidden = (
            "updateinv",
            "updaterate",
            "setinv",
            "setrate",
            "pushbooking",
            "createbooking",
            "cancelbooking",
            "modifybooking",
            "/json/update",
            "/json/set",
        )
        for needle in forbidden:
            self.assertNotIn(needle, src, f"write-style path leaked: {needle}")
        self.assertIn("/json/rooms", src)
        self.assertIn("bookings", src)

    def test_looks_like_booking_list(self):
        rows = asia_tech_http._looks_like_booking_list(
            {"booking_list": [{"guestname": "A", "checkin": "2026-01-01"}]}
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["guestname"], "A")

    def test_http_upgrades_to_https(self):
        self.assertEqual(
            asia_tech_http._normalize_base("http://provider.asiatech.in"),
            "https://provider.asiatech.in",
        )
        self.assertEqual(
            asia_tech_http._normalize_base("https://provider.asiatech.in/"),
            "https://provider.asiatech.in",
        )

    def test_getbooking_included_in_candidates(self):
        self.assertEqual(asia_tech_http.GETBOOKING_PATH, "/json/getbooking")
        self.assertIn("/json/getbooking", asia_tech_http.BOOKING_PATH_CANDIDATES)

    def test_merge_booking_rows_keeps_earlier_stays(self):
        asia_tech_http.clear_caches()
        first = asia_tech_http.merge_booking_rows(
            [{"bookingid": "A", "checkin": "2026-08-24", "guestname": "Future"}]
        )
        self.assertEqual(len(first), 1)
        second = asia_tech_http.merge_booking_rows(
            [{"bookingid": "B", "checkin": "2026-08-12", "guestname": "Today"}]
        )
        ids = {row["bookingid"] for row in second}
        self.assertEqual(ids, {"A", "B"})
        asia_tech_http.clear_caches()
        self.assertEqual(asia_tech_http.merge_booking_rows([]), [])

    def test_merge_booking_rows_resets_when_hotel_changes(self):
        asia_tech_http.clear_caches()
        asia_tech_http.merge_booking_rows(
            [{"bookingid": "FDR0119OLD", "guestname": "Demo"}],
            cred_key="https://provider.asiatech.in|old|119",
        )
        second = asia_tech_http.merge_booking_rows(
            [{"bookingid": "FDR4502NEW", "guestname": "Bell Elite"}],
            cred_key="https://provider.asiatech.in|new|4502",
        )
        ids = {row["bookingid"] for row in second}
        self.assertEqual(ids, {"FDR4502NEW"})
        asia_tech_http.clear_caches()

    def test_booking_date_window_stays_within_lookback(self):
        start, end = asia_tech_http.booking_date_window(today=date(2026, 8, 12))
        self.assertEqual(end, "2026-08-12")
        self.assertEqual(start, "2026-08-03")


class AsiaTechDateParseTests(unittest.TestCase):
    def test_parse_iso_strips_time_and_dmy(self):
        self.assertEqual(
            asia_tech_client._parse_iso("24/08/2026 14:00:00").isoformat(),
            "2026-08-24",
        )
        self.assertEqual(
            asia_tech_client._parse_iso("2026-08-24T11:00:00").isoformat(),
            "2026-08-24",
        )

    def test_filter_keeps_checkin_when_checkout_missing(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "open-checkout",
                    "guestName": "No Checkout",
                    "checkInDate": "2026-08-24",
                    "checkOutDate": "",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 100,
                }
            )
        ]
        filtered = asia_tech_client.filter_reservations(
            rows, date_from="2026-08-24", date_to="2026-08-24"
        )
        self.assertEqual([row["id"] for row in filtered], ["open-checkout"])


if __name__ == "__main__":
    unittest.main()
