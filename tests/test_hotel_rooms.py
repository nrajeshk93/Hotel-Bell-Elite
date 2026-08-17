"""Hotel Rooms floor board seed and API."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import db as db_mod


class HotelRoomsTests(unittest.TestCase):
    @staticmethod
    def _stay_window(nights=2, end_offset_days=1):
        """Return check-in / check-out ISO dates that avoid overstay billing."""
        nights = max(1, int(nights or 1))
        check_out = datetime.now().date() + timedelta(days=max(1, int(end_offset_days or 1)))
        check_in = check_out - timedelta(days=nights)
        return check_in.isoformat(), check_out.isoformat()

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
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        self._get_user_patch.stop()
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_default_seed_inventory(self):
        layout = db_mod.default_hotel_rooms_layout()
        self.assertEqual(len(layout["floors"]), 3)
        self.assertEqual(len(layout["rooms"]), 20)
        by_type = {}
        for room in layout["rooms"]:
            by_type[room["roomType"]] = by_type.get(room["roomType"], 0) + 1
            self.assertEqual(room["status"], "vacant")
            self.assertEqual(room["floorId"], f"floor-{room['number'][0]}")
        self.assertEqual(
            by_type,
            {
                "premium_without_balcony": 6,
                "premium_deluxe_balcony": 12,
                "premium_suite_tub": 2,
            },
        )

    def test_get_layout_seeds_when_empty(self):
        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            counts = db_mod.hotel_rooms_status_counts(layout)
            self.assertEqual(counts["total"], 20)
            self.assertEqual(counts["vacant"], 20)
            updated = db_mod.update_hotel_room_status(conn, "room-207", "dirty")
            room = next(r for r in updated["rooms"] if r["id"] == "room-207")
            self.assertEqual(room["status"], "dirty")
            conn.commit()
        finally:
            conn.close()

    def test_rooms_api_get_and_status_put(self):
        get_resp = self.client.get("/hotel/api/rooms")
        self.assertEqual(get_resp.status_code, 200)
        payload = get_resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["rooms"]), 20)
        self.assertEqual(payload["counts"]["total"], 20)

        put_resp = self.client.put(
            "/hotel/api/rooms",
            json={"roomId": "room-101", "status": "occupied"},
        )
        self.assertEqual(put_resp.status_code, 200)
        put_payload = put_resp.get_json()
        self.assertTrue(put_payload["ok"])
        room = next(r for r in put_payload["rooms"] if r["id"] == "room-101")
        self.assertEqual(room["status"], "occupied")
        self.assertEqual(put_payload["counts"]["occupied"], 1)

    def test_rooms_api_reserve_binds_stay_to_as_of_date(self):
        put_resp = self.client.put(
            "/hotel/api/rooms",
            json={
                "roomId": "room-104",
                "status": "reserved",
                "checkInDate": "2026-07-31",
                "checkOutDate": "2026-08-01",
            },
        )
        self.assertEqual(put_resp.status_code, 200)
        payload = put_resp.get_json()
        self.assertTrue(payload["ok"])
        room = next(r for r in payload["rooms"] if r["id"] == "room-104")
        self.assertEqual(room["status"], "reserved")
        self.assertEqual(room["stay"]["checkInDate"], "2026-07-31")
        self.assertEqual(room["stay"]["checkOutDate"], "2026-08-01")
        # Reservation without an explicit rate seeds the room-type tariff.
        self.assertGreater(float(room["stay"]["roomRate"]), 0)
        self.assertEqual(payload["counts"]["reserved"], 1)

    def test_rooms_page_renders(self):
        resp = self.client.get("/hotel/rooms")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("hotel-rooms-page", html)
        self.assertIn("Rooms", html)
        self.assertIn("hotel-rooms-status-listbox", html)
        self.assertIn("hotel-rooms-quick-reservations", html)
        self.assertIn("Reservations", html)
        self.assertIn("hr-board-reserve-modal", html)
        self.assertIn("hr-board-reserve-form", html)
        self.assertIn("hr-board-reserve-rooms-select", html)
        self.assertIn("Save Reservation", html)
        self.assertIn('data-customers-api="/hotel/api/customers"', html)
        self.assertIn("hotel-rooms-date-filter", html)
        self.assertIn('data-kpi="expected_checkout"', html)
        self.assertIn("Expected Check Out", html)
        self.assertNotIn('data-kpi="reserved"', html)

    def test_board_multi_room_reserve_via_per_room_api(self):
        """Board Reserve loops single-room reserve; same dates work on free rooms."""
        stay = {
            "guestName": "Board Guest",
            "mobile": "9876543210",
            "email": "board@example.com",
            "additionalRequests": "Late arrival after 10 PM",
        }
        dates = {
            "action": "reserve",
            "checkInDate": "2026-09-10",
            "checkOutDate": "2026-09-12",
            "stay": stay,
        }
        room_a = self.client.put("/hotel/api/rooms/room-201", json=dates)
        self.assertEqual(room_a.status_code, 200)
        self.assertTrue(room_a.get_json()["ok"])
        self.assertEqual(room_a.get_json()["room"]["status"], "reserved")
        self.assertEqual(room_a.get_json()["room"]["stay"]["checkInDate"], "2026-09-10")
        self.assertGreater(float(room_a.get_json()["room"]["stay"]["roomRate"]), 0)
        self.assertEqual(
            room_a.get_json()["room"]["stay"]["additionalRequests"],
            "Late arrival after 10 PM",
        )

        room_b = self.client.put("/hotel/api/rooms/room-202", json=dates)
        self.assertEqual(room_b.status_code, 200)
        self.assertTrue(room_b.get_json()["ok"])
        self.assertEqual(room_b.get_json()["room"]["status"], "reserved")
        self.assertEqual(
            room_b.get_json()["room"]["stay"]["guestName"], "Board Guest"
        )

        occupied = self.client.put(
            "/hotel/api/rooms/room-203",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "In",
                    "lastName": "House",
                    "mobile": "9000099999",
                    "checkInDate": "2026-07-28",
                    "nights": 2,
                    "roomRate": 4000,
                },
            },
        )
        self.assertEqual(occupied.status_code, 200)
        self.assertEqual(occupied.get_json()["room"]["status"], "occupied")

        # Future non-overlapping dates queue as upcomingStay while still occupied.
        future = self.client.put(
            "/hotel/api/rooms/room-203",
            json={
                "action": "reserve",
                "checkInDate": "2026-09-10",
                "checkOutDate": "2026-09-12",
                "stay": stay,
            },
        )
        self.assertEqual(future.status_code, 200)
        future_room = future.get_json()["room"]
        self.assertTrue(future.get_json()["ok"])
        self.assertEqual(future_room["status"], "occupied")
        self.assertEqual(future_room["stay"]["guestName"], "In House")
        self.assertEqual(future_room["upcomingStay"]["guestName"], "Board Guest")
        self.assertEqual(future_room["upcomingStay"]["checkInDate"], "2026-09-10")

        overlap_occupied = self.client.put(
            "/hotel/api/rooms/room-203",
            json={
                "action": "reserve",
                "checkInDate": "2026-07-29",
                "checkOutDate": "2026-07-31",
                "stay": {
                    "guestName": "Overlap Occ",
                    "mobile": "9111222333",
                },
            },
        )
        self.assertEqual(overlap_occupied.status_code, 400)
        self.assertFalse(overlap_occupied.get_json()["ok"])

        overlap_replace = self.client.put(
            "/hotel/api/rooms/room-201",
            json={
                "action": "reserve",
                "replace": True,
                "checkInDate": "2026-09-11",
                "checkOutDate": "2026-09-13",
                "stay": {
                    "guestName": "Overlap Guest",
                    "mobile": "9123456780",
                },
            },
        )
        self.assertEqual(overlap_replace.status_code, 400)
        self.assertFalse(overlap_replace.get_json()["ok"])
        self.assertIn("already reserved", overlap_replace.get_json()["error"].lower())

    def test_occupied_future_reserve_and_checkout_promotes_upcoming(self):
        """Occupied rooms accept non-overlapping future reserve; checkout promotes it."""
        checkin = self.client.put(
            "/hotel/api/rooms/room-204",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Today",
                    "lastName": "Guest",
                    "mobile": "9000088888",
                    "checkInDate": "2026-07-28",
                    "nights": 2,
                    "roomRate": 3500,
                },
            },
        )
        self.assertEqual(checkin.status_code, 200)
        self.assertEqual(checkin.get_json()["room"]["status"], "occupied")
        self.assertEqual(
            checkin.get_json()["room"]["stay"]["checkOutDate"], "2026-07-30"
        )

        future = self.client.put(
            "/hotel/api/rooms/room-204",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-20",
                "checkOutDate": "2026-08-22",
                "stay": {
                    "guestName": "Next Guest",
                    "mobile": "9888777666",
                    "email": "next@example.com",
                },
            },
        )
        self.assertEqual(future.status_code, 200)
        room = future.get_json()["room"]
        self.assertEqual(room["status"], "occupied")
        self.assertEqual(room["stay"]["guestName"], "Today Guest")
        self.assertEqual(room["upcomingStay"]["guestName"], "Next Guest")
        self.assertEqual(room["upcomingStay"]["checkInDate"], "2026-08-20")
        self.assertEqual(room["upcomingStay"]["checkOutDate"], "2026-08-22")

        # Overlapping the in-house window still fails.
        overlap = self.client.put(
            "/hotel/api/rooms/room-204",
            json={
                "action": "reserve",
                "checkInDate": "2026-07-29",
                "checkOutDate": "2026-07-31",
                "stay": {"guestName": "Clash", "mobile": "9777666555"},
            },
        )
        self.assertEqual(overlap.status_code, 400)
        self.assertIn("occupied", overlap.get_json()["error"].lower())

        checkout = self.client.put(
            "/hotel/api/rooms/room-204",
            json={"action": "checkout"},
        )
        self.assertEqual(checkout.status_code, 200)
        after = checkout.get_json()["room"]
        self.assertEqual(after["status"], "reserved")
        self.assertEqual(after["stay"]["guestName"], "Next Guest")
        self.assertEqual(after["stay"]["checkInDate"], "2026-08-20")
        self.assertNotIn("upcomingStay", after)

    def test_room_detail_page_renders(self):
        resp = self.client.get("/hotel/rooms/room-101")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("hotel-room-detail-page", html)
        self.assertIn("Room 101", html)
        self.assertIn("Start Check-In", html)
        self.assertIn("hrd-add-guest-id", html)
        self.assertIn("Add Guest ID", html)
        self.assertIn('data-action="add-guest-id"', html)
        self.assertIn("hrd-ci-id-proof", html)
        self.assertIn("hrd-id-doc-name", html)
        self.assertIn("hrd-id-preview-modal", html)
        self.assertNotIn("New Check-in", html)
        self.assertIn("hrd-reserve", html)
        self.assertIn("hrd-reserve-new", html)
        self.assertIn("hrd-reserve-modal", html)
        self.assertIn("hrd-form-listbox--countries", html)
        box_at = html.find('id="hrd-ci-nationality-listbox"')
        self.assertGreater(box_at, 0)
        nat_at = html.find('id="hrd-ci-nationality-list"')
        self.assertGreater(nat_at, box_at)
        trigger_chunk = html[box_at:nat_at]
        self.assertIn('role="combobox"', trigger_chunk)
        self.assertIn('id="hrd-ci-nationality-trigger"', trigger_chunk)
        self.assertNotIn("ep-listbox-search", trigger_chunk)
        nat_chunk = html[nat_at:nat_at + 120000]
        self.assertNotIn("ep-listbox-search", nat_chunk.split('<div class="ep-listbox-options"', 1)[0])
        self.assertIn("Afghanistan", nat_chunk)
        self.assertIn("Indonesia", nat_chunk)
        self.assertGreater(nat_chunk.count("se-filter-listbox-option"), 180)

    def test_reserved_future_room_detail_renders(self):
        reserved = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-14",
                "checkOutDate": "2026-08-15",
                "stay": {
                    "guestName": "Pratik",
                    "mobile": "8587836993",
                    "email": "pratikmmt@gmail.com",
                },
            },
        )
        self.assertEqual(reserved.status_code, 200, reserved.get_data(as_text=True))
        self.assertEqual(reserved.get_json()["room"]["status"], "reserved")

        detail = self.client.get("/hotel/rooms/room-102")
        self.assertEqual(detail.status_code, 200, detail.get_data(as_text=True))
        html = detail.get_data(as_text=True)
        self.assertIn("hotel-room-detail-page", html)
        self.assertIn("Room 102", html)
        self.assertIn("hrd-start-checkin-reserved", html)
        self.assertIn("Edit Reservation", html)

        with_date = self.client.get("/hotel/rooms/room-102?date=2026-08-14")
        self.assertEqual(with_date.status_code, 200)
        self.assertIn("hotel-room-detail-page", with_date.get_data(as_text=True))

    def test_room_detail_reserve_and_occupied_reject(self):
        reserved = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-06",
                "checkOutDate": "2026-08-08",
                "stay": {
                    "guestName": "Priya Shah",
                    "mobile": "9887766554",
                    "email": "priya@example.com",
                    "agencyName": "Travel Co",
                    "agencyGst": "27AAAAA0000A1Z5",
                    "agencyAddress": "MG Road",
                    "agencyBilling": True,
                },
            },
        )
        self.assertEqual(reserved.status_code, 200)
        payload = reserved.get_json()
        self.assertTrue(payload["ok"])
        stay = payload["room"]["stay"]
        self.assertEqual(payload["room"]["status"], "reserved")
        self.assertEqual(stay["checkInDate"], "2026-08-06")
        self.assertEqual(stay["checkOutDate"], "2026-08-08")
        self.assertEqual(stay["nights"], 2)
        self.assertEqual(stay["guestName"], "Priya Shah")
        self.assertEqual(stay["firstName"], "Priya")
        self.assertEqual(stay["lastName"], "Shah")
        self.assertEqual(stay["mobile"], "9887766554")
        self.assertEqual(stay["email"], "priya@example.com")
        self.assertEqual(stay["agencyName"], "Travel Co")
        self.assertEqual(stay["agencyGst"], "27AAAAA0000A1Z5")
        self.assertTrue(stay["agencyBilling"])

        missing = self.client.put(
            "/hotel/api/rooms/room-104",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-10",
                "checkOutDate": "2026-08-12",
                "stay": {"guestName": "No Phone"},
            },
        )
        self.assertEqual(missing.status_code, 400)
        self.assertFalse(missing.get_json()["ok"])
        self.assertIn("Mobile", missing.get_json()["error"])

        missing_name = self.client.put(
            "/hotel/api/rooms/room-104",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-10",
                "checkOutDate": "2026-08-12",
                "stay": {"mobile": "9000000001"},
            },
        )
        self.assertEqual(missing_name.status_code, 400)
        self.assertFalse(missing_name.get_json()["ok"])
        self.assertIn("Guest name", missing_name.get_json()["error"])

        checkin = self.client.put(
            "/hotel/api/rooms/room-106",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Sam",
                    "lastName": "Lee",
                    "mobile": "9000012345",
                    "checkInDate": "2026-07-30",
                    "nights": 1,
                    "roomRate": 4500,
                },
            },
        )
        self.assertEqual(checkin.status_code, 200)
        self.assertEqual(checkin.get_json()["room"]["status"], "occupied")

        # Overlapping the in-house stay is still rejected.
        blocked = self.client.put(
            "/hotel/api/rooms/room-106",
            json={
                "action": "reserve",
                "checkInDate": "2026-07-30",
                "checkOutDate": "2026-08-01",
                "stay": {"guestName": "Blocked Guest", "mobile": "9111111111"},
            },
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(blocked.get_json()["ok"])
        self.assertIn("occupied", blocked.get_json()["error"].lower())

        # Non-overlapping future dates queue as upcomingStay.
        future = self.client.put(
            "/hotel/api/rooms/room-106",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-10",
                "checkOutDate": "2026-08-12",
                "stay": {"guestName": "Future Guest", "mobile": "9111111111"},
            },
        )
        self.assertEqual(future.status_code, 200)
        self.assertEqual(future.get_json()["room"]["status"], "occupied")
        self.assertEqual(
            future.get_json()["room"]["upcomingStay"]["guestName"], "Future Guest"
        )

    def test_room_detail_reserve_replace_clears_prior_guest(self):
        first = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "reserve",
                "checkInDate": "2026-08-06",
                "checkOutDate": "2026-08-08",
                "stay": {
                    "guestName": "Priya Shah",
                    "mobile": "9887766554",
                    "email": "priya@example.com",
                    "agencyName": "Travel Co",
                    "agencyGst": "27AAAAA0000A1Z5",
                    "agencyAddress": "MG Road",
                    "agencyBilling": True,
                },
            },
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["room"]["stay"]["guestName"], "Priya Shah")

        overlap = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "reserve",
                "replace": True,
                "checkInDate": "2026-08-07",
                "checkOutDate": "2026-08-09",
                "stay": {
                    "guestName": "Overlap Guest",
                    "mobile": "9000099999",
                },
            },
        )
        self.assertEqual(overlap.status_code, 400)
        self.assertFalse(overlap.get_json()["ok"])
        self.assertIn("already reserved", overlap.get_json()["error"].lower())

        replaced = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "reserve",
                "replace": True,
                "checkInDate": "2026-08-10",
                "checkOutDate": "2026-08-12",
                "stay": {
                    "guestName": "Asha Rao",
                    "mobile": "9000012345",
                    "email": "asha@example.com",
                },
            },
        )
        self.assertEqual(replaced.status_code, 200)
        payload = replaced.get_json()
        self.assertTrue(payload["ok"])
        stay = payload["room"]["stay"]
        self.assertEqual(payload["room"]["status"], "reserved")
        self.assertEqual(stay["guestName"], "Asha Rao")
        self.assertEqual(stay["mobile"], "9000012345")
        self.assertEqual(stay["email"], "asha@example.com")
        self.assertEqual(stay["checkInDate"], "2026-08-10")
        self.assertEqual(stay["checkOutDate"], "2026-08-12")
        self.assertEqual(stay.get("agencyName") or "", "")
        self.assertEqual(stay.get("agencyGst") or "", "")
        self.assertFalse(stay.get("agencyBilling"))

    def test_room_detail_api_get_and_mark_clean(self):
        put_dirty = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"status": "dirty"},
        )
        self.assertEqual(put_dirty.status_code, 200)
        self.assertEqual(put_dirty.get_json()["room"]["status"], "dirty")

        put_clean = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"status": "vacant"},
        )
        self.assertEqual(put_clean.status_code, 200)
        cleaned = put_clean.get_json()["room"]
        self.assertEqual(cleaned["status"], "vacant")
        self.assertEqual(cleaned.get("statusLabel"), "Vacant")

    def test_occupied_status_cannot_become_vacant_while_checked_in(self):
        """Checked-in rooms stay Occupied until checkout — no Vacant shortcut."""
        check_in, check_out = self._stay_window(nights=3)
        self.client.put(
            "/hotel/api/rooms/room-103",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "In",
                    "lastName": "House",
                    "mobile": "9000000103",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 3,
                    "roomRate": 3000,
                },
            },
        )
        blocked_vacant = self.client.put(
            "/hotel/api/rooms/room-103",
            json={"status": "vacant"},
        )
        self.assertEqual(blocked_vacant.status_code, 400)
        self.assertIn("checked in", blocked_vacant.get_json().get("error", "").lower())

        still = self.client.get("/hotel/api/rooms/room-103").get_json()["room"]
        self.assertEqual(still["status"], "occupied")
        self.assertEqual(still.get("statusLabel"), "Occupied")
        self.assertTrue(still.get("stay", {}).get("guestName") or still.get("stay", {}).get("firstName"))

        # Dirty while occupied is allowed — checks guest out and marks Dirty.
        forced_dirty = self.client.put(
            "/hotel/api/rooms/room-103",
            json={"status": "dirty"},
        )
        self.assertEqual(forced_dirty.status_code, 200, forced_dirty.get_data(as_text=True))
        dirty_room = forced_dirty.get_json()["room"]
        self.assertEqual(dirty_room["status"], "dirty")
        self.assertFalse(dirty_room.get("stay"))

        cleaned = self.client.put(
            "/hotel/api/rooms/room-103",
            json={"status": "vacant"},
        )
        self.assertEqual(cleaned.status_code, 200)
        self.assertEqual(cleaned.get_json()["room"]["status"], "vacant")

    def test_checkout_sets_room_dirty(self):
        check_in, check_out = self._stay_window(nights=1)
        self.client.put(
            "/hotel/api/rooms/room-104",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Out",
                    "lastName": "Guest",
                    "mobile": "9000000104",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 2000,
                },
            },
        )
        closed = self.client.put(
            "/hotel/api/rooms/room-104",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200)
        room = closed.get_json()["room"]
        self.assertEqual(room["status"], "dirty")
        self.assertEqual(room.get("statusLabel"), "Dirty")
        self.assertFalse(room.get("stay"))

    def test_expected_checkout_kpi_counts_departures_for_day(self):
        today = datetime.now().date()
        check_out_today = today.isoformat()
        check_in = (today - timedelta(days=2)).isoformat()
        future_out = (today + timedelta(days=2)).isoformat()

        self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Due",
                    "lastName": "Today",
                    "mobile": "9000000105",
                    "checkInDate": check_in,
                    "checkOutDate": check_out_today,
                    "nights": 2,
                    "roomRate": 3000,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-106",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Staying",
                    "lastName": "On",
                    "mobile": "9000000106",
                    "checkInDate": check_in,
                    "checkOutDate": future_out,
                    "nights": 4,
                    "roomRate": 3000,
                },
            },
        )

        layout = self.client.get("/hotel/api/rooms").get_json()
        self.assertEqual(layout["counts"]["expected_checkout"], 1)
        self.assertGreaterEqual(layout["counts"]["occupied"], 2)

        # Board date filter for a future day should count that day's departures.
        conn = db_mod.get_db()
        try:
            counts = db_mod.hotel_rooms_status_counts(
                {"rooms": layout["rooms"]}, as_of=future_out
            )
            self.assertEqual(counts["expected_checkout"], 1)
        finally:
            conn.close()

    def test_expected_checkout_counts_each_merged_occupied_room(self):
        """Expected checkout is physical rooms due that day, including merge members."""
        today = datetime.now().date()
        check_out_today = today.isoformat()
        check_in = (today - timedelta(days=1)).isoformat()
        stay = {
            "firstName": "Merge",
            "lastName": "Out",
            "mobile": "9000000201",
            "checkInDate": check_in,
            "checkOutDate": check_out_today,
            "nights": 1,
            "roomRate": 3000,
        }
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-201",
                json={"action": "checkin", "stay": stay},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-202",
                json={"action": "checkin", "stay": dict(stay, mobile="9000000202")},
            ).status_code,
            200,
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-202",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-202",
                "toRoomId": "room-201",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        layout = self.client.get("/hotel/api/rooms").get_json()
        self.assertEqual(layout["counts"]["expected_checkout"], 2)
        rooms = {r["id"]: r for r in layout.get("rooms") or []}
        self.assertEqual(rooms["room-201"]["status"], "occupied")
        self.assertEqual(rooms["room-202"]["status"], "occupied")
        self.assertTrue(rooms["room-201"].get("mergeGroupId"))
        self.assertEqual(
            rooms["room-201"].get("mergeGroupId"),
            rooms["room-202"].get("mergeGroupId"),
        )

    def test_heals_orphan_vacant_with_inhouse_stay(self):
        """Vacant inventory with an active stay is restored to Occupied on load."""
        import json

        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            rooms = layout.get("rooms") or []
            room = next(r for r in rooms if r.get("id") == "room-104")
            room["status"] = "vacant"
            room["stay"] = {
                "firstName": "Still",
                "lastName": "Here",
                "guestName": "Still Here",
                "mobile": "9000000104",
                "checkInDate": "2026-07-28",
                "checkOutDate": "2026-08-05",
                "nights": 8,
                "roomRate": 4000,
                "checkedInAt": "2026-07-28 14:00:00",
            }
            room.pop("mergeGroupId", None)
            room.pop("mergePrimary", None)
            blob = json.dumps(
                {"floors": layout.get("floors") or [], "rooms": rooms},
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO hotel_rooms_layout (id, payload, updated_at)
                VALUES (1, ?, datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (blob,),
            )
            conn.commit()
        finally:
            conn.close()

        healed = self.client.get("/hotel/api/rooms/room-104").get_json()["room"]
        self.assertEqual(healed["status"], "occupied")
        self.assertEqual(healed.get("statusLabel"), "Occupied")

    def test_mark_clean_blocked_when_merge_member_occupied(self):
        """Vacant billing primary stays vacant; only the occupied room is blocked."""
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Raj",
                    "lastName": "Kumar",
                    "mobile": "9000000101",
                    "checkInDate": "2026-07-29",
                    "nights": 2,
                    "roomRate": 2500,
                },
            },
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-101",
                "toRoomId": "room-106",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        primary = merged.get_json()["primaryRoom"]
        self.assertEqual(primary["id"], "room-106")
        self.assertEqual(primary["status"], "vacant")
        member = merged.get_json()["memberRoom"]
        self.assertEqual(member["id"], "room-101")
        self.assertEqual(member["status"], "occupied")

        allowed = self.client.put(
            "/hotel/api/rooms/room-106",
            json={"status": "vacant"},
        )
        self.assertEqual(allowed.status_code, 200, allowed.get_data(as_text=True))
        self.assertEqual(allowed.get_json()["room"]["status"], "vacant")

        blocked = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"status": "vacant"},
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_data(as_text=True))
        err = blocked.get_json().get("error", "").lower()
        self.assertIn("checked in", err)

        still = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertEqual(still["status"], "occupied")

    def test_heals_vacant_merge_primary_when_member_occupied(self):
        """Vacant billing primary stays vacant when a member is occupied."""
        import json

        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            rooms = layout.get("rooms") or []
            primary = next(r for r in rooms if r.get("id") == "room-106")
            member = next(r for r in rooms if r.get("id") == "room-101")
            gid = "hmg_test_heal_occ"
            primary["mergeGroupId"] = gid
            primary["mergePrimary"] = True
            primary["status"] = "vacant"
            primary["stay"] = {
                "mergeRole": "primary",
                "firstName": "Host",
                "guestName": "Host",
            }
            member["mergeGroupId"] = gid
            member["mergePrimary"] = False
            member["status"] = "occupied"
            member["stay"] = {
                "firstName": "Guest",
                "lastName": "One",
                "guestName": "Guest One",
                "mobile": "9000000102",
                "checkInDate": "2026-07-29",
                "nights": 1,
                "roomRate": 2000,
                "checkedInAt": "2026-07-29 14:00:00",
                "mergeRole": "member",
                "billingRoomId": "room-106",
            }
            # Bypass save_hotel_rooms_layout heal so we can seed the stale row.
            blob = json.dumps(
                {"floors": layout.get("floors") or [], "rooms": rooms},
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO hotel_rooms_layout (id, payload, updated_at)
                VALUES (1, ?, datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (blob,),
            )
            conn.commit()
        finally:
            conn.close()

        healed = self.client.get("/hotel/api/rooms/room-106").get_json()["room"]
        self.assertEqual(healed["status"], "vacant")
        member_healed = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertEqual(member_healed["status"], "occupied")

    def test_room_detail_404(self):
        resp = self.client.get("/hotel/rooms/room-999")
        self.assertEqual(resp.status_code, 404)

    def test_room_checkin_and_checkout(self):
        check_in, check_out = self._stay_window(nights=2)
        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Raj",
                    "lastName": "Kumar",
                    "mobile": "9876543210",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 4500,
                    "idType": "Aadhaar",
                    "idNumber": "1234-5678",
                },
            },
        )
        self.assertEqual(checkin.status_code, 200)
        payload = checkin.get_json()
        self.assertTrue(payload["ok"])
        room = payload["room"]
        self.assertEqual(room["status"], "occupied")
        self.assertEqual(room["stay"]["firstName"], "Raj")
        self.assertEqual(room["stay"]["guestName"], "Raj Kumar")
        self.assertTrue(room["stay"]["bookingNumber"].startswith("BK"))
        self.assertEqual(room["stay"]["totalRate"], 9000.0)

        detail = self.client.get("/hotel/rooms/room-101")
        self.assertEqual(detail.status_code, 200)
        html = detail.get_data(as_text=True)
        self.assertIn("New Check-In", html)
        self.assertIn("hrd-checkin-modal", html)
        self.assertIn('data-se-listbox-change="hrdCiMobileCountryChanged"', html)
        self.assertIn("Indonesia", html)

        checkout = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(checkout.status_code, 200)
        out = checkout.get_json()["room"]
        self.assertEqual(out["status"], "dirty")
        self.assertNotIn("stay", out)

    def test_checkin_rejected_when_room_is_dirty(self):
        check_in, check_out = self._stay_window(nights=1)
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-101", json={"status": "dirty"}).status_code,
            200,
        )
        blocked = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Raj",
                    "lastName": "Kumar",
                    "mobile": "9876543210",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                },
            },
        )
        self.assertEqual(blocked.status_code, 400, blocked.get_data(as_text=True))
        payload = blocked.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("dirty", (payload.get("error") or "").lower())
        room = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertEqual(room["status"], "dirty")
        self.assertFalse(room.get("stay"))

        cleaned = self.client.put("/hotel/api/rooms/room-101", json={"status": "vacant"})
        self.assertEqual(cleaned.status_code, 200)
        allowed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Raj",
                    "lastName": "Kumar",
                    "mobile": "9876543210",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                },
            },
        )
        self.assertEqual(allowed.status_code, 200, allowed.get_data(as_text=True))
        self.assertEqual(allowed.get_json()["room"]["status"], "occupied")

    def test_room_checkin_requires_fields(self):
        resp = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "checkin", "stay": {"firstName": "Only"}},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.get_json()["ok"])

        missing_rate = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000001",
                    "checkInDate": "2026-07-29",
                    "roomRate": 0,
                },
            },
        )
        self.assertEqual(missing_rate.status_code, 400)
        self.assertEqual(missing_rate.get_json()["error"], "Room rate is required.")

        missing_plan = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000001",
                    "checkInDate": "2026-07-29",
                    "roomRate": 2500,
                    "ratePlan": "",
                },
            },
        )
        self.assertEqual(missing_plan.status_code, 400)
        self.assertEqual(missing_plan.get_json()["error"], "Meal plan is required.")

    def test_room_transfer_vacant_only(self):
        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000001",
                    "checkInDate": "2026-07-29",
                    "roomRate": 2500,
                },
            },
        )
        self.assertEqual(checkin.status_code, 200)

        # Occupy another room so it is not offered as vacant.
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Other",
                    "lastName": "Guest",
                    "mobile": "9000000002",
                    "checkInDate": "2026-07-29",
                    "roomRate": 2500,
                },
            },
        )

        bad = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "transfer", "toRoomId": "room-102"},
        )
        self.assertEqual(bad.status_code, 400)
        self.assertIn("vacant", bad.get_json()["error"].lower())

        ok = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "transfer", "toRoomId": "room-103", "note": "Upgrade"},
        )
        self.assertEqual(ok.status_code, 200)
        payload = ok.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["fromRoom"]["status"], "dirty")
        self.assertNotIn("stay", payload["fromRoom"])
        self.assertEqual(payload["toRoom"]["status"], "occupied")
        self.assertEqual(payload["toRoom"]["stay"]["firstName"], "Asha")
        self.assertEqual(payload["toRoom"]["stay"]["transferCount"], 1)
        self.assertEqual(payload["toRoom"]["stay"]["transferHistory"][0]["fromRoomNumber"], "101")
        self.assertEqual(payload["toRoom"]["stay"]["transferHistory"][0]["toRoomNumber"], "103")

        vacant_only = self.client.put(
            "/hotel/api/rooms/room-103",
            json={"action": "transfer", "toRoomId": "room-101"},
        )
        self.assertEqual(vacant_only.status_code, 400)

    def test_room_transfer_clears_stale_vacant_stay_shell(self):
        """Vacant destinations with a cancelled reservation shell must still accept transfer."""
        import json

        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "roomRate": 2500,
                },
            },
        )
        self.assertEqual(checkin.status_code, 200)

        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            rooms = layout.get("rooms") or []
            for room in rooms:
                if room.get("id") != "room-105":
                    continue
                room["status"] = "vacant"
                room["stay"] = {
                    "checkInDate": "2026-08-01",
                    "checkOutDate": "2026-08-02",
                    "firstName": "",
                    "lastName": "",
                    "guestName": "",
                }
                break
            # Bypass save heal so the cancelled shell is present in storage.
            blob = json.dumps(
                {"floors": layout.get("floors") or [], "rooms": rooms},
                separators=(",", ":"),
            )
            conn.execute(
                """
                INSERT INTO hotel_rooms_layout (id, payload, updated_at)
                VALUES (1, ?, datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (blob,),
            )
            conn.commit()
        finally:
            conn.close()

        moved = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "transfer", "toRoomId": "room-105"},
        )
        self.assertEqual(moved.status_code, 200, moved.get_data(as_text=True))
        payload = moved.get_json()
        self.assertEqual(payload["toRoom"]["id"], "room-105")
        self.assertEqual(payload["toRoom"]["status"], "occupied")
        self.assertEqual(payload["toRoom"]["stay"]["firstName"], "Asha")
        self.assertEqual(payload["fromRoom"]["status"], "dirty")
        self.assertNotIn("stay", payload["fromRoom"])

    def test_guest_lookup_by_mobile(self):
        miss = self.client.get("/hotel/api/guests/lookup?mobile=9111111111")
        self.assertEqual(miss.status_code, 200)
        self.assertFalse(miss.get_json()["found"])

        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Priya",
                    "lastName": "Shah",
                    "mobile": "9876501234",
                    "email": "priya@example.com",
                    "checkInDate": "2026-07-29",
                    "city": "Mumbai",
                    "idType": "Aadhaar",
                    "idNumber": "9999",
                    "roomRate": 2500,
                },
            },
        )
        # Vacate so lookup still finds historical stay on the room layout.
        hit = self.client.get("/hotel/api/guests/lookup?mobile=9876501234")
        self.assertEqual(hit.status_code, 200)
        body = hit.get_json()
        self.assertTrue(body["found"])
        guest = body["guest"]
        self.assertEqual(guest["firstName"], "Priya")
        self.assertEqual(guest["lastName"], "Shah")
        self.assertEqual(guest["email"], "priya@example.com")
        self.assertEqual(guest["city"], "Mumbai")
        self.assertEqual(guest["returningGuest"], "Yes")

        # After checkout, stay is cleared — full profile still comes from guest profiles.
        self.client.put("/hotel/api/rooms/room-101", json={"action": "checkout"})
        after = self.client.get("/hotel/api/guests/lookup?mobile=9876501234")
        self.assertEqual(after.status_code, 200)
        after_body = after.get_json()
        self.assertTrue(after_body["found"])
        self.assertEqual(after_body["guest"]["firstName"], "Priya")
        self.assertEqual(after_body["guest"]["lastName"], "Shah")
        self.assertEqual(after_body["guest"]["email"], "priya@example.com")
        self.assertEqual(after_body["guest"]["city"], "Mumbai")
        self.assertEqual(after_body["guest"]["returningGuest"], "Yes")
        self.assertTrue(after_body.get("nameMatch", True))

    def test_hotel_guest_names_match(self):
        guest = {"firstName": "Priya", "lastName": "Shah"}
        self.assertTrue(db_mod.hotel_guest_names_match(guest, "", ""))
        self.assertTrue(db_mod.hotel_guest_names_match(guest, "priya", "SHAH"))
        self.assertTrue(db_mod.hotel_guest_names_match(guest, "Mr. Priya", "Shah"))
        self.assertFalse(db_mod.hotel_guest_names_match(guest, "Amit", "Khan"))
        self.assertFalse(db_mod.hotel_guest_names_match(guest, "Priya", "Khan"))

    def test_guest_lookup_returns_id_after_checkout(self):
        doc_path = "/hotel/api/id-documents/aa111111-2222-3333-4444-555555555555.pdf"
        extra_path = "/hotel/api/id-documents/bb111111-2222-3333-4444-555555555555.pdf"
        healed_doc = "/hotel/api/id-documents/view/aa111111-2222-3333-4444-555555555555.pdf/raw"
        healed_extra = "/hotel/api/id-documents/view/bb111111-2222-3333-4444-555555555555.pdf/raw"
        check_in, check_out = self._stay_window(nights=1)
        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Priya",
                    "lastName": "Shah",
                    "mobile": "9876501234",
                    "address": "12 Marine Drive",
                    "city": "Mumbai",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "roomRate": 2500,
                    "idType": "Aadhaar",
                    "idDocumentName": "Priya Shah Aadhaar.pdf",
                    "idDocumentPath": doc_path,
                    "idDocumentMime": "application/pdf",
                    "idDocumentStoredName": "aa111111-2222-3333-4444-555555555555.pdf",
                    "additionalGuests": [
                        {
                            "name": "Amit Shah",
                            "idType": "Passport",
                            "idDocumentName": "Amit Shah Passport.pdf",
                            "idDocumentPath": extra_path,
                            "idDocumentMime": "application/pdf",
                        }
                    ],
                },
            },
        )
        self.assertEqual(checkin.status_code, 200, checkin.get_data(as_text=True))
        self.client.put("/hotel/api/rooms/room-101", json={"action": "checkout"})

        hit = self.client.get("/hotel/api/guests/lookup?mobile=9876501234")
        self.assertEqual(hit.status_code, 200)
        body = hit.get_json()
        self.assertTrue(body["found"])
        self.assertTrue(body["nameMatch"])
        guest = body["guest"]
        self.assertEqual(guest["firstName"], "Priya")
        self.assertEqual(guest["idType"], "Aadhaar")
        self.assertEqual(guest["idDocumentPath"], healed_doc)
        self.assertEqual(guest["address"], "12 Marine Drive")
        extras = guest.get("additionalGuests") or []
        self.assertEqual(len(extras), 1)
        self.assertEqual(extras[0]["name"], "Amit Shah")
        self.assertEqual(extras[0]["idDocumentPath"], healed_extra)

        mismatch = self.client.get(
            "/hotel/api/guests/lookup?mobile=9876501234&firstName=Amit&lastName=Khan"
        )
        mismatch_body = mismatch.get_json()
        self.assertTrue(mismatch_body["found"])
        self.assertFalse(mismatch_body["nameMatch"])
        self.assertEqual(mismatch_body["guest"]["firstName"], "Priya")
        self.assertEqual(mismatch_body["guest"]["idDocumentPath"], healed_doc)

        titled = self.client.get(
            "/hotel/api/guests/lookup?mobile=9876501234&firstName=Mr%20Priya&lastName=Shah"
        )
        self.assertTrue(titled.get_json()["nameMatch"])

    def test_guest_profile_merge_keeps_id_without_reupload(self):
        doc_path = "/hotel/api/id-documents/cc111111-2222-3333-4444-555555555555.pdf"
        healed_doc = "/hotel/api/id-documents/view/cc111111-2222-3333-4444-555555555555.pdf/raw"
        check_in, check_out = self._stay_window(nights=1)
        first = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Arun",
                    "lastName": "Shetty",
                    "mobile": "9000011122",
                    "address": "9 MG Road",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "roomRate": 2500,
                    "idType": "Aadhaar",
                    "idDocumentName": "Arun Shetty Aadhaar.pdf",
                    "idDocumentPath": doc_path,
                    "idDocumentMime": "application/pdf",
                    "idDocumentStoredName": "cc111111-2222-3333-4444-555555555555.pdf",
                },
            },
        )
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.client.put("/hotel/api/rooms/room-101", json={"action": "checkout"})
        self.client.put("/hotel/api/rooms/room-101", json={"status": "vacant"})

        second = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Arun",
                    "lastName": "Shetty",
                    "mobile": "9000011122",
                    "address": "9 MG Road",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "roomRate": 2500,
                    "idType": "Aadhaar",
                    "idDocumentPath": "",
                    "idDocumentName": "",
                    "idDocumentMime": "",
                    "idDocumentStoredName": "",
                },
            },
        )
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))
        self.assertEqual(second.get_json()["room"]["stay"].get("idDocumentPath") or "", "")
        self.client.put("/hotel/api/rooms/room-101", json={"action": "checkout"})

        after = self.client.get("/hotel/api/guests/lookup?mobile=9000011122")
        self.assertEqual(after.status_code, 200)
        guest = after.get_json()["guest"]
        self.assertEqual(guest["idDocumentPath"], healed_doc)
        self.assertEqual(guest["idType"], "Aadhaar")
        self.assertEqual(guest["idDocumentName"], "Arun Shetty Aadhaar.pdf")

    def test_checkin_estimated_charges_and_folio_moves_on_transfer(self):
        check_in, check_out = self._stay_window(nights=2)
        checkin = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Ravi",
                    "lastName": "Menon",
                    "mobile": "9000000099",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 2500,
                    "totalRate": 5000,
                    "extraBedAmount": 500,
                    "earlyCheckinAmount": 250,
                    "advancePaid": 1000,
                    "folioCharges": [
                        {
                            "id": "fc-test-1",
                            "kind": "restaurant_room_transfer",
                            "label": "Restaurant Room Transfer · ORD-1",
                            "amount": 420,
                            "source": "pos",
                            "invoiceId": "9",
                            "outlet": "restaurant",
                        }
                    ],
                },
            },
        )
        self.assertEqual(checkin.status_code, 200, checkin.get_data(as_text=True))
        stay = checkin.get_json()["room"]["stay"]
        self.assertEqual(stay["roomRate"], 2500)
        self.assertEqual(stay["extraBedAmount"], 500)
        self.assertEqual(stay["earlyCheckinAmount"], 250)
        self.assertEqual(len(stay["folioCharges"]), 1)
        self.assertEqual(stay["folioCharges"][0]["kind"], "restaurant_room_transfer")
        self.assertEqual(stay["folioCharges"][0]["orderNo"], "ORD-1")
        self.assertEqual(
            stay["folioCharges"][0]["label"],
            "Restaurant Room Transfer · ORD-1",
        )
        # room 5000 + extras 750 + folio 420 = 6170 (tax-inclusive rates)
        self.assertEqual(stay["estimatedTotal"], 6170.0)
        self.assertEqual(stay["advancePaid"], 1000)
        self.assertEqual(stay["balanceAmount"], 5170.0)

        detail = self.client.get("/hotel/rooms/room-101")
        self.assertEqual(detail.status_code, 200)
        html = detail.get_data(as_text=True)
        self.assertIn("hrd-charges-card", html)
        self.assertIn("Estimated Charges", html)
        self.assertIn("data-charges-cgst", html)
        self.assertIn("data-charges-ugst", html)
        self.assertIn("CGST", html)
        self.assertIn("UGST", html)

        moved = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "transfer", "toRoomId": "room-105", "note": "Upgrade"},
        )
        self.assertEqual(moved.status_code, 200, moved.get_data(as_text=True))
        dest = moved.get_json()["toRoom"]["stay"]
        self.assertEqual(dest["firstName"], "Ravi")
        self.assertEqual(len(dest["folioCharges"]), 1)
        self.assertEqual(dest["folioCharges"][0]["amount"], 420)
        self.assertEqual(dest["estimatedTotal"], 6170.0)
        self.assertEqual(dest["balanceAmount"], 5170.0)
        self.assertNotIn("stay", moved.get_json()["fromRoom"])

    def test_pos_occupied_rooms_api_lists_in_house_only(self):
        empty = self.client.get("/point-of-sale/api/hotel-rooms/occupied")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.get_json()["rooms"], [])

        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "In",
                    "lastName": "House",
                    "mobile": "9000000088",
                    "checkInDate": "2026-07-29",
                    "roomRate": 2500,
                },
            },
        )
        self.client.put("/hotel/api/rooms/room-102", json={"status": "dirty"})

        listed = self.client.get("/point-of-sale/api/hotel-rooms/occupied")
        self.assertEqual(listed.status_code, 200)
        rooms = listed.get_json()["rooms"]
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0]["id"], "room-101")
        self.assertIn("In", rooms[0]["guestName"])

    def _checkin_with_charges(self, room_id="room-101", advance=1000):
        check_in, check_out = self._stay_window(nights=2)
        res = self.client.put(
            f"/hotel/api/rooms/{room_id}",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Ravi",
                    "lastName": "Menon",
                    "mobile": "9000000099",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 2500,
                    "totalRate": 5000,
                    "extraBedAmount": 500,
                    "earlyCheckinAmount": 250,
                    "advancePaid": advance,
                },
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json()["room"]

    def test_overstay_adds_room_charge_per_extra_day(self):
        today = datetime.now().date()
        check_in = (today - timedelta(days=2)).isoformat()
        check_out = (today - timedelta(days=1)).isoformat()  # expected yesterday
        res = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Over",
                    "lastName": "Stay",
                    "mobile": "9000000888",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 3500,
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        stay = res.get_json()["room"]["stay"]
        self.assertEqual(stay["nights"], 1)
        self.assertEqual(stay["overstayNights"], 1)
        self.assertEqual(stay["billableNights"], 2)
        # 3500 * 2 nights (tax-inclusive)
        self.assertEqual(stay["estimatedTotal"], 7000.0)
        self.assertEqual(stay["balanceAmount"], 7000.0)

        # Two days past expected checkout → two overstay nights.
        older_out = (today - timedelta(days=2)).isoformat()
        older_in = (today - timedelta(days=3)).isoformat()
        res2 = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Long",
                    "lastName": "Stay",
                    "mobile": "9000000889",
                    "checkInDate": older_in,
                    "checkOutDate": older_out,
                    "nights": 1,
                    "roomRate": 3500,
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(res2.status_code, 200, res2.get_data(as_text=True))
        stay2 = res2.get_json()["room"]["stay"]
        self.assertEqual(stay2["overstayNights"], 2)
        self.assertEqual(stay2["billableNights"], 3)
        self.assertEqual(stay2["estimatedTotal"], 10500.0)

    def test_generate_invoice_mints_number_and_allows_partial_payment(self):
        room = self._checkin_with_charges()
        stay = room["stay"]
        self.assertEqual(stay["estimatedTotal"], 5750.0)
        self.assertEqual(stay["advancePaid"], 1000)
        self.assertEqual(stay["balanceAmount"], 4750.0)
        self.assertFalse(stay.get("invoiceGenerated"))

        detail = self.client.get("/hotel/rooms/room-101")
        html = detail.get_data(as_text=True)
        self.assertIn("hrd-generate-invoice", html)
        self.assertIn("hrd-invoice-modal", html)
        self.assertIn("hrd-invoice-add-split", html)
        self.assertIn("Split Payment", html)

        invoice_page = self.client.get("/hotel/rooms/room-101/invoice")
        self.assertEqual(invoice_page.status_code, 200, invoice_page.get_data(as_text=True))
        inv_html = invoice_page.get_data(as_text=True)
        self.assertIn("hotel-room-invoice-page", inv_html)
        self.assertIn("pos-invoice-page", inv_html)
        self.assertIn("pos_invoice.css", inv_html)
        self.assertIn("hri-generate", inv_html)
        self.assertIn("Generate Invoice", inv_html)
        self.assertIn("Settle Bill", inv_html)
        self.assertIn("Bill Summary", inv_html)
        self.assertIn("pos-inv-settle-modal", inv_html)
        self.assertIn("hri-sum-cgst", inv_html)
        self.assertIn("hri-sum-ugst", inv_html)
        self.assertIn("UGST", inv_html)
        self.assertIn("(2.5% incl.)", inv_html)
        self.assertIn("hri-tool-discount", inv_html)
        self.assertIn("Add Discount", inv_html)
        self.assertIn("hri-discount-modal", inv_html)
        self.assertIn("hri-add-custom", inv_html)
        self.assertIn("Custom Charges", inv_html)
        self.assertIn("hri-custom-modal", inv_html)

        generated = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {
                    "amount": 1500,
                    "method": "upi",
                    "reference": "UPI123",
                    "note": "Partial",
                },
            },
        )
        self.assertEqual(generated.status_code, 200, generated.get_data(as_text=True))
        body = generated.get_json()
        stay = body["room"]["stay"]
        self.assertTrue(body.get("minted"))
        self.assertTrue(stay["invoiceGenerated"])
        self.assertTrue(str(stay["invoiceNumber"]).startswith("HBE/RM/"))
        self.assertEqual(stay["checkInAdvancePaid"], 1000)
        self.assertEqual(len(stay["payments"]), 1)
        self.assertEqual(stay["payments"][0]["amount"], 1500)
        self.assertEqual(stay["payments"][0]["method"], "upi")
        self.assertEqual(stay["advancePaid"], 2500)
        self.assertEqual(stay["balanceAmount"], 3250.0)
        self.assertEqual(body["room"]["status"], "occupied")

        # Second generate does not mint a new number.
        again = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "generate_invoice", "amount": 0},
        )
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        self.assertFalse(again.get_json().get("minted"))
        self.assertEqual(
            again.get_json()["room"]["stay"]["invoiceNumber"], stay["invoiceNumber"]
        )

    def test_set_discount_updates_balance_and_locks_after_generate(self):
        room = self._checkin_with_charges()
        self.assertEqual(room["stay"]["estimatedTotal"], 5750.0)
        self.assertEqual(room["stay"]["balanceAmount"], 4750.0)

        discounted = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "set_discount",
                "discountType": "pct",
                "discountValue": 10,
            },
        )
        self.assertEqual(discounted.status_code, 200, discounted.get_data(as_text=True))
        stay = discounted.get_json()["room"]["stay"]
        self.assertEqual(stay["discountType"], "pct")
        self.assertEqual(stay["discountValue"], 10)
        self.assertEqual(stay["discountAmount"], 575.0)
        self.assertEqual(stay["estimatedTotal"], 5175.0)
        self.assertEqual(stay["balanceAmount"], 4175.0)

        needs_reason = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "set_discount",
                "discountType": "pct",
                "discountValue": 20,
            },
        )
        self.assertEqual(needs_reason.status_code, 400)
        self.assertIn("reason", needs_reason.get_json().get("error", "").lower())

        with_reason = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "set_discount",
                "discountType": "pct",
                "discountValue": 20,
                "discountReason": "Loyalty guest",
            },
        )
        self.assertEqual(with_reason.status_code, 200, with_reason.get_data(as_text=True))
        stay = with_reason.get_json()["room"]["stay"]
        self.assertEqual(stay["discountAmount"], 1150.0)
        self.assertEqual(stay["discountReason"], "Loyalty guest")

        generated = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "generate_invoice", "amount": 0},
        )
        self.assertEqual(generated.status_code, 200, generated.get_data(as_text=True))
        locked = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "set_discount", "discountType": "pct", "discountValue": 5},
        )
        self.assertEqual(locked.status_code, 400)
        self.assertIn("generated", locked.get_json().get("error", "").lower())

    def test_add_custom_charge_updates_folio_and_locks_after_generate(self):
        room = self._checkin_with_charges()
        before = room["stay"]["estimatedTotal"]
        added = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "add_custom_charge",
                "label": "Mini bar",
                "amount": 350,
            },
        )
        self.assertEqual(added.status_code, 200, added.get_data(as_text=True))
        stay = added.get_json()["room"]["stay"]
        self.assertEqual(stay["estimatedTotal"], round(before + 350, 2))
        labels = [f.get("label") for f in stay.get("folioCharges") or []]
        self.assertIn("Mini bar", labels)

        generated = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "generate_invoice", "amount": 0},
        )
        self.assertEqual(generated.status_code, 200, generated.get_data(as_text=True))
        locked = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "add_custom_charge", "label": "Late fee", "amount": 100},
        )
        self.assertEqual(locked.status_code, 400)
        self.assertIn("generated", locked.get_json().get("error", "").lower())

    def test_update_and_delete_folio_charges(self):
        room = self._checkin_with_charges()
        self.assertEqual(room["stay"]["extraBedAmount"], 500)

        updated = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "update_charge",
                "chargeKey": "extra_bed",
                "amount": 750,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.get_data(as_text=True))
        self.assertEqual(updated.get_json()["room"]["stay"]["extraBedAmount"], 750)

        room_rate = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "update_charge",
                "chargeKey": "room",
                "rate": 3000,
            },
        )
        self.assertEqual(room_rate.status_code, 200, room_rate.get_data(as_text=True))
        stay = room_rate.get_json()["room"]["stay"]
        self.assertEqual(stay["roomRate"], 3000)
        self.assertEqual(stay["totalRate"], 6000)

        deleted = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "delete_charge", "chargeKey": "extra_bed"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.get_data(as_text=True))
        self.assertEqual(deleted.get_json()["room"]["stay"]["extraBedAmount"], 0)

        refuse_room = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "delete_charge", "chargeKey": "room"},
        )
        self.assertEqual(refuse_room.status_code, 400)

        custom = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "add_custom_charge",
                "label": "Laundry",
                "amount": 200,
            },
        )
        self.assertEqual(custom.status_code, 200, custom.get_data(as_text=True))
        folio = custom.get_json()["room"]["stay"]["folioCharges"]
        laundry = next(f for f in folio if f.get("label") == "Laundry")
        folio_key = "folio:" + laundry["id"]
        renamed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "update_charge",
                "chargeKey": folio_key,
                "label": "Laundry service",
                "amount": 250,
            },
        )
        self.assertEqual(renamed.status_code, 200, renamed.get_data(as_text=True))
        folio2 = renamed.get_json()["room"]["stay"]["folioCharges"]
        item = next(f for f in folio2 if f.get("id") == laundry["id"])
        self.assertEqual(item["label"], "Laundry service")
        self.assertEqual(item["amount"], 250)

        removed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "delete_charge", "chargeKey": folio_key},
        )
        self.assertEqual(removed.status_code, 200, removed.get_data(as_text=True))
        labels = [f.get("label") for f in removed.get_json()["room"]["stay"]["folioCharges"]]
        self.assertNotIn("Laundry service", labels)

    def test_record_payment_rejects_before_generate_and_overpay(self):
        self._checkin_with_charges()
        early = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "record_payment", "amount": 100, "method": "cash"},
        )
        self.assertEqual(early.status_code, 400)
        self.assertIn("Generate", early.get_json().get("error", ""))

        self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "generate_invoice", "amount": 0},
        )
        over = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "amount": 99999,
                "method": "cash",
            },
        )
        self.assertEqual(over.status_code, 400)
        self.assertIn("exceeds", over.get_json().get("error", "").lower())

        bank = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "amount": 100,
                "method": "bank_transfer",
            },
        )
        self.assertEqual(bank.status_code, 400)
        self.assertIn("reference", bank.get_json().get("error", "").lower())

    def test_full_payment_then_checkout(self):
        self._checkin_with_charges(advance=0)
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 2000, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        stay = gen.get_json()["room"]["stay"]
        self.assertEqual(stay["advancePaid"], 2000)
        balance = stay["balanceAmount"]
        self.assertGreater(balance, 0)

        paid = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "amount": balance,
                "method": "card",
            },
        )
        self.assertEqual(paid.status_code, 200, paid.get_data(as_text=True))
        stay = paid.get_json()["room"]["stay"]
        self.assertEqual(stay["balanceAmount"], 0)
        self.assertEqual(len(stay["payments"]), 2)
        self.assertEqual(stay["advancePaid"], stay["estimatedTotal"])

        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        room = closed.get_json()["room"]
        self.assertEqual(room["status"], "dirty")
        self.assertNotIn("stay", room)

    def test_generate_invoice_split_payment(self):
        self._checkin_with_charges(advance=0)
        split = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment_splits": [
                    {"payment_method": "cash", "amount": 3000},
                    {
                        "payment_method": "upi",
                        "amount": 2000,
                        "transaction_id": "",
                    },
                ],
                "note": "Split at desk",
            },
        )
        self.assertEqual(split.status_code, 200, split.get_data(as_text=True))
        stay = split.get_json()["room"]["stay"]
        self.assertTrue(stay["invoiceGenerated"])
        self.assertEqual(stay["advancePaid"], 5000)
        self.assertEqual(stay["balanceAmount"], 750.0)
        self.assertEqual(len(stay["payments"]), 2)
        methods = sorted(p["method"] for p in stay["payments"])
        self.assertEqual(methods, ["cash", "upi"])

        over = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "payment_splits": [
                    {"payment_method": "cash", "amount": 600},
                    {"payment_method": "card", "amount": 600},
                ],
            },
        )
        self.assertEqual(over.status_code, 400)

        done = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "payment_splits": [
                    {"payment_method": "cash", "amount": 400},
                    {
                        "payment_method": "bank_transfer",
                        "amount": 350,
                        "transaction_id": "NEFT991",
                    },
                ],
            },
        )
        self.assertEqual(done.status_code, 200, done.get_data(as_text=True))
        stay = done.get_json()["room"]["stay"]
        self.assertEqual(stay["balanceAmount"], 0)
        self.assertEqual(len(stay["payments"]), 4)

    def test_credit_payment_requires_agency(self):
        self._checkin_with_charges(advance=0)
        denied = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment_splits": [
                    {"payment_method": "credit", "amount": 1000},
                ],
            },
        )
        self.assertEqual(denied.status_code, 400)
        self.assertIn("agency", denied.get_json().get("error", "").lower())

        with_agency = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Iyer",
                    "mobile": "9000000077",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                    "agencyName": "Travel Desk Co",
                    "agencyBilling": True,
                },
            },
        )
        self.assertEqual(with_agency.status_code, 200, with_agency.get_data(as_text=True))
        credited = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "generate_invoice",
                "payment_splits": [
                    {"payment_method": "credit", "amount": 500},
                    {"payment_method": "cash", "amount": 500},
                ],
            },
        )
        self.assertEqual(credited.status_code, 200, credited.get_data(as_text=True))
        stay = credited.get_json()["room"]["stay"]
        methods = sorted(p["method"] for p in stay["payments"])
        self.assertEqual(methods, ["cash", "credit"])
        self.assertEqual(stay["advancePaid"], 1000)

    def test_invoice_ledger_lists_generated_invoice(self):
        room = self._checkin_with_charges(advance=0)
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 500, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        inv_no = gen.get_json()["room"]["stay"]["invoiceNumber"]
        self.assertTrue(inv_no)

        page = self.client.get("/hotel/invoice-ledger")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Invoice Ledger", html)
        self.assertIn(inv_no, html)
        self.assertIn("is-open", html)
        self.assertIn("Un Settled", html)
        self.assertIn("pos-inv-settle-modal", html)
        self.assertIn("hotel_settle_modal.js", html)
        self.assertIn("data-hil-settle", html)
        self.assertIn('data-room-id="room-101"', html)
        self.assertIn("Settle invoice", html)
        self.assertIn("hil-view-btn", html)
        self.assertIn("hil-print-btn", html)
        self.assertIn("de-nav-hotel-invoice-ledger", html)
        self.assertIn("de-nav-hotel-credit", html)
        self.assertIn("hil-invoice-listbox", html)
        self.assertIn("Room Transfer", html)
        self.assertIn(">Invoice</span>", html)

        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200)
        payload = api.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["invoice"]["invoice_number"], inv_no)
        self.assertEqual(payload["room"]["stay"]["invoiceNumber"], inv_no)
        self.assertGreater(float(payload["invoice"]["balance_amount"]), 0)
        self.assertEqual(payload["invoice"]["status"], "open")

        settle = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={
                "payment_splits": [
                    {"method": "cash", "amount": payload["invoice"]["balance_amount"]}
                ]
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        settled = settle.get_json()
        self.assertTrue(settled["ok"])
        self.assertEqual(settled["invoice"]["status"], "settled")
        self.assertLessEqual(float(settled["invoice"]["balance_amount"]), 0.009)
        ledger = self.client.get("/hotel/invoice-ledger")
        self.assertIn("Payment Mode", ledger.get_data(as_text=True))
        conn = db_mod.get_db()
        try:
            rows = db_mod.list_hotel_room_invoices(conn, q=inv_no)
        finally:
            conn.close()
        match = next(row for row in rows if row["invoice_number"] == inv_no)
        self.assertEqual(match["status"], "settled")
        self.assertEqual(match["payment_mode_label"], "Cash")
        self.assertEqual(match["payment_modes"], ["cash"])

    def test_invoice_ledger_payment_mode_shows_split_tenders(self):
        self._checkin_with_charges(advance=0)
        stay = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]["stay"]
        total = round(float(stay["balanceAmount"]), 2)
        cash_part = round(total / 2, 2)
        upi_part = round(total - cash_part, 2)
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment_splits": [
                    {"payment_method": "cash", "amount": cash_part},
                    {"payment_method": "upi", "amount": upi_part},
                ],
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        inv_no = gen.get_json()["room"]["stay"]["invoiceNumber"]
        conn = db_mod.get_db()
        try:
            rows = db_mod.list_hotel_room_invoices(conn, q=inv_no)
        finally:
            conn.close()
        match = next(row for row in rows if row["invoice_number"] == inv_no)
        self.assertEqual(match["status"], "settled")
        self.assertEqual(match["payment_mode_label"], "Cash + UPI")
        self.assertEqual(match["payment_modes"], ["cash", "upi"])

    def test_pos_room_transfer_lists_on_invoice_ledger(self):
        """Restaurant/bar room transfers appear as Un Settled hotel invoices."""
        self._checkin_with_charges(advance=0)
        conn = db_mod.get_db()
        try:
            result = db_mod.append_hotel_room_folio_charge(
                conn,
                "room-101",
                amount=150.48,
                kind="restaurant_room_transfer",
                label="Restaurant Room Transfer · SPC/26-27/12",
                source="pos",
                invoice_id="99",
                order_no="SPC/26-27/12",
                outlet="restaurant",
            )
            db_mod.upsert_pos_room_transfer_invoice(
                conn, result["room"], result["charge"]
            )
            conn.commit()
        finally:
            conn.close()

        page = self.client.get("/hotel/invoice-ledger")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("SPC/26-27/12", html)
        self.assertIn("Un Settled", html)

        room_transfer = self.client.get(
            "/hotel/invoice-ledger?invoice=room_transfer"
        )
        self.assertIn("SPC/26-27/12", room_transfer.get_data(as_text=True))
        hotel_only = self.client.get("/hotel/invoice-ledger?invoice=hotel")
        self.assertNotIn("SPC/26-27/12", hotel_only.get_data(as_text=True))

        stay = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]["stay"]
        balance_before = float(stay["balanceAmount"])
        settle = self.client.post(
            "/hotel/invoice-ledger/api/SPC/26-27/12/settle",
            json={
                "payment_splits": [{"method": "cash", "amount": 150.48}],
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        settled = settle.get_json()
        self.assertTrue(settled["ok"])
        self.assertEqual(settled["invoice"]["status"], "settled")
        self.assertEqual(settled["invoice"]["source"], "pos_room_transfer")
        stay_after = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]["stay"]
        self.assertAlmostEqual(
            float(stay_after["balanceAmount"]),
            round(balance_before - 150.48, 2),
            places=2,
        )
        folio = stay_after["folioCharges"]
        self.assertTrue(any(f.get("settled") for f in folio))

    def test_pos_room_transfer_ledger_allow_credit_when_stay_has_agency(self):
        """Room-transfer bills on the ledger expose Credit when the live stay has an agency."""
        check_in, check_out = self._stay_window(nights=2)
        res = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Agency",
                    "lastName": "Guest",
                    "mobile": "9000000099",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 2500,
                    "totalRate": 5000,
                    "advancePaid": 0,
                    "agencyName": "Travel Co",
                    "agencyGst": "27AAAAA0000A1Z5",
                },
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        conn = db_mod.get_db()
        try:
            result = db_mod.append_hotel_room_folio_charge(
                conn,
                "room-101",
                amount=158.0,
                kind="restaurant_room_transfer",
                label="Restaurant Room Transfer · SPC/26-27/99",
                source="pos",
                invoice_id="199",
                order_no="SPC/26-27/99",
                outlet="restaurant",
            )
            db_mod.upsert_pos_room_transfer_invoice(
                conn, result["room"], result["charge"]
            )
            conn.commit()
        finally:
            conn.close()

        api = self.client.get("/hotel/invoice-ledger/api/SPC/26-27/99")
        self.assertEqual(api.status_code, 200, api.get_data(as_text=True))
        payload = api.get_json()
        self.assertTrue(payload["allow_credit"])
        self.assertEqual(
            payload["room"]["stay"].get("agencyName")
            or payload["room"]["stay"].get("agency_name"),
            "Travel Co",
        )

        settle = self.client.post(
            "/hotel/invoice-ledger/api/SPC/26-27/99/settle",
            json={
                "payment_splits": [{"method": "credit", "amount": 158.0}],
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        settled = settle.get_json()
        self.assertTrue(settled["ok"])
        self.assertEqual(settled["invoice"]["status"], "settled")

    def test_stay_payment_settles_linked_pos_room_transfer(self):
        self._checkin_with_charges(advance=0)
        conn = db_mod.get_db()
        try:
            result = db_mod.append_hotel_room_folio_charge(
                conn,
                "room-101",
                amount=80,
                kind="bar_room_transfer",
                label="Bar Room Transfer · INV/26-27/4",
                source="pos",
                invoice_id="100",
                order_no="INV/26-27/4",
                outlet="bar",
            )
            db_mod.upsert_pos_room_transfer_invoice(
                conn, result["room"], result["charge"]
            )
            conn.commit()
        finally:
            conn.close()
        stay = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]["stay"]
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment_splits": [
                    {"method": "upi", "amount": stay["balanceAmount"]},
                ],
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        api = self.client.get("/hotel/invoice-ledger/api/INV/26-27/4")
        self.assertEqual(api.status_code, 200)
        item = api.get_json()["invoice"]
        self.assertEqual(item["status"], "settled")
        self.assertLessEqual(float(item["balance_amount"]), 0.009)

    def test_invoice_ledger_settle_after_checkout(self):
        self._checkin_with_charges(advance=0)
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment_splits": [],
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        stay = gen.get_json()["room"]["stay"]
        inv_no = stay["invoiceNumber"]
        balance = stay["balanceAmount"]
        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertNotIn("stay", closed.get_json()["room"])

        settle = self.client.post(
            f"/hotel/invoice-ledger/api/{inv_no}/settle",
            json={
                "payment_splits": [{"method": "upi", "amount": balance}],
            },
        )
        self.assertEqual(settle.status_code, 200, settle.get_data(as_text=True))
        settled = settle.get_json()
        self.assertTrue(settled["ok"])
        self.assertEqual(settled["invoice"]["status"], "settled")
        self.assertLessEqual(float(settled["invoice"]["balance_amount"]), 0.009)

        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200)
        item = api.get_json()["invoice"]
        self.assertEqual(item["status"], "settled")

    def test_invoice_ledger_survives_checkout(self):
        self._checkin_with_charges(advance=0)
        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 2000, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        stay = gen.get_json()["room"]["stay"]
        inv_no = stay["invoiceNumber"]
        balance = stay["balanceAmount"]
        paid = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "record_payment",
                "amount": balance,
                "method": "card",
            },
        )
        self.assertEqual(paid.status_code, 200, paid.get_data(as_text=True))
        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertNotIn("stay", closed.get_json()["room"])

        page = self.client.get("/hotel/invoice-ledger")
        self.assertEqual(page.status_code, 200)
        self.assertIn(inv_no, page.get_data(as_text=True))

        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200)
        payload = api.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("stay", payload["room"])
        self.assertEqual(payload["room"]["stay"]["invoiceNumber"], inv_no)
        self.assertEqual(payload["invoice"]["status"], "settled")
        self.assertLessEqual(float(payload["invoice"]["balance_amount"]), 0.009)

    def test_invoice_ledger_access_gate(self):
        from workspace_access import get_endpoint_dashboard_module

        self.assertEqual(
            get_endpoint_dashboard_module("hotel_invoice_ledger"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_invoice_ledger_api"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_invoice_ledger_export"), "hotel_rooms"
        )
        self.assertEqual(
            get_endpoint_dashboard_module("hotel_invoice_ledger_settle_api"),
            "hotel_rooms",
        )

        viewer = {
            "id": self.admin_id,
            "username": "posonly",
            "full_name": "POS Only",
            "is_admin": False,
            "is_active": True,
            "dashboard_access": {"point_of_sale"},
            "stores_access": set(),
            "sales_analytics_access": set(),
            "user_access": set(),
            "payroll_access": set(),
            "accounts_access": set(),
        }
        with mock.patch.object(self.app_mod, "get_current_user", return_value=viewer):
            denied_page = self.client.get("/hotel/invoice-ledger")
            denied_rooms = self.client.get("/hotel/rooms")
            denied_api = self.client.get(
                "/hotel/invoice-ledger/api/HBE/RM/1/2025-26",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        self.assertIn(denied_page.status_code, (302, 403))
        self.assertIn(denied_rooms.status_code, (302, 403))
        self.assertEqual(denied_api.status_code, 403)

    def test_merge_rooms_combines_billing_onto_primary(self):
        self._checkin_with_charges("room-101", advance=500)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 3000,
                    "totalRate": 3000,
                    "advancePaid": 200,
                },
            },
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-102",
                "toRoomId": "room-101",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        body = merged.get_json()
        primary = body["primaryRoom"]
        member = body["memberRoom"]
        self.assertTrue(primary["isMergePrimary"])
        self.assertTrue(member["isMergeMember"])
        self.assertEqual(member["stay"]["billingRoomId"], "room-101")
        self.assertEqual(member["stay"]["mergeRole"], "member")
        # Member room charge + advances moved onto primary folio/advance.
        folio_labels = [f.get("label") for f in primary["stay"]["folioCharges"]]
        self.assertTrue(any("Room 102" in (label or "") for label in folio_labels))
        absorb_lines = [
            f
            for f in primary["stay"]["folioCharges"]
            if f.get("source") == "room_merge"
            and str(f.get("sourceRoomId") or "") == "room-102"
        ]
        self.assertEqual(len(absorb_lines), 1, primary["stay"]["folioCharges"])
        # No duplicate auto rate line alongside the absorb for the same member.
        rate_dupes = [
            f
            for f in primary["stay"]["folioCharges"]
            if f.get("source") == "merged_room_rate"
            and str(f.get("sourceRoomId") or "") == "room-102"
        ]
        self.assertEqual(rate_dupes, [])
        self.assertGreaterEqual(float(primary["stay"]["advancePaid"]), 700)
        self.assertGreater(float(primary["stay"]["estimatedTotal"]), 5750)

        blocked = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "generate_invoice", "amount": 0},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("primary", blocked.get_json().get("error", "").lower())

        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "generate_invoice", "amount": 0},
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        gen_stay = gen.get_json()["room"]["stay"]
        self.assertTrue(gen_stay["invoiceNumber"])
        self.assertEqual(gen_stay.get("mergeRoomLabel"), "101 + 102")
        self.assertEqual(gen_stay.get("mergeRoomNumbers"), ["101", "102"])

    def test_merge_promotes_guest_onto_vacant_primary(self):
        """Occupied member guest becomes the primary bill guest for board/invoice."""
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Priya",
                    "lastName": "Menon",
                    "mobile": "9000000099",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2500,
                    "advancePaid": 0,
                },
            },
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-101",
                "toRoomId": "room-106",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        primary = merged.get_json()["primaryRoom"]
        self.assertEqual(primary["id"], "room-106")
        stay = primary["stay"]
        self.assertIn("Priya", stay.get("guestName") or stay.get("firstName") or "")
        self.assertEqual(stay.get("mobile"), "9000000099")

        member = merged.get_json()["memberRoom"]
        mstay = member["stay"]
        self.assertIn("Priya", mstay.get("guestName") or mstay.get("firstName") or "")
        self.assertEqual(mstay.get("mobile"), "9000000099")

        # Both detail APIs expose the same guest; member also sees shared bill totals.
        primary_get = self.client.get("/hotel/api/rooms/room-106").get_json()["room"]
        member_get = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        p_name = primary_get["stay"].get("guestName") or primary_get["stay"].get("firstName")
        m_name = member_get["stay"].get("guestName") or member_get["stay"].get("firstName")
        self.assertIn("Priya", p_name or "")
        self.assertEqual(p_name, m_name)
        self.assertEqual(
            primary_get["stay"].get("mobile"), member_get["stay"].get("mobile")
        )
        self.assertGreater(float(primary_get["stay"].get("estimatedTotal") or 0), 0)
        self.assertEqual(
            float(primary_get["stay"].get("estimatedTotal") or 0),
            float(member_get["stay"].get("estimatedTotal") or 0),
        )

    def test_checkin_on_merge_primary_replicates_to_member(self):
        """After vacant-vacant merge, check-in on primary copies guest onto the member."""
        check_in, check_out = self._stay_window(nights=2)
        merged = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-105",
                "toRoomId": "room-106",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        checked = self.client.put(
            "/hotel/api/rooms/room-106",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Karan",
                    "lastName": "Singh",
                    "mobile": "9000000088",
                    "email": "karan@example.com",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 3000,
                    "advancePaid": 500,
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        primary = self.client.get("/hotel/api/rooms/room-106").get_json()["room"]
        member = self.client.get("/hotel/api/rooms/room-105").get_json()["room"]
        self.assertIn("Karan", primary["stay"].get("guestName") or "")
        self.assertIn("Karan", member["stay"].get("guestName") or "")
        self.assertEqual(primary["stay"].get("mobile"), "9000000088")
        self.assertEqual(member["stay"].get("mobile"), "9000000088")
        self.assertEqual(primary["stay"].get("email"), member["stay"].get("email"))
        self.assertGreater(float(primary["stay"].get("estimatedTotal") or 0), 0)
        self.assertEqual(
            float(primary["stay"].get("estimatedTotal") or 0),
            float(member["stay"].get("estimatedTotal") or 0),
        )
        # Member tariff is typed at check-in; it is not filled from Hotel Settings.
        folio = primary["stay"].get("folioCharges") or []
        rate_lines = [f for f in folio if f.get("source") == "merged_room_rate"]
        self.assertEqual(rate_lines, [])
        # Primary ₹3000 × 2 nights
        self.assertAlmostEqual(
            float(primary["stay"].get("estimatedTotal") or 0), 6000.0, places=2
        )
        self.assertEqual(primary["status"], "occupied")
        self.assertEqual(member["status"], "vacant")

    def test_merged_occupied_rooms_keep_distinct_guest_names(self):
        """Each occupied merge peer keeps its own guest; folio stays on primary."""
        check_in, check_out = self._stay_window(nights=1)
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-201",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Anita",
                        "lastName": "Rao",
                        "mobile": "9000000301",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 1,
                        "roomRate": 2500,
                    },
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-202",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Vikram",
                        "lastName": "Shah",
                        "mobile": "9000000302",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 1,
                        "roomRate": 2600,
                    },
                },
            ).status_code,
            200,
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-202",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-202",
                "toRoomId": "room-201",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        primary = self.client.get("/hotel/api/rooms/room-201").get_json()["room"]
        member = self.client.get("/hotel/api/rooms/room-202").get_json()["room"]
        self.assertIn("Anita", primary["stay"].get("guestName") or "")
        self.assertIn("Vikram", member["stay"].get("guestName") or "")
        self.assertEqual(primary["stay"].get("mobile"), "9000000301")
        self.assertEqual(member["stay"].get("mobile"), "9000000302")
        layout = self.client.get("/hotel/api/rooms").get_json()
        rooms = {r["id"]: r for r in layout.get("rooms") or []}
        p_name = rooms["room-201"]["stay"].get("guestName") or rooms["room-201"][
            "stay"
        ].get("firstName")
        m_name = rooms["room-202"]["stay"].get("guestName") or rooms["room-202"][
            "stay"
        ].get("firstName")
        self.assertIn("Anita", p_name or "")
        self.assertIn("Vikram", m_name or "")
        self.assertGreater(float(primary["stay"].get("estimatedTotal") or 0), 0)
        self.assertEqual(
            float(primary["stay"].get("estimatedTotal") or 0),
            float(member["stay"].get("estimatedTotal") or 0),
        )
        member_html = self.client.get("/hotel/rooms/room-202").get_data(as_text=True)
        self.assertIn("Vikram", member_html)
        name_bit = member_html.split('id="hrd-guest-name"', 1)[-1][:120]
        self.assertIn("Vikram", name_bit)
        self.assertNotIn("Anita", name_bit)

    def test_merge_member_agency_comes_from_primary(self):
        """Merged member guest card shows the billing primary's agency."""
        check_in, check_out = self._stay_window(nights=1)
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-201",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Anita",
                        "lastName": "Rao",
                        "mobile": "9000000301",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 1,
                        "roomRate": 2500,
                        "agencyName": "ATPI India Pvt. Ltd",
                        "agencyGst": "27AABCU9603R1ZM",
                        "agencyAddress": "Bhandup West, Mumbai",
                        "agencyBilling": True,
                        "invoiceTo": "ATPI India Pvt. Ltd",
                    },
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-202",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Vikram",
                        "lastName": "Shah",
                        "mobile": "9000000302",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 1,
                        "roomRate": 2600,
                    },
                },
            ).status_code,
            200,
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-202",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-202",
                "toRoomId": "room-201",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        member = self.client.get("/hotel/api/rooms/room-202").get_json()["room"]
        stay = member.get("stay") or {}
        self.assertIn("Vikram", stay.get("guestName") or "")
        self.assertEqual(stay.get("agencyName"), "ATPI India Pvt. Ltd")
        self.assertEqual(stay.get("agencyGst"), "27AABCU9603R1ZM")
        self.assertEqual(stay.get("agencyAddress"), "Bhandup West, Mumbai")
        html = self.client.get("/hotel/rooms/room-202").get_data(as_text=True)
        self.assertIn("ATPI India Pvt. Ltd", html)
        self.assertIn("27AABCU9603R1ZM", html)
        self.assertNotIn('id="hrd-agency-card" hidden', html)

    def test_checkin_on_vacant_merge_member_keeps_own_guest(self):
        """Check-in on a vacant merge member is not overwritten by the primary guest."""
        check_in, check_out = self._stay_window(nights=2)
        merged = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-105",
                "toRoomId": "room-106",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        self.assertEqual(
            self.client.put(
                "/hotel/api/rooms/room-106",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Karan",
                        "lastName": "Singh",
                        "mobile": "9000000088",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 2,
                        "roomRate": 3000,
                    },
                },
            ).status_code,
            200,
        )
        checked = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Meera",
                    "lastName": "Nair",
                    "mobile": "9000000089",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 2,
                    "roomRate": 3500,
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        primary = self.client.get("/hotel/api/rooms/room-106").get_json()["room"]
        member = self.client.get("/hotel/api/rooms/room-105").get_json()["room"]
        self.assertIn("Karan", primary["stay"].get("guestName") or "")
        self.assertIn("Meera", member["stay"].get("guestName") or "")
        self.assertEqual(primary["stay"].get("mobile"), "9000000088")
        self.assertEqual(member["stay"].get("mobile"), "9000000089")
        self.assertEqual(member["status"], "occupied")
        self.assertEqual(primary["status"], "occupied")

    def test_checkin_on_reserved_merge_member_occupies_only_that_room(self):
        """Check-in on a reserved merge member occupies that room only."""
        check_in, check_out = self._stay_window(nights=1)
        stay = {
            "guestName": "Manoj Vijayan",
            "firstName": "Manoj",
            "lastName": "Vijayan",
            "mobile": "9876500101",
        }
        for room_id in ("room-101", "room-103"):
            reserved = self.client.put(
                f"/hotel/api/rooms/{room_id}",
                json={
                    "action": "reserve",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "stay": stay,
                },
            )
            self.assertEqual(reserved.status_code, 200, reserved.get_data(as_text=True))
            self.assertEqual(reserved.get_json()["room"]["status"], "reserved")
        merged = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-101",
                "toRoomId": "room-103",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        checked = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Manoj",
                    "lastName": "Vijayan",
                    "mobile": "9876500101",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        member = checked.get_json()["room"]
        self.assertEqual(member["id"], "room-101")
        self.assertEqual(member["status"], "occupied", member)
        primary = self.client.get("/hotel/api/rooms/room-103").get_json()["room"]
        self.assertEqual(primary["status"], "reserved", primary)
        self.assertTrue(member.get("stay", {}).get("checkedInAt"))
        self.assertFalse(primary.get("stay", {}).get("checkedInAt"))

        primary_in = self.client.put(
            "/hotel/api/rooms/room-103",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Manoj",
                    "lastName": "Vijayan",
                    "mobile": "9876500101",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                },
            },
        )
        self.assertEqual(primary_in.status_code, 200, primary_in.get_data(as_text=True))
        primary = primary_in.get_json()["room"]
        self.assertEqual(primary["status"], "occupied")
        member = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertEqual(member["status"], "occupied")

        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertEqual(closed.get_json()["room"]["status"], "dirty")
        still_primary = self.client.get("/hotel/api/rooms/room-103").get_json()["room"]
        self.assertEqual(still_primary["status"], "occupied")
        self.assertTrue(still_primary.get("isMergePrimary") or not still_primary.get("mergeGroupId"))

    def test_merged_checkin_uses_submitted_room_rates(self):
        """Suite primary + Deluxe member bill the typed stay prices, not settings tariffs."""
        check_in, check_out = self._stay_window(nights=1)
        merged = self.client.put(
            "/hotel/api/rooms/room-306",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-306",
                "toRoomId": "room-307",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        checked = self.client.put(
            "/hotel/api/rooms/room-307",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000306",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 7500,
                    "mergeRoomRates": [
                        {
                            "roomId": "room-307",
                            "number": "307",
                            "roomType": "premium_suite_tub",
                            "ratePlan": "EP",
                            "roomRate": 7500,
                            "isPrimary": True,
                        },
                        {
                            "roomId": "room-306",
                            "number": "306",
                            "roomType": "premium_deluxe_balcony",
                            "ratePlan": "EP",
                            "roomRate": 4500,
                            "isPrimary": False,
                        },
                    ],
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        primary = self.client.get("/hotel/api/rooms/room-307").get_json()["room"]
        folio = primary["stay"].get("folioCharges") or []
        rate_lines = [f for f in folio if f.get("source") == "merged_room_rate"]
        self.assertEqual(len(rate_lines), 1, folio)
        self.assertIn("306", rate_lines[0].get("label") or "")
        self.assertEqual(float(rate_lines[0].get("amount") or 0), 4500.0)
        rates = primary["stay"].get("mergeRoomRates") or []
        by_num = {str(r.get("number") or ""): r for r in rates}
        self.assertEqual(float(by_num["307"]["roomRate"]), 7500.0)
        self.assertEqual(float(by_num["306"]["roomRate"]), 4500.0)
        # ₹7500 + ₹4500 = ₹12,000 (tax-inclusive)
        self.assertAlmostEqual(
            float(primary["stay"].get("estimatedTotal") or 0), 12000.0, places=2
        )

    def test_merged_checkin_keeps_manual_member_rate(self):
        """Typed mergeRoomRates are billed as entered, even if they match the primary."""
        check_in, check_out = self._stay_window(nights=1)
        merged = self.client.put(
            "/hotel/api/rooms/room-306",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-306",
                "toRoomId": "room-307",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        checked = self.client.put(
            "/hotel/api/rooms/room-307",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Dev",
                    "lastName": "Iyer",
                    "mobile": "9000000307",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 7500,
                    "mergeRoomRates": [
                        {
                            "roomId": "room-307",
                            "number": "307",
                            "roomRate": 7500,
                            "isPrimary": True,
                        },
                        {
                            "roomId": "room-306",
                            "number": "306",
                            "roomRate": 7500,
                            "isPrimary": False,
                        },
                    ],
                    "advancePaid": 0,
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        primary = self.client.get("/hotel/api/rooms/room-307").get_json()["room"]
        rate_lines = [
            f
            for f in (primary["stay"].get("folioCharges") or [])
            if f.get("source") == "merged_room_rate"
        ]
        self.assertEqual(len(rate_lines), 1, primary["stay"].get("folioCharges"))
        self.assertEqual(float(rate_lines[0].get("amount") or 0), 7500.0)
        by_num = {
            str(r.get("number") or ""): r
            for r in (primary["stay"].get("mergeRoomRates") or [])
        }
        self.assertEqual(float(by_num["306"]["roomRate"]), 7500.0)
        self.assertAlmostEqual(
            float(primary["stay"].get("estimatedTotal") or 0), 15000.0, places=2
        )

    def test_merge_allows_any_rooms_without_stay(self):
        """Vacant / status-only rooms can join a billing merge group."""
        merged = self.client.put(
            "/hotel/api/rooms/room-105",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-105",
                "toRoomId": "room-106",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        body = merged.get_json()
        primary = body["primaryRoom"]
        member = body["memberRoom"]
        self.assertEqual(primary["id"], "room-106")
        self.assertEqual(member["id"], "room-105")
        self.assertTrue(primary["isMergePrimary"])
        self.assertTrue(member["isMergeMember"])
        # Vacant rooms stay vacant until a guest is checked in on the bill.
        self.assertEqual(primary["status"], "vacant")
        self.assertEqual(member["status"], "vacant")
        self.assertEqual(member["stay"]["billingRoomId"], "room-106")
        self.assertEqual(member["stay"]["mergeRole"], "member")
        self.assertEqual(primary["stay"]["mergeRole"], "primary")
        self.assertTrue(primary.get("mergeGroupId"))
        self.assertEqual(primary["mergeGroupId"], member["mergeGroupId"])

    def test_merge_board_tile_exposes_guest_for_hover(self):
        """Merged primary board payload carries guest so the hover card can render."""
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Neha",
                    "lastName": "Iyer",
                    "mobile": "9000000077",
                    "checkInDate": "2026-08-01",
                    "nights": 2,
                    "roomRate": 2800,
                    "adults": 2,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-101",
                "toRoomId": "room-106",
            },
        )
        layout = self.client.get("/hotel/api/rooms").get_json()
        rooms = layout.get("rooms") or []
        primary = next((r for r in rooms if r.get("id") == "room-106"), None)
        self.assertIsNotNone(primary)
        self.assertTrue(primary.get("isMergePrimary"))
        self.assertEqual(primary.get("status"), "vacant")
        member = next((r for r in rooms if r.get("id") == "room-101"), None)
        self.assertIsNotNone(member)
        self.assertEqual(member.get("status"), "occupied")
        stay = primary.get("stay") or {}
        self.assertIn("Neha", stay.get("guestName") or stay.get("firstName") or "")
        self.assertEqual(stay.get("mobile"), "9000000077")
        self.assertTrue(stay.get("checkInDate"))

    def test_unmerge_splits_folio_onto_member(self):
        self._checkin_with_charges("room-101", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "merge_rooms", "fromRoomId": "room-102", "toRoomId": "room-101"},
        )
        before = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        folio_count = len(before["stay"]["folioCharges"])
        self.assertGreater(folio_count, 0)
        self.assertTrue(
            any(
                str(f.get("sourceRoomId") or "") == "room-102"
                for f in before["stay"]["folioCharges"]
            )
        )

        unmerged = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "unmerge_rooms", "scope": "one"},
        )
        self.assertEqual(unmerged.status_code, 200, unmerged.get_data(as_text=True))
        member = unmerged.get_json()["room"]
        self.assertFalse(member.get("isMergeMember"))
        self.assertFalse(member.get("mergeGroupId"))
        self.assertEqual(member["stay"].get("billingRoomId") or "", "")
        self.assertTrue(member["stay"].get("independentBilling"))
        self.assertGreater(float(member["stay"].get("roomRate") or 0), 0)
        self.assertGreater(float(member["stay"].get("estimatedTotal") or 0), 0)

        primary = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertFalse(
            any(
                str(f.get("sourceRoomId") or "") == "room-102"
                for f in primary["stay"].get("folioCharges") or []
            )
        )
        self.assertLess(len(primary["stay"]["folioCharges"]), folio_count)
        self.assertTrue(primary["stay"].get("independentBilling"))
        self.assertFalse(primary.get("mergeGroupId"))
        for stay in (member["stay"], primary["stay"]):
            merge_folio = [
                f
                for f in stay.get("folioCharges") or []
                if str(f.get("source") or "") in ("room_merge", "merged_room_rate")
            ]
            self.assertEqual(merge_folio, [])

    def test_independent_stay_strips_stale_merge_folio(self):
        """Unmerged rooms must not keep other rooms' absorb lines on Estimated Charges."""
        check_in, check_out = self._stay_window(nights=1)
        stay = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Asha",
                "lastName": "Nair",
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "nights": 1,
                "roomRate": 5000,
                "independentBilling": True,
                "folioCharges": [
                    {
                        "kind": "other",
                        "label": "Room 102 — stay charges",
                        "amount": 5000,
                        "source": "room_merge",
                        "sourceRoomId": "room-102",
                        "sourceRoomNumber": "102",
                    },
                    {
                        "kind": "other",
                        "label": "Room 103 — stay charges",
                        "amount": 5000,
                        "source": "room_merge",
                        "sourceRoomId": "room-103",
                        "sourceRoomNumber": "103",
                    },
                    {
                        "kind": "restaurant_room_transfer",
                        "label": "Dinner",
                        "amount": 800,
                        "source": "pos",
                    },
                ],
            }
        )
        sources = [f.get("source") for f in stay.get("folioCharges") or []]
        self.assertNotIn("room_merge", sources)
        self.assertNotIn("merged_room_rate", sources)
        self.assertEqual(len(stay["folioCharges"]), 1)
        self.assertEqual(stay["folioCharges"][0]["kind"], "restaurant_room_transfer")
        self.assertLess(float(stay["estimatedTotal"]), 10000)
        self.assertGreater(float(stay["estimatedTotal"]), 5000)

    def test_folio_keeps_each_pos_invoice_as_own_line(self):
        """Each restaurant/bar transfer must stay a distinct folio line with its order number."""
        check_in, check_out = self._stay_window(nights=1)
        stay = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Asha",
                "lastName": "Nair",
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "nights": 1,
                "roomRate": 2000,
                "folioCharges": [
                    {
                        "id": "fc1",
                        "kind": "restaurant_room_transfer",
                        "label": "Restaurant Room Transfer · ORD-1",
                        "amount": 150.48,
                        "source": "pos",
                        "invoiceId": "11",
                    },
                    {
                        "id": "fc2",
                        "kind": "restaurant_room_transfer",
                        "label": "Restaurant Room Transfer · ORD-2",
                        "amount": 80,
                        "source": "pos",
                        "invoiceId": "12",
                    },
                    {
                        "id": "fc3",
                        "kind": "bar_room_transfer",
                        "label": "Bar Room Transfer",
                        "amount": 40,
                        "source": "pos",
                        "invoiceId": "13",
                        "orderNo": "ORD-3",
                    },
                ],
            }
        )
        folio = stay["folioCharges"]
        self.assertEqual(len(folio), 3)
        self.assertEqual(folio[0]["orderNo"], "ORD-1")
        self.assertEqual(folio[1]["orderNo"], "ORD-2")
        self.assertEqual(folio[2]["orderNo"], "ORD-3")
        self.assertEqual(folio[0]["label"], "Restaurant Room Transfer · ORD-1")
        self.assertEqual(folio[1]["label"], "Restaurant Room Transfer · ORD-2")
        self.assertEqual(folio[2]["amount"], 40)

    def test_unmerge_primary_scope_one_shows_former_member(self):
        """Unmerge Room on the primary must not leave the member hidden on the board."""
        self._checkin_with_charges("room-106", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Orphan",
                    "lastName": "Member",
                    "mobile": "9000000101",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-101",
                "toRoomId": "room-106",
            },
        )
        layout_before = self.client.get("/hotel/api/rooms").get_json()
        member_before = next(
            r for r in layout_before["rooms"] if r.get("id") == "room-101"
        )
        self.assertTrue(member_before.get("isMergeMember"))

        unmerged = self.client.put(
            "/hotel/api/rooms/room-106",
            json={"action": "unmerge_rooms", "scope": "one"},
        )
        self.assertEqual(unmerged.status_code, 200, unmerged.get_data(as_text=True))

        layout = self.client.get("/hotel/api/rooms").get_json()
        by_id = {r["id"]: r for r in layout["rooms"]}
        primary = by_id["room-106"]
        member = by_id["room-101"]
        self.assertFalse(primary.get("isMergePrimary"))
        self.assertFalse(primary.get("mergeGroupId"))
        self.assertFalse(member.get("isMergeMember"))
        self.assertFalse(member.get("mergeGroupId"))
        self.assertEqual((member.get("stay") or {}).get("mergeRole") or "", "")
        self.assertEqual((member.get("stay") or {}).get("billingRoomId") or "", "")

    def test_heal_orphan_merge_member_clears_hidden_room(self):
        """Layout heal recovers members left behind after a bad primary unmerge."""
        conn = db_mod.get_db()
        try:
            layout = db_mod.get_hotel_rooms_layout(conn)
            rooms = layout["rooms"]
            member = next(r for r in rooms if r["id"] == "room-101")
            member["mergeGroupId"] = "mg-orphan-101"
            member["mergePrimary"] = False
            member["status"] = "vacant"
            member["stay"] = db_mod._normalize_hotel_room_stay(
                {
                    "mergeRole": "member",
                    "billingRoomId": "room-106",
                    "firstName": "",
                    "lastName": "",
                }
            )
            db_mod.save_hotel_rooms_layout(conn, layout["floors"], rooms)
        finally:
            conn.close()

        healed = self.client.get("/hotel/api/rooms").get_json()
        room_101 = next(r for r in healed["rooms"] if r["id"] == "room-101")
        self.assertFalse(room_101.get("isMergeMember"))
        self.assertFalse(room_101.get("mergeGroupId"))
        stay = room_101.get("stay") or {}
        self.assertEqual(stay.get("mergeRole") or "", "")
        self.assertEqual(stay.get("billingRoomId") or "", "")

    def test_transfer_member_and_primary_remap_merge(self):
        self._checkin_with_charges("room-101", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "merge_rooms", "fromRoomId": "room-102", "toRoomId": "room-101"},
        )

        # Transfer member 102 → vacant 103; keep billing on 101.
        moved_member = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "transfer", "toRoomId": "room-103"},
        )
        self.assertEqual(moved_member.status_code, 200, moved_member.get_data(as_text=True))
        to_member = moved_member.get_json()["toRoom"]
        self.assertEqual(to_member["id"], "room-103")
        self.assertTrue(to_member["isMergeMember"])
        self.assertEqual(to_member["stay"]["billingRoomId"], "room-101")
        old_member = moved_member.get_json()["fromRoom"]
        self.assertEqual(old_member["status"], "dirty")
        self.assertFalse(old_member.get("mergeGroupId"))

        # Transfer primary 101 → vacant 104; remap member billingRoomId.
        moved_primary = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "transfer", "toRoomId": "room-104"},
        )
        self.assertEqual(moved_primary.status_code, 200, moved_primary.get_data(as_text=True))
        new_primary = moved_primary.get_json()["toRoom"]
        self.assertTrue(new_primary["isMergePrimary"])
        member = self.client.get("/hotel/api/rooms/room-103").get_json()["room"]
        self.assertEqual(member["stay"]["billingRoomId"], "room-104")

    def test_set_merge_primary_and_checkout_group(self):
        self._checkin_with_charges("room-101", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "merge_rooms", "fromRoomId": "room-102", "toRoomId": "room-101"},
        )
        swapped = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "set_merge_primary"},
        )
        self.assertEqual(swapped.status_code, 200, swapped.get_data(as_text=True))
        new_primary = swapped.get_json()["room"]
        self.assertEqual(new_primary["id"], "room-102")
        self.assertTrue(new_primary["isMergePrimary"])
        self.assertGreater(len(new_primary["stay"]["folioCharges"]), 0)
        old = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertTrue(old["isMergeMember"])
        self.assertEqual(old["stay"]["billingRoomId"], "room-102")

        closed = self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertEqual(closed.get_json()["room"]["status"], "dirty")
        other = self.client.get("/hotel/api/rooms/room-101").get_json()["room"]
        self.assertEqual(other["status"], "occupied")
        self.assertIn("stay", other)
        self.assertFalse(other.get("isMergeMember"))

    def test_checkout_group_clears_all_merged_rooms(self):
        self._checkin_with_charges("room-101", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-103",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Ravi",
                    "lastName": "Menon",
                    "mobile": "9000000012",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 1800,
                    "advancePaid": 0,
                },
            },
        )
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={"action": "merge_rooms", "fromRoomId": "room-102", "toRoomId": "room-101"},
        )
        self.client.put(
            "/hotel/api/rooms/room-103",
            json={"action": "merge_rooms", "fromRoomId": "room-103", "toRoomId": "room-101"},
        )
        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout_group"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        body = closed.get_json()
        self.assertTrue(body["ok"])
        ids = set(body.get("checkedOutRoomIds") or [])
        self.assertEqual(ids, {"room-101", "room-102", "room-103"})
        for rid in ("room-101", "room-102", "room-103"):
            room = self.client.get("/hotel/api/rooms/" + rid).get_json()["room"]
            self.assertEqual(room["status"], "dirty", rid)
            self.assertFalse(room.get("isMergePrimary"))
            self.assertFalse(room.get("isMergeMember"))
            self.assertFalse(room.get("mergeGroupId"))
            self.assertFalse(room.get("stay"), rid)

    def test_merged_invoice_snapshots_both_rooms_and_survives_checkout(self):
        """Merged bill prints both room numbers; checkout of primary leaves member occupied."""
        self._checkin_with_charges("room-101", advance=0)
        self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Asha",
                    "lastName": "Nair",
                    "mobile": "9000000011",
                    "checkInDate": "2026-07-29",
                    "nights": 1,
                    "roomRate": 2000,
                    "advancePaid": 0,
                },
            },
        )
        merged = self.client.put(
            "/hotel/api/rooms/room-102",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-102",
                "toRoomId": "room-101",
            },
        )
        self.assertEqual(merged.status_code, 200, merged.get_data(as_text=True))
        primary = merged.get_json()["primaryRoom"]
        self.assertEqual(primary.get("mergeLabel"), "101 + 102")
        self.assertTrue(primary.get("isMergePrimary"))

        gen = self.client.put(
            "/hotel/api/rooms/room-101",
            json={
                "action": "generate_invoice",
                "payment": {"amount": 1, "method": "cash"},
            },
        )
        self.assertEqual(gen.status_code, 200, gen.get_data(as_text=True))
        stay = gen.get_json()["room"]["stay"]
        inv_no = stay["invoiceNumber"]
        self.assertEqual(stay.get("mergeRoomNumbers"), ["101", "102"])
        self.assertEqual(stay.get("mergeRoomLabel"), "101 + 102")

        # Settle remaining balance so checkout is allowed in UI flows.
        balance = float(stay.get("balanceAmount") or 0)
        if balance > 0:
            paid = self.client.put(
                "/hotel/api/rooms/room-101",
                json={
                    "action": "record_payment",
                    "amount": balance,
                    "method": "cash",
                },
            )
            self.assertEqual(paid.status_code, 200, paid.get_data(as_text=True))

        closed = self.client.put(
            "/hotel/api/rooms/room-101",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        primary_after = closed.get_json()["room"]
        self.assertEqual(primary_after["status"], "dirty")
        self.assertFalse(primary_after.get("mergeGroupId"))
        self.assertFalse(primary_after.get("isMergePrimary"))
        self.assertNotIn("stay", primary_after)

        member_after = self.client.get("/hotel/api/rooms/room-102").get_json()["room"]
        self.assertEqual(member_after["status"], "occupied")
        self.assertTrue(member_after.get("isMergePrimary") or not member_after.get("isMergeMember"))
        self.assertIn("stay", member_after)

        api = self.client.get(f"/hotel/invoice-ledger/api/{inv_no}")
        self.assertEqual(api.status_code, 200, api.get_data(as_text=True))
        body = api.get_json()
        self.assertTrue(body["ok"])
        ledger_room = body["room"]
        ledger_stay = ledger_room["stay"]
        self.assertCountEqual(ledger_stay.get("mergeRoomNumbers") or [], ["101", "102"])
        self.assertCountEqual(
            [p.strip() for p in str(ledger_stay.get("mergeRoomLabel") or "").split("+") if p.strip()],
            ["101", "102"],
        )
        self.assertCountEqual(
            [p.strip() for p in str(body["invoice"]["room_number"] or "").split("+") if p.strip()],
            ["101", "102"],
        )
        self.assertIn("102", ledger_room.get("mergeRoomLabel") or "")

    def test_normalize_nightly_rates_sum_and_fill(self):
        stay = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Nightly",
                "checkInDate": "2026-08-15",
                "checkOutDate": "2026-08-17",
                "nights": 2,
                "roomRate": 5000,
                "ratePlan": "EP",
                "nightlyRates": [
                    {"date": "2026-08-15", "roomRate": 5000, "ratePlan": "AP"},
                    {"date": "2026-08-16", "roomRate": 4500, "ratePlan": "CP"},
                ],
            }
        )
        self.assertEqual(stay["totalRate"], 9500.0)
        self.assertEqual(stay["roomRate"], 5000.0)
        self.assertEqual(stay["ratePlan"], "AP")
        self.assertEqual(len(stay["nightlyRates"]), 2)
        self.assertEqual(stay["nightlyRates"][1]["ratePlan"], "CP")

        filled = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Fill",
                "checkInDate": "2026-08-15",
                "nights": 3,
                "roomRate": 4000,
                "ratePlan": "EP",
                "nightlyRates": [
                    {"date": "2026-08-15", "roomRate": 5000, "ratePlan": "AP"},
                    {"date": "2026-08-17", "roomRate": 4500, "ratePlan": "CP"},
                ],
            }
        )
        self.assertEqual(
            [row["roomRate"] for row in filled["nightlyRates"]],
            [5000.0, 5000.0, 4500.0],
        )
        self.assertEqual(filled["totalRate"], 14500.0)
        self.assertEqual(
            [row["ratePlan"] for row in filled["nightlyRates"]],
            ["AP", "AP", "CP"],
        )

    def test_normalize_legacy_flat_rate_without_nightly(self):
        stay = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Legacy",
                "checkInDate": "2026-08-15",
                "checkOutDate": "2026-08-17",
                "nights": 2,
                "roomRate": 5000,
                "ratePlan": "EP",
            }
        )
        self.assertEqual(stay.get("nightlyRates"), [])
        self.assertEqual(stay["totalRate"], 10000.0)
        self.assertEqual(
            db_mod._hotel_stay_room_charges_amount(stay),
            10000.0,
        )

    def test_normalize_heals_id_document_path_from_filename(self):
        stay = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Lukas",
                "idType": "Passport",
                "idDocumentName": "f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.webp",
                "idDocumentPath": "",
                "idDocumentMime": "image/webp",
            }
        )
        self.assertEqual(
            stay["idDocumentPath"],
            "/hotel/api/id-documents/view/f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.webp/raw",
        )
        extras = db_mod._normalize_hotel_room_stay(
            {
                "firstName": "Host",
                "additionalGuests": [
                    {
                        "name": "Extra",
                        "idType": "Aadhaar",
                        "idDocumentName": "9bd51354-c325-456a-919c-9d9910c52808.webp",
                    }
                ],
            }
        )
        self.assertEqual(
            extras["additionalGuests"][0]["idDocumentPath"],
            "/hotel/api/id-documents/view/9bd51354-c325-456a-919c-9d9910c52808.webp/raw",
        )

    def test_same_reservation_id_auto_merges_reserved_rooms(self):
        """Two reserved rooms with the same reservation id join one merge group."""
        stay = {
            "guestName": "Rid Guest",
            "mobile": "9000012345",
            "reservationId": "AT-RID-1001",
        }
        payload = {
            "action": "reserve",
            "checkInDate": "2026-11-10",
            "checkOutDate": "2026-11-12",
            "stay": stay,
        }
        first = self.client.put("/hotel/api/rooms/room-201", json=payload)
        second = self.client.put("/hotel/api/rooms/room-202", json=payload)
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(second.status_code, 200, second.get_data(as_text=True))

        board = self.client.get("/hotel/api/rooms")
        self.assertEqual(board.status_code, 200)
        rooms = {r["id"]: r for r in board.get_json().get("rooms") or []}
        self.assertTrue(rooms["room-201"].get("mergeGroupId"))
        self.assertEqual(
            rooms["room-201"].get("mergeGroupId"),
            rooms["room-202"].get("mergeGroupId"),
        )
        self.assertTrue(
            rooms["room-201"].get("isMergePrimary")
            or rooms["room-202"].get("isMergePrimary")
        )
        self.assertEqual(rooms["room-201"]["status"], "reserved")
        self.assertEqual(rooms["room-202"]["status"], "reserved")

    def test_unmerge_same_reservation_does_not_remerge_on_get(self):
        stay = {
            "guestName": "Rid Guest",
            "mobile": "9000012345",
            "reservationId": "AT-RID-UNMERGE-1",
        }
        payload = {
            "action": "reserve",
            "checkInDate": "2026-11-10",
            "checkOutDate": "2026-11-12",
            "stay": stay,
        }
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-201", json=payload).status_code, 200
        )
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-202", json=payload).status_code, 200
        )
        board = self.client.get("/hotel/api/rooms")
        self.assertEqual(board.status_code, 200)
        rooms = {r["id"]: r for r in board.get_json().get("rooms") or []}
        self.assertTrue(rooms["room-201"].get("mergeGroupId"))
        member_id = (
            "room-202" if rooms["room-202"].get("isMergeMember") else "room-201"
        )
        unmerged = self.client.put(
            f"/hotel/api/rooms/{member_id}",
            json={"action": "unmerge_rooms", "scope": "one"},
        )
        self.assertEqual(unmerged.status_code, 200, unmerged.get_data(as_text=True))

        again = self.client.get("/hotel/api/rooms")
        self.assertEqual(again.status_code, 200)
        rooms = {r["id"]: r for r in again.get_json().get("rooms") or []}
        self.assertFalse(rooms["room-201"].get("mergeGroupId"))
        self.assertFalse(rooms["room-202"].get("mergeGroupId"))
        self.assertFalse(rooms["room-201"].get("isMergeMember"))
        self.assertFalse(rooms["room-202"].get("isMergeMember"))
        self.assertTrue(rooms["room-201"]["stay"].get("independentBilling"))
        self.assertTrue(rooms["room-202"]["stay"].get("independentBilling"))

        rematch = self.client.put(
            "/hotel/api/rooms/room-201",
            json={
                "action": "merge_rooms",
                "fromRoomId": "room-201",
                "toRoomId": "room-202",
            },
        )
        self.assertEqual(rematch.status_code, 200, rematch.get_data(as_text=True))
        rooms = {
            r["id"]: r
            for r in self.client.get("/hotel/api/rooms").get_json().get("rooms") or []
        }
        self.assertTrue(rooms["room-201"].get("mergeGroupId"))
        self.assertEqual(
            rooms["room-201"].get("mergeGroupId"),
            rooms["room-202"].get("mergeGroupId"),
        )
        self.assertFalse(rooms["room-201"]["stay"].get("independentBilling"))
        self.assertFalse(rooms["room-202"]["stay"].get("independentBilling"))

    def test_same_reservation_checkin_occupies_only_that_room(self):
        stay = {
            "guestName": "Stagger Guest",
            "firstName": "Stagger",
            "lastName": "Guest",
            "mobile": "9000012346",
            "reservationId": "AT-RID-1002",
        }
        check_in, check_out = self._stay_window(nights=1)
        payload = {
            "action": "reserve",
            "checkInDate": check_in,
            "checkOutDate": check_out,
            "stay": stay,
        }
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-201", json=payload).status_code, 200
        )
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-202", json=payload).status_code, 200
        )
        checked = self.client.put(
            "/hotel/api/rooms/room-201",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Stagger",
                    "lastName": "Guest",
                    "mobile": "9000012346",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                    "reservationId": "AT-RID-1002",
                },
            },
        )
        self.assertEqual(checked.status_code, 200, checked.get_data(as_text=True))
        self.assertEqual(checked.get_json()["room"]["status"], "occupied")
        peer = self.client.get("/hotel/api/rooms/room-202").get_json()["room"]
        self.assertEqual(peer["status"], "reserved")

    def test_same_reservation_checkout_clears_this_room_only(self):
        stay = {
            "guestName": "Checkout Group",
            "firstName": "Checkout",
            "lastName": "Group",
            "mobile": "9000012347",
            "reservationId": "AT-RID-1003",
        }
        check_in, check_out = self._stay_window(nights=1)
        payload = {
            "action": "reserve",
            "checkInDate": check_in,
            "checkOutDate": check_out,
            "stay": stay,
        }
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-201", json=payload).status_code, 200
        )
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-202", json=payload).status_code, 200
        )
        self.client.put(
            "/hotel/api/rooms/room-201",
            json={
                "action": "checkin",
                "stay": {
                    "firstName": "Checkout",
                    "lastName": "Group",
                    "mobile": "9000012347",
                    "checkInDate": check_in,
                    "checkOutDate": check_out,
                    "nights": 1,
                    "roomRate": 4500,
                    "reservationId": "AT-RID-1003",
                },
            },
        )
        closed = self.client.put(
            "/hotel/api/rooms/room-201",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertEqual(closed.get_json()["room"]["status"], "dirty")
        ids = closed.get_json().get("checkedOutRoomIds") or []
        self.assertEqual(ids, ["room-201"])
        peer = self.client.get("/hotel/api/rooms/room-202").get_json()["room"]
        self.assertEqual(peer["status"], "reserved")
        self.assertTrue(peer.get("stay"))

    def test_same_reservation_checkout_leaves_occupied_peers(self):
        stay = {
            "guestName": "Both In",
            "firstName": "Both",
            "lastName": "In",
            "mobile": "9000012348",
            "reservationId": "AT-RID-1004",
        }
        check_in, check_out = self._stay_window(nights=1)
        payload = {
            "action": "reserve",
            "checkInDate": check_in,
            "checkOutDate": check_out,
            "stay": stay,
        }
        self.client.put("/hotel/api/rooms/room-201", json=payload)
        self.client.put("/hotel/api/rooms/room-202", json=payload)
        for room_id in ("room-201", "room-202"):
            self.client.put(
                f"/hotel/api/rooms/{room_id}",
                json={
                    "action": "checkin",
                    "stay": {
                        "firstName": "Both",
                        "lastName": "In",
                        "mobile": "9000012348",
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "nights": 1,
                        "roomRate": 4500,
                        "reservationId": "AT-RID-1004",
                    },
                },
            )
        closed = self.client.put(
            "/hotel/api/rooms/room-201",
            json={"action": "checkout"},
        )
        self.assertEqual(closed.status_code, 200, closed.get_data(as_text=True))
        self.assertEqual(closed.get_json()["room"]["status"], "dirty")
        peer = self.client.get("/hotel/api/rooms/room-202").get_json()["room"]
        self.assertEqual(peer["status"], "occupied")
        self.assertTrue(peer.get("stay"))

    def test_local_bk_booking_number_does_not_auto_merge(self):
        stay = {
            "guestName": "Local Bk",
            "mobile": "9000012349",
            "bookingNumber": "BK20260816123456",
            "reservationBookingId": "BK20260816123456",
        }
        payload = {
            "action": "reserve",
            "checkInDate": "2026-11-20",
            "checkOutDate": "2026-11-22",
            "stay": stay,
        }
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-201", json=payload).status_code, 200
        )
        self.assertEqual(
            self.client.put("/hotel/api/rooms/room-202", json=payload).status_code, 200
        )
        board = self.client.get("/hotel/api/rooms")
        rooms = {r["id"]: r for r in board.get_json().get("rooms") or []}
        self.assertFalse(rooms["room-201"].get("mergeGroupId"))
        self.assertFalse(rooms["room-202"].get("mergeGroupId"))


if __name__ == "__main__":
    unittest.main()
