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

    def tearDown(self):
        self._get_user_patch.stop()
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
        self.assertIn("hbe-scroll-panel", html)
        self.assertIn("Assign Room", html)
        self.assertNotIn("hres-pagination-pages", html)
        self.assertNotIn("hres-page-size", html)
        self.assertIn("hotel_reservations.js", html)

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
            },
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        payload = resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reservation"]["guestName"], "Test Guest")
        booking_id = payload["reservation"]["id"]

        found = self.client.get(f"/hotel/api/reservations/{booking_id}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.get_json()["reservation"]["mobile"], "9998887776")

    def test_hotel_settings_page_has_asia_tech_section(self):
        page = self.client.get("/hotel/settings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('data-section="asia_tech"', html)
        self.assertIn("asia_tech_api_key", html)


if __name__ == "__main__":
    unittest.main()
