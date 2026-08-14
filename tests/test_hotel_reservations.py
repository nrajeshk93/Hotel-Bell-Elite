"""Hotel Reservations manager — Asia Tech stub provider + page APIs."""

import os
import tempfile
import unittest
from unittest import mock

import asia_tech_client
import db as db_mod


class HotelReservationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        import app as app_mod

        self.app_mod = app_mod
        self.app = app_mod.app
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        conn = db_mod.get_db()
        try:
            admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            self.admin_id = admin["id"]
        finally:
            conn.close()

        self.user = {
            "id": self.admin_id,
            "username": "admin",
            "full_name": "Administrator",
            "is_admin": True,
            "is_active": True,
            "dashboard_access": set(),
            "stores_access": set(),
        }
        self._get_user_patch = mock.patch.object(
            app_mod, "get_current_user", return_value=self.user
        )
        self._get_user_patch.start()

        # Reservations stub tests must not inherit live Asia Tech env from local .env.
        self._asia_env = {}
        for key in (
            "ASIA_TECH_USERNAME",
            "ASIA_TECH_PASSWORD",
            "ASIA_TECH_HOTEL_ID",
            "ASIA_TECH_BASE_URL",
        ):
            self._asia_env[key] = os.environ.pop(key, None)

    def tearDown(self):
        self._get_user_patch.stop()
        for key, value in self._asia_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_reservations_page_and_nav(self):
        page = self.client.get("/hotel/reservations")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="hotel-reservations-page"', html)
        self.assertIn("data-hotel-reservations", html)
        self.assertIn("de-nav-hotel-reservations", html)
        self.assertIn("Total Reservations", html)
        self.assertIn("hres-table-body", html)
        self.assertIn('data-sort="guest"', html)
        self.assertIn("pl-sortable", html)
        self.assertIn("hbe-scroll-panel", html)
        self.assertIn("Assign Room", html)
        self.assertIn("hres-assign-modal", html)
        self.assertIn("hres-actions-card", html)
        self.assertNotIn("hres-pagination-pages", html)
        self.assertNotIn("hres-page-size", html)
        self.assertIn("hotel_reservations.js", html)
        self.assertIn("hres-sync-banner", html)
        self.assertIn("hres-date-range-trigger", html)
        self.assertIn("hres-date-from", html)
        self.assertIn("hres-date-to", html)
        self.assertIn("sales_date_range.js", html)
        self.assertIn("hotel_reservations.js?v=27", html)
        js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "hotel_reservations.js")
        js = open(js_path, encoding="utf-8").read()
        self.assertIn("function initDateRangePicker", js)
        self.assertIn("initDateRangePicker();", js)
        self.assertIn('id="hres-edit-meal"', html)
        self.assertIn('id="hres-edit-meal-listbox"', html)
        self.assertIn('id="hres-edit-notes"', html)
        self.assertIn('id="hres-edit-total-rooms"', html)
        self.assertIn("['Total Room'", js)

        rooms = self.client.get("/hotel/rooms")
        self.assertEqual(rooms.status_code, 200)
        rooms_html = rooms.get_data(as_text=True)
        self.assertIn("de-nav-hotel-reservations", rooms_html)

    def test_list_api_stub_without_key(self):
        resp = self.client.get("/hotel/api/reservations?page=1&page_size=all")
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "stub")
        self.assertFalse(payload["hasApiKey"])
        self.assertIn("kpis", payload)
        self.assertEqual(payload["kpis"]["total"], 0)
        self.assertEqual(payload["kpis"]["checked_in"], 0)
        self.assertEqual(payload["kpis"]["upcoming"], 0)
        self.assertEqual(payload["kpis"]["checked_out"], 0)
        self.assertEqual(payload["reservations"], [])
        self.assertEqual(payload["pagination"]["total"], 0)
        self.assertTrue(payload["pagination"].get("scroll"))

    def test_settings_api_key_masked_and_preserved(self):
        put = self.client.put(
            "/hotel/api/settings",
            json={
                "settings": {
                    "panels": {
                        "asia_tech": {
                            "values": {
                                "asia_tech_api_key": {
                                    "kind": "text",
                                    "value": "secret-asia-key-123",
                                },
                                "asia_tech_base_url": {
                                    "kind": "text",
                                    "value": "https://api.asiatech.in",
                                },
                                "asia_tech_mode": {"kind": "text", "value": "stub"},
                            }
                        }
                    }
                }
            },
        )
        self.assertEqual(put.status_code, 200)
        saved = put.get_json()
        self.assertTrue(saved["ok"])
        masked = saved["settings"]["panels"]["asia_tech"]["values"]["asia_tech_api_key"][
            "value"
        ]
        self.assertEqual(masked, asia_tech_client.MASKED_API_KEY)
        self.assertNotIn("secret-asia-key-123", put.get_data(as_text=True))

        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        get_payload = get_resp.get_json()
        self.assertTrue(get_payload["settings"]["asia_tech_has_api_key"])
        again = get_payload["settings"]["panels"]["asia_tech"]["values"][
            "asia_tech_api_key"
        ]["value"]
        self.assertEqual(again, asia_tech_client.MASKED_API_KEY)

        # Saving the masked value must keep the real secret in state.
        put2 = self.client.put(
            "/hotel/api/settings",
            json={
                "settings": {
                    "panels": {
                        "asia_tech": {
                            "values": {
                                "asia_tech_api_key": {
                                    "kind": "text",
                                    "value": asia_tech_client.MASKED_API_KEY,
                                },
                                "asia_tech_mode": {"kind": "text", "value": "stub"},
                            }
                        }
                    }
                }
            },
        )
        self.assertEqual(put2.status_code, 200)
        conn = db_mod.get_db()
        try:
            raw = db_mod.get_hotel_settings(conn)
        finally:
            conn.close()
        self.assertEqual(asia_tech_client.get_api_key(raw), "secret-asia-key-123")

    def test_assign_room_updates_local_inventory(self):
        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Assign Guest",
                "mobile": "9000011122",
                "email": "assign@example.com",
                "checkInDate": "2026-09-10",
                "checkOutDate": "2026-09-12",
                "amount": 5000,
                "source": "direct",
                "status": "upcoming",
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        unassigned = create.get_json()["reservation"]
        self.assertFalse(unassigned.get("roomAssigned"))

        rooms_resp = self.client.get("/hotel/api/rooms")
        self.assertEqual(rooms_resp.status_code, 200)
        vacant = [
            r
            for r in rooms_resp.get_json().get("rooms") or []
            if str(r.get("status") or "").lower() == "vacant"
        ]
        self.assertTrue(vacant)
        room = vacant[0]

        assign = self.client.post(
            f"/hotel/api/reservations/{unassigned['id']}/assign",
            json={"roomId": room["id"]},
        )
        self.assertEqual(assign.status_code, 200, assign.get_data(as_text=True))
        payload = assign.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reservation"]["roomId"], room["id"])
        self.assertTrue(payload["reservation"]["roomAssigned"])
        self.assertEqual(payload["room"]["status"], "reserved")
        stay = payload["room"].get("stay") or {}
        self.assertEqual(stay.get("guestName"), unassigned["guestName"])

        detail = self.client.get(f"/hotel/api/reservations/{unassigned['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.get_json()["reservation"]["roomNumber"], room["number"])

    def test_assign_room_rejected_for_cancelled_reservation(self):
        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Cancelled Guest",
                "mobile": "9000011133",
                "email": "cancelled@example.com",
                "checkInDate": "2026-09-20",
                "checkOutDate": "2026-09-22",
                "amount": 4000,
                "source": "direct",
                "status": "cancelled",
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        reservation = create.get_json()["reservation"]
        self.assertEqual(str(reservation.get("status") or "").lower(), "cancelled")

        rooms_resp = self.client.get("/hotel/api/rooms")
        self.assertEqual(rooms_resp.status_code, 200)
        vacant = [
            r
            for r in rooms_resp.get_json().get("rooms") or []
            if str(r.get("status") or "").lower() == "vacant"
        ]
        self.assertTrue(vacant)

        assign = self.client.post(
            f"/hotel/api/reservations/{reservation['id']}/assign",
            json={"roomId": vacant[0]["id"]},
        )
        self.assertEqual(assign.status_code, 400, assign.get_data(as_text=True))
        payload = assign.get_json()
        self.assertFalse(payload.get("ok"))
        self.assertIn("cancelled", str(payload.get("error") or "").lower())

    def test_assign_rooms_as_merge_group_up_to_total_rooms(self):
        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Group Guest",
                "mobile": "9000011155",
                "email": "group@example.com",
                "checkInDate": "2026-10-10",
                "checkOutDate": "2026-10-12",
                "amount": 8000,
                "source": "direct",
                "status": "upcoming",
                "totalRooms": 2,
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        booking = create.get_json()["reservation"]
        self.assertEqual(booking.get("totalRooms"), 2)

        rooms_resp = self.client.get("/hotel/api/rooms")
        self.assertEqual(rooms_resp.status_code, 200)
        vacant = [
            r
            for r in rooms_resp.get_json().get("rooms") or []
            if str(r.get("status") or "").lower() == "vacant"
        ]
        self.assertGreaterEqual(len(vacant), 2)
        primary = vacant[0]
        member = vacant[1]

        assign = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomIds": [primary["id"], member["id"]]},
        )
        self.assertEqual(assign.status_code, 200, assign.get_data(as_text=True))
        payload = assign.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reservation"]["roomId"], primary["id"])
        self.assertEqual(payload["reservation"]["roomIds"], [primary["id"], member["id"]])
        self.assertTrue(payload["reservation"]["roomAssigned"])
        self.assertEqual(payload["room"]["status"], "reserved")
        self.assertTrue(payload["room"].get("isMergePrimary"))
        merge_numbers = payload["room"].get("stay", {}).get("mergeRoomNumbers") or []
        self.assertIn(str(primary.get("number") or ""), merge_numbers)
        self.assertIn(str(member.get("number") or ""), merge_numbers)

        member_resp = self.client.get(f"/hotel/api/rooms/{member['id']}")
        self.assertEqual(member_resp.status_code, 200, member_resp.get_data(as_text=True))
        member_room = member_resp.get_json()["room"]
        self.assertTrue(member_room.get("isMergeMember"))
        self.assertEqual((member_room.get("stay") or {}).get("billingRoomId"), primary["id"])
        self.assertEqual((member_room.get("stay") or {}).get("mergeRole"), "member")
        self.assertEqual(member_room.get("status"), "reserved")

    def test_assign_rejects_more_rooms_than_total_rooms(self):
        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Cap Guest",
                "mobile": "9000011166",
                "checkInDate": "2026-10-20",
                "checkOutDate": "2026-10-22",
                "amount": 6000,
                "source": "direct",
                "status": "upcoming",
                "totalRooms": 2,
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        booking = create.get_json()["reservation"]

        rooms_resp = self.client.get("/hotel/api/rooms")
        vacant = [
            r
            for r in rooms_resp.get_json().get("rooms") or []
            if str(r.get("status") or "").lower() == "vacant"
        ]
        self.assertGreaterEqual(len(vacant), 3)

        blocked = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomIds": [vacant[0]["id"], vacant[1]["id"], vacant[2]["id"]]},
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_data(as_text=True))
        payload = blocked.get_json()
        self.assertFalse(payload.get("ok"))
        self.assertIn("at most 2", str(payload.get("error") or "").lower())

    def test_assign_second_visit_uses_remaining_total_rooms(self):
        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Remain Guest",
                "mobile": "9000011177",
                "checkInDate": "2026-11-10",
                "checkOutDate": "2026-11-12",
                "amount": 7000,
                "source": "direct",
                "status": "upcoming",
                "totalRooms": 2,
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        booking = create.get_json()["reservation"]

        rooms_resp = self.client.get("/hotel/api/rooms")
        vacant = [
            r
            for r in rooms_resp.get_json().get("rooms") or []
            if str(r.get("status") or "").lower() == "vacant"
        ]
        self.assertGreaterEqual(len(vacant), 3)
        first = vacant[0]
        second = vacant[1]
        third = vacant[2]

        first_assign = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomId": first["id"]},
        )
        self.assertEqual(first_assign.status_code, 200, first_assign.get_data(as_text=True))
        first_payload = first_assign.get_json()
        self.assertEqual(first_payload["reservation"]["roomId"], first["id"])
        self.assertEqual(first_payload["room"]["status"], "reserved")

        second_assign = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomIds": [second["id"]]},
        )
        self.assertEqual(second_assign.status_code, 200, second_assign.get_data(as_text=True))
        payload = second_assign.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reservation"]["roomId"], first["id"])
        self.assertEqual(
            payload["reservation"]["roomIds"], [first["id"], second["id"]]
        )
        self.assertTrue(payload["room"].get("isMergePrimary"))
        self.assertEqual(payload["room"]["id"], first["id"])

        member_resp = self.client.get(f"/hotel/api/rooms/{second['id']}")
        self.assertEqual(member_resp.status_code, 200, member_resp.get_data(as_text=True))
        member_room = member_resp.get_json()["room"]
        self.assertTrue(member_room.get("isMergeMember"))
        self.assertEqual((member_room.get("stay") or {}).get("billingRoomId"), first["id"])

        blocked = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomIds": [third["id"]]},
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_data(as_text=True))
        blocked_payload = blocked.get_json()
        self.assertFalse(blocked_payload.get("ok"))
        self.assertIn("already has 2 of 2", str(blocked_payload.get("error") or "").lower())

    def test_list_includes_occupied_rooms_free_for_future_dates(self):
        occupied = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "In",
                    "lastName": "House",
                    "mobile": "9000099999",
                    "checkInDate": "2026-08-12",
                    "nights": 2,
                    "roomRate": 4000,
                },
            },
        )
        self.assertEqual(occupied.status_code, 200, occupied.get_data(as_text=True))
        self.assertEqual(occupied.get_json()["room"]["status"], "occupied")

        listed = self.client.get("/hotel/api/reservations")
        self.assertEqual(listed.status_code, 200, listed.get_data(as_text=True))
        rooms = listed.get_json().get("vacantRooms") or []
        occupied_row = next((r for r in rooms if r.get("id") == "room-101"), None)
        self.assertIsNotNone(occupied_row)
        self.assertEqual(occupied_row["status"], "occupied")
        self.assertEqual((occupied_row.get("stay") or {}).get("checkInDate"), "2026-08-12")

        vacant_only = [r for r in rooms if r.get("status") == "vacant"]
        self.assertTrue(vacant_only)
        self.assertGreater(len(rooms), len(vacant_only))

    def test_assign_future_booking_onto_occupied_room(self):
        occupied = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "In",
                    "lastName": "House",
                    "mobile": "9000099998",
                    "checkInDate": "2026-08-12",
                    "nights": 2,
                    "roomRate": 4000,
                },
            },
        )
        self.assertEqual(occupied.status_code, 200, occupied.get_data(as_text=True))

        create = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Later Guest",
                "mobile": "9000011133",
                "email": "later@example.com",
                "checkInDate": "2026-09-10",
                "checkOutDate": "2026-09-12",
                "amount": 2500,
                "source": "direct",
                "status": "upcoming",
            },
        )
        self.assertEqual(create.status_code, 200, create.get_data(as_text=True))
        booking = create.get_json()["reservation"]

        assign = self.client.post(
            f"/hotel/api/reservations/{booking['id']}/assign",
            json={"roomId": "room-102"},
        )
        self.assertEqual(assign.status_code, 200, assign.get_data(as_text=True))
        payload = assign.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["room"]["status"], "occupied")
        self.assertEqual(payload["room"]["stay"]["guestName"], "In House")
        upcoming = payload["room"].get("upcomingStay") or {}
        self.assertEqual(upcoming.get("guestName"), "Later Guest")
        self.assertEqual(upcoming.get("checkInDate"), "2026-09-10")
        self.assertEqual(upcoming.get("checkOutDate"), "2026-09-12")
        self.assertTrue(payload["reservation"]["roomAssigned"])
        self.assertEqual(payload["reservation"]["roomId"], "room-102")

        overlap = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Overlap Guest",
                "mobile": "9000011144",
                "checkInDate": "2026-08-12",
                "checkOutDate": "2026-08-16",
                "amount": 1800,
                "source": "direct",
                "status": "upcoming",
            },
        )
        self.assertEqual(overlap.status_code, 200, overlap.get_data(as_text=True))
        blocked = self.client.post(
            f"/hotel/api/reservations/{overlap.get_json()['reservation']['id']}/assign",
            json={"roomId": "room-102"},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(blocked.get_json()["ok"])
        self.assertIn("not available", blocked.get_json()["error"].lower())

    def test_hotel_room_available_for_stay_skips_overlap(self):
        occupied = {
            "status": "occupied",
            "stay": {"checkInDate": "2026-08-12", "checkOutDate": "2026-08-14"},
        }
        self.assertTrue(
            db_mod.hotel_room_available_for_stay(
                occupied, "2026-08-15", "2026-08-16", today="2026-08-12"
            )
        )
        self.assertFalse(
            db_mod.hotel_room_available_for_stay(
                occupied, "2026-08-13", "2026-08-15", today="2026-08-12"
            )
        )
        self.assertFalse(
            db_mod.hotel_room_available_for_stay(
                {"status": "out_of_order"}, "2026-08-20", "2026-08-21"
            )
        )
        self.assertFalse(
            db_mod.hotel_room_available_for_stay(
                {"status": "dirty"},
                "2026-08-12",
                "2026-08-13",
                today="2026-08-12",
            )
        )
        self.assertTrue(
            db_mod.hotel_room_available_for_stay(
                {"status": "dirty"},
                "2026-08-20",
                "2026-08-21",
                today="2026-08-12",
            )
        )

    def test_list_api_total_kpi_follows_selected_date(self):
        rows = [
            asia_tech_client._normalize_reservation(
                {
                    "id": "stay-today",
                    "guestName": "Today Guest",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-14",
                    "status": "checked_in",
                    "source": "direct",
                    "amount": 1000,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "stay-later",
                    "guestName": "Later Guest",
                    "checkInDate": "2026-08-20",
                    "checkOutDate": "2026-08-22",
                    "status": "upcoming",
                    "source": "direct",
                    "amount": 2000,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "left-today",
                    "guestName": "Departed Guest",
                    "checkInDate": "2026-08-10",
                    "checkOutDate": "2026-08-12",
                    "status": "checked_out",
                    "source": "direct",
                    "amount": 800,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "left-earlier",
                    "guestName": "Earlier Guest",
                    "checkInDate": "2026-08-01",
                    "checkOutDate": "2026-08-05",
                    "status": "checked_out",
                    "source": "direct",
                    "amount": 400,
                }
            ),
            asia_tech_client._normalize_reservation(
                {
                    "id": "stale-inhouse",
                    "guestName": "Stale Inhouse",
                    "checkInDate": "2026-08-18",
                    "checkOutDate": "2026-08-19",
                    "status": "checked_in",
                    "source": "direct",
                    "amount": 500,
                }
            ),
        ]
        with mock.patch.object(
            asia_tech_client, "list_provider_reservations", return_value=rows
        ):
            all_resp = self.client.get("/hotel/api/reservations?page=1&page_size=all")
            self.assertEqual(all_resp.status_code, 200)
            all_payload = all_resp.get_json()
            self.assertEqual(all_payload["kpis"]["total"], 5)
            self.assertEqual(all_payload["kpis"]["checked_in"], 2)
            self.assertEqual(all_payload["kpis"]["upcoming"], 1)
            self.assertEqual(all_payload["kpis"]["checked_out"], 2)
            self.assertEqual(all_payload["kpis"]["revenue"], 4700)

            dated = self.client.get(
                "/hotel/api/reservations?page=1&page_size=all"
                "&date_from=2026-08-12&date_to=2026-08-12"
            )
            self.assertEqual(dated.status_code, 200)
            dated_payload = dated.get_json()
            self.assertEqual(dated_payload["kpis"]["total"], 2)
            self.assertEqual(len(dated_payload["reservations"]), 2)
            self.assertEqual(
                {row["id"] for row in dated_payload["reservations"]},
                {"stay-today", "left-today"},
            )
            self.assertEqual(dated_payload["kpis"]["checked_in"], 1)
            self.assertEqual(dated_payload["kpis"]["upcoming"], 0)
            self.assertEqual(dated_payload["kpis"]["checked_out"], 1)
            self.assertEqual(dated_payload["kpis"]["revenue"], 1800)

            checked_in = self.client.get(
                "/hotel/api/reservations?page=1&page_size=all"
                "&date_from=2026-08-12&date_to=2026-08-12"
                "&status=checked_in"
            )
            self.assertEqual(checked_in.status_code, 200)
            checked_in_payload = checked_in.get_json()
            self.assertEqual(
                {row["id"] for row in checked_in_payload["reservations"]},
                {"stay-today"},
            )
            self.assertEqual(checked_in_payload["kpis"]["total"], 2)
            self.assertEqual(checked_in_payload["kpis"]["checked_in"], 1)
            self.assertEqual(checked_in_payload["kpis"]["checked_out"], 1)

            checkout_only = self.client.get(
                "/hotel/api/reservations?page=1&page_size=all"
                "&date_from=2026-08-12&date_to=2026-08-12"
                "&checkout_only=1"
            )
            self.assertEqual(checkout_only.status_code, 200)
            checkout_payload = checkout_only.get_json()
            self.assertEqual(
                {row["id"] for row in checkout_payload["reservations"]},
                {"left-today"},
            )
            self.assertEqual(checkout_payload["kpis"]["total"], 2)
            self.assertEqual(checkout_payload["kpis"]["checked_out"], 1)

            arrivals = self.client.get(
                "/hotel/api/reservations?page=1&page_size=all"
                "&date_from=2026-08-20&date_to=2026-08-20"
            )
            self.assertEqual(arrivals.status_code, 200)
            self.assertEqual(arrivals.get_json()["kpis"]["upcoming"], 1)

    def test_create_reservation(self):
        resp = self.client.post(
            "/hotel/api/reservations",
            json={
                "guestName": "Test Guest",
                "mobile": "9998887776",
                "email": "test@example.com",
                "checkInDate": "2026-09-01",
                "checkOutDate": "2026-09-03",
                "amount": 9000,
                "source": "direct",
                "status": "upcoming",
                "mealPlan": "CP",
                "specialNotes": "Late arrival after 10 PM",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reservation"]["guestName"], "Test Guest")
        self.assertEqual(payload["reservation"]["mealPlan"], "CP · Breakfast")
        self.assertEqual(payload["reservation"]["specialNotes"], "Late arrival after 10 PM")
        booking_id = payload["reservation"]["id"]

        found = self.client.get(f"/hotel/api/reservations/{booking_id}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.get_json()["reservation"]["mobile"], "9998887776")

        updated = self.client.put(
            f"/hotel/api/reservations/{booking_id}",
            json={
                "guestName": "Test Guest",
                "mobile": "9998887776",
                "email": "test@example.com",
                "checkInDate": "2026-09-01",
                "checkOutDate": "2026-09-03",
                "amount": 9000,
                "source": "direct",
                "status": "upcoming",
                "mealPlan": "MAP",
                "specialNotes": "High floor if possible",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_data(as_text=True))
        saved = updated.get_json()["reservation"]
        self.assertEqual(saved["mealPlan"], "MAP · Breakfast & dinner")
        self.assertEqual(saved["specialNotes"], "High floor if possible")

    def test_hotel_settings_page_has_asia_tech_section(self):
        page = self.client.get("/hotel/settings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('data-section="asia_tech"', html)
        self.assertIn("asia_tech_api_key", html)
        self.assertIn("asia_tech_username", html)
        self.assertIn("asia_tech_hotel_id", html)
        self.assertIn("asia_tech_password", html)


if __name__ == "__main__":
    unittest.main()
