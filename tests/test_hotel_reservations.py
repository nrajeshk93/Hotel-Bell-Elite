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
        self.assertNotIn("hres-pagination-pages", html)
        self.assertNotIn("hres-page-size", html)
        self.assertIn("hotel_reservations.js", html)
        self.assertIn("hres-sync-banner", html)
        self.assertIn("hres-date-range-trigger", html)
        self.assertIn("hres-date-from", html)
        self.assertIn("hres-date-to", html)
        self.assertIn("sales_date_range.js", html)

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
        self.assertIn("asia_tech_username", html)
        self.assertIn("asia_tech_hotel_id", html)
        self.assertIn("asia_tech_password", html)


if __name__ == "__main__":
    unittest.main()
