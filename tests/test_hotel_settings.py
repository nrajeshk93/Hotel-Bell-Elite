"""Hotel Settings — independent from Restaurant/Bar POS settings."""

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod


class HotelSettingsTests(unittest.TestCase):
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

    def test_settings_hub_includes_hotel_card(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Hotel Settings", html)
        self.assertIn("/hotel/settings", html)
        self.assertIn("Restaurant Settings", html)
        self.assertIn("Bar Settings", html)

    def test_hotel_settings_page_and_api_round_trip(self):
        page = self.client.get("/hotel/settings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="hotel-settings-page"', html)
        self.assertIn("data-hotel-settings", html)
        self.assertIn('data-hotel-api-base="/hotel"', html)
        self.assertIn("Floor Layout", html)
        self.assertIn('data-section="rooms"', html)
        self.assertIn('data-section="tariff"', html)
        self.assertIn("Premium Room", html)
        self.assertIn("Deluxe with Balcony", html)
        self.assertIn("Suite Room", html)
        self.assertIn("Extra Mattress", html)
        self.assertIn("Airport Pickup", html)
        self.assertNotIn('data-pos-outlet=', html)
        self.assertNotIn("pos_settings.js", html)

        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        payload = get_resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("taxRates", payload)
        self.assertEqual(payload["taxRates"]["cgst_pct"], 2.5)
        self.assertIn("tariffRates", payload)
        self.assertEqual(payload["tariffRates"]["premium_without_balcony"], 3500.0)
        self.assertEqual(payload["tariffRates"]["extra_mattress"], 1000.0)
        self.assertEqual(payload["tariffRates"]["airport_pickup"], 1500.0)

        put_resp = self.client.put(
            "/hotel/api/settings",
            json={
                "settings": {
                    "panels": {
                        "taxes": {
                            "values": {
                                "cgst_pct": {"kind": "text", "value": "3"},
                                "ugst_pct": {"kind": "text", "value": "3"},
                            }
                        },
                        "tariff": {
                            "values": {
                                "rate_premium_without_balcony": {
                                    "kind": "text",
                                    "value": "4000",
                                },
                                "rate_extra_mattress": {"kind": "text", "value": "1200"},
                                "rate_airport_pickup": {"kind": "text", "value": "2000"},
                            }
                        },
                        "invoice": {
                            "values": {
                                "invoice_prefix": {"kind": "text", "value": "HBE/RM"},
                                "invoice_footer": {"kind": "textarea", "value": "Thank you"},
                            }
                        },
                    }
                }
            },
        )
        self.assertEqual(put_resp.status_code, 200)
        saved = put_resp.get_json()
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["taxRates"]["cgst_pct"], 3.0)
        self.assertEqual(saved["taxRates"]["ugst_pct"], 3.0)
        self.assertEqual(saved["tariffRates"]["premium_without_balcony"], 4000.0)
        self.assertEqual(saved["tariffRates"]["extra_mattress"], 1200.0)
        self.assertEqual(saved["tariffRates"]["airport_pickup"], 2000.0)

        # Hotel settings must not write POS outlet settings.
        conn = db_mod.get_db()
        try:
            hotel = db_mod.get_hotel_settings(conn)
            self.assertEqual(
                hotel["panels"]["taxes"]["values"]["cgst_pct"]["value"], "3"
            )
            pos = db_mod.get_pos_restaurant_settings(conn, "restaurant")
            self.assertNotEqual(
                (pos.get("panels") or {}).get("taxes"),
                hotel.get("panels", {}).get("taxes"),
            )
        finally:
            conn.close()

    def test_hotel_tax_rates_drive_stay_estimate(self):
        conn = db_mod.get_db()
        try:
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "taxes": {
                            "values": {
                                "cgst_pct": {"value": "4"},
                                "ugst_pct": {"value": "4"},
                            }
                        }
                    }
                },
            )
            rates = db_mod.get_hotel_tax_rates(conn)
            self.assertEqual(rates["cgst_pct"], 4.0)
            self.assertAlmostEqual(rates["cgst"], 0.04)
            stay = db_mod._normalize_hotel_room_stay(
                {
                    "firstName": "Test",
                    "nights": 1,
                    "roomRate": 1000,
                    "advancePaid": 0,
                },
                tax_rates=rates,
            )
            # roomRate 1000 is tax-inclusive (CGST/UGST extracted, not added)
            self.assertEqual(stay["estimatedTotal"], 1000.0)
            conn.commit()
        finally:
            conn.close()

    def test_hotel_tariff_rates_defaults_and_overrides(self):
        conn = db_mod.get_db()
        try:
            defaults = db_mod.get_hotel_tariff_rates(conn)
            self.assertEqual(defaults["premium_without_balcony"], 3500.0)
            self.assertEqual(defaults["premium_deluxe_balcony"], 4500.0)
            self.assertEqual(defaults["premium_suite_tub"], 7500.0)
            self.assertEqual(defaults["extra_mattress"], 1000.0)
            self.assertEqual(defaults["early_checkin"], 500.0)
            self.assertEqual(defaults["late_checkout"], 500.0)
            self.assertEqual(defaults["airport_pickup"], 1500.0)

            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "tariff": {
                            "values": {
                                "rate_premium_suite_tub": {"value": "8000"},
                                "rate_late_checkout": {"value": "750"},
                            }
                        }
                    }
                },
            )
            rates = db_mod.get_hotel_tariff_rates(conn)
            self.assertEqual(rates["premium_suite_tub"], 8000.0)
            self.assertEqual(rates["late_checkout"], 750.0)
            # Unset keys keep defaults
            self.assertEqual(rates["early_checkin"], 500.0)
            conn.commit()
        finally:
            conn.close()

    def test_hotel_settings_independent_from_pos_settings_api(self):
        self.client.put(
            "/hotel/api/settings",
            json={
                "settings": {
                    "panels": {
                        "taxes": {
                            "values": {
                                "cgst_pct": {"value": "7"},
                                "ugst_pct": {"value": "7"},
                            }
                        }
                    }
                }
            },
        )
        pos = self.client.get("/point-of-sale/api/settings")
        self.assertEqual(pos.status_code, 200)
        pos_rates = pos.get_json()["taxRates"]
        # POS defaults remain 2.5 unless POS settings were changed.
        self.assertEqual(pos_rates["cgst_pct"], 2.5)

        hotel = self.client.get("/hotel/api/settings").get_json()
        self.assertEqual(hotel["taxRates"]["cgst_pct"], 7.0)

    def test_cannot_remove_occupied_room_via_layout_save(self):
        self.client.put(
            "/hotel/api/rooms",
            json={"roomId": "room-101", "status": "occupied"},
        )
        layout = self.client.get("/hotel/api/rooms").get_json()
        rooms = [r for r in layout["rooms"] if r["id"] != "room-101"]
        resp = self.client.put(
            "/hotel/api/rooms",
            json={"floors": layout["floors"], "rooms": rooms},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("occupied", (resp.get_json().get("error") or "").lower())


if __name__ == "__main__":
    unittest.main()
