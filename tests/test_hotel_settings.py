"""Hotel Settings — independent from Restaurant/Bar POS settings."""

import inspect
import json
import os
import tempfile
import threading
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
        self.assertIn('data-settings-rev="taxes-v4"', html)
        self.assertIn('data-hotel-api-base="/hotel"', html)
        self.assertIn("Floor Layout", html)
        self.assertIn('data-section="rooms"', html)
        self.assertIn('data-section="tariff"', html)
        self.assertIn('data-hotel-set-key="cgst_pct_above"', html)
        self.assertIn("Room rent less than or equal to 7500", html)
        self.assertIn("Room rent greater than 7500", html)
        self.assertNotIn("tax_slab_threshold", html)
        self.assertIn("Premium Room", html)
        self.assertIn("Deluxe with Balcony", html)
        self.assertIn("Suite Room", html)
        self.assertIn("Extra Mattress", html)
        self.assertIn("Airport Pickup", html)
        self.assertIn("Printer pairing", html)
        self.assertIn('data-hotel-action="print-agent-pair"', html)
        self.assertIn('data-hotel-pairing-code', html)
        self.assertIn("hotel_settings.js", html)
        self.assertNotIn('data-pos-outlet=', html)
        self.assertNotIn("pos_settings.js", html)

        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        payload = get_resp.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("taxRates", payload)
        self.assertEqual(payload["taxRates"]["cgst_pct"], 2.5)
        self.assertEqual(payload["taxRates"]["ugst_pct"], 2.5)
        self.assertEqual(payload["taxRates"]["cgst_pct_above"], 9.0)
        self.assertEqual(payload["taxRates"]["ugst_pct_above"], 9.0)
        self.assertEqual(payload["taxRates"]["threshold"], 7500.0)
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
                                "cgst_pct_above": {"kind": "text", "value": "6"},
                                "ugst_pct_above": {"kind": "text", "value": "6"},
                                "tax_slab_threshold": {"kind": "text", "value": "7500"},
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
        self.assertEqual(saved["taxRates"]["cgst_pct_above"], 6.0)
        self.assertEqual(saved["taxRates"]["ugst_pct_above"], 6.0)
        self.assertEqual(saved["taxRates"]["threshold"], 7500.0)
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

    def test_hotel_tax_slab_by_room_tariff(self):
        conn = db_mod.get_db()
        try:
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "taxes": {
                            "values": {
                                "cgst_pct": {"value": "2.5"},
                                "ugst_pct": {"value": "2.5"},
                                "cgst_pct_above": {"value": "9"},
                                "ugst_pct_above": {"value": "9"},
                                "tax_slab_threshold": {"value": "7500"},
                            }
                        }
                    }
                },
            )
            rates = db_mod.get_hotel_tax_rates(conn)
            self.assertEqual(rates["threshold"], 7500.0)

            low = db_mod.hotel_tax_rates_for_tariff(rates, 7500)
            self.assertEqual(low["slab"], "standard")
            self.assertEqual(low["cgst_pct"], 2.5)
            self.assertEqual(low["ugst_pct"], 2.5)
            taxable_low, cgst_low, ugst_low, incl_low = db_mod._hotel_split_inclusive_tax(
                7500, low
            )
            self.assertEqual(incl_low, 7500.0)
            self.assertAlmostEqual(cgst_low + ugst_low, 7500.0 - taxable_low, places=2)
            # 2.5+2.5 inclusive → tax share is 5/105 of total
            self.assertAlmostEqual(cgst_low + ugst_low, round(7500 * 5 / 105, 2), places=1)

            high = db_mod.hotel_tax_rates_for_tariff(rates, 8000)
            self.assertEqual(high["slab"], "above")
            self.assertEqual(high["cgst_pct"], 9.0)
            self.assertEqual(high["ugst_pct"], 9.0)
            taxable_high, cgst_high, ugst_high, incl_high = db_mod._hotel_split_inclusive_tax(
                8000, high
            )
            self.assertEqual(incl_high, 8000.0)
            self.assertAlmostEqual(
                cgst_high + ugst_high, round(8000 * 18 / 118, 2), places=1
            )

            # Max nightly rate drives slab when nightlyRates are present.
            nightly = db_mod.hotel_tax_rates_for_tariff(
                rates,
                db_mod._hotel_stay_tariff_for_tax_slab(
                    {
                        "roomRate": 5000,
                        "nightlyRates": [
                            {"roomRate": 5000},
                            {"roomRate": 8000},
                        ],
                    }
                ),
            )
            self.assertEqual(nightly["slab"], "above")

            # Custom threshold override.
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "taxes": {
                            "values": {
                                "cgst_pct": {"value": "2.5"},
                                "ugst_pct": {"value": "2.5"},
                                "cgst_pct_above": {"value": "9"},
                                "ugst_pct_above": {"value": "9"},
                                "tax_slab_threshold": {"value": "5000"},
                            }
                        }
                    }
                },
            )
            rates2 = db_mod.get_hotel_tax_rates(conn)
            self.assertEqual(rates2["threshold"], 5000.0)
            mid = db_mod.hotel_tax_rates_for_tariff(rates2, 5500)
            self.assertEqual(mid["slab"], "above")
            edge = db_mod.hotel_tax_rates_for_tariff(rates2, 5000)
            self.assertEqual(edge["slab"], "standard")
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

    def test_hotel_invoice_prefix_drives_allocation(self):
        conn = db_mod.get_db()
        try:
            fy = db_mod.indian_fiscal_year_label()
            short_fy = db_mod.indian_fiscal_year_short_label(fy)

            # Default stem HBE → HBE/{fy}/00001
            first = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertEqual(first, f"HBE/{short_fy}/00001")

            # Custom stem
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "invoice": {
                            "values": {
                                "invoice_prefix": {"kind": "text", "value": "BELLA"},
                            }
                        }
                    }
                },
            )
            bella = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertEqual(bella, f"BELLA/{short_fy}/00002")

            # Full series including FY (trailing slash OK)
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "invoice": {
                            "values": {
                                "invoice_prefix": {
                                    "kind": "text",
                                    "value": f"HBE/{short_fy}/",
                                },
                            }
                        }
                    }
                },
            )
            series = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertEqual(series, f"HBE/{short_fy}/00003")
            series2 = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertEqual(series2, f"HBE/{short_fy}/00004")

            # Changing prefix does not rewrite prior numbers; format helper stays pure
            self.assertEqual(
                db_mod.format_hotel_room_invoice_number("HBE", short_fy, 1),
                f"HBE/{short_fy}/00001",
            )
            self.assertEqual(
                db_mod.format_hotel_room_invoice_number(f"HBE/{short_fy}/", short_fy, 9),
                f"HBE/{short_fy}/00009",
            )
            conn.commit()
        finally:
            conn.close()

    def test_hotel_invoice_prefix_embedded_fy_overrides_calendar_fy(self):
        """Prefix HBE/27-28/ must mint that series even when calendar FY is 26-27."""
        conn = db_mod.get_db()
        try:
            calendar_fy = db_mod.indian_fiscal_year_short_label()
            self.assertNotEqual(calendar_fy, "27-28")  # sanity for this assertion era
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "invoice": {
                            "values": {
                                "invoice_prefix": {
                                    "kind": "text",
                                    "value": "HBE/27-28/",
                                },
                            }
                        }
                    }
                },
            )
            self.assertEqual(db_mod.hotel_room_invoice_prefix(conn), "HBE/27-28")
            minted = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertTrue(
                minted.startswith("HBE/27-28/"),
                f"expected HBE/27-28/… got {minted} (calendar FY {calendar_fy})",
            )
            self.assertFalse(minted.startswith(f"HBE/{calendar_fy}/"))
            conn.commit()
        finally:
            conn.close()

    def test_hotel_settings_page_shows_invoice_prefix_hint(self):
        page = self.client.get("/hotel/settings")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('data-hotel-set-key="invoice_prefix"', html)
        self.assertIn('data-hotel-set-key="fb_invoice_prefix"', html)
        self.assertNotIn('data-hotel-set-key="room_transfer_prefix"', html)
        self.assertNotIn("hotel-invoice-prefix-hint", html)
        self.assertIn("Food &amp; Beverage Room Transfer", html)
        self.assertNotIn("<h3>Room Transfer</h3>", html)

    def test_fb_and_room_transfer_prefixes_drive_allocation(self):
        conn = db_mod.get_db()
        try:
            short_fy = db_mod.indian_fiscal_year_short_label()

            # Default FBE series
            fb_default = db_mod.allocate_fb_transfer_invoice_number(conn)
            self.assertEqual(fb_default, f"FBE/{short_fy}/00001")

            # Custom F&B stem
            db_mod.save_hotel_settings(
                conn,
                {
                    "panels": {
                        "invoice": {
                            "values": {
                                "fb_invoice_prefix": {
                                    "kind": "text",
                                    "value": "FOOD",
                                },
                                "room_transfer_prefix": {
                                    "kind": "text",
                                    "value": "RTR",
                                },
                            }
                        }
                    }
                },
            )
            self.assertEqual(db_mod.hotel_fb_invoice_prefix(conn), "FOOD")
            self.assertEqual(db_mod.hotel_room_transfer_invoice_prefix(conn), "RTR")
            fb_custom = db_mod.allocate_fb_transfer_invoice_number(conn)
            self.assertEqual(fb_custom, f"FOOD/{short_fy}/00002")

            rt = db_mod.allocate_room_transfer_invoice_number(conn)
            self.assertEqual(rt, f"RTR/{short_fy}/00001")
            rt2 = db_mod.allocate_room_transfer_invoice_number(conn)
            self.assertEqual(rt2, f"RTR/{short_fy}/00002")
            conn.commit()
        finally:
            conn.close()

    def test_plaintext_asia_tech_secrets_sealed_on_settings_get(self):
        secret = "legacy-plain-asia-tech-password"
        cm_secret = "legacy-plain-cm-password"
        conn = db_mod.get_db()
        try:
            db_mod.ensure_hotel_rooms_schema(conn)
            conn.execute(
                """
                INSERT INTO hotel_settings (id, payload, updated_at)
                VALUES (1, ?, datetime('now','localtime'))
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload
                """,
                (
                    json.dumps(
                        {
                            "panels": {
                                "asia_tech": {
                                    "values": {
                                        "asia_tech_username": {
                                            "kind": "text",
                                            "value": "desk-user",
                                        },
                                        "asia_tech_password": {
                                            "kind": "text",
                                            "value": secret,
                                        },
                                        "asia_tech_api_key": {
                                            "kind": "text",
                                            "value": secret,
                                        },
                                        "asia_tech_cm_password": {
                                            "kind": "text",
                                            "value": cm_secret,
                                        },
                                    }
                                }
                            },
                            "asia_tech_state": {
                                "username": "desk-user",
                                "password": secret,
                                "api_key": secret,
                                "cm_password": cm_secret,
                            },
                        }
                    ),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        get_resp = self.client.get("/hotel/api/settings")
        self.assertEqual(get_resp.status_code, 200)
        body = get_resp.get_data(as_text=True)
        self.assertNotIn(secret, body)
        self.assertNotIn(cm_secret, body)
        settings = (get_resp.get_json() or {}).get("settings") or {}
        values = (
            ((settings.get("panels") or {}).get("asia_tech") or {}).get("values") or {}
        )
        username = values.get("asia_tech_username")
        username_val = username.get("value") if isinstance(username, dict) else username
        self.assertEqual(username_val, "desk-user")
        pw = values.get("asia_tech_password")
        pw_val = pw.get("value") if isinstance(pw, dict) else pw
        self.assertNotEqual(pw_val, secret)
        self.assertTrue(str(pw_val or "").startswith("•") or str(pw_val or "") == "")

        conn = db_mod.get_db()
        try:
            stored = db_mod.get_hotel_settings(conn)
        finally:
            conn.close()
        stored_state = stored.get("asia_tech_state") or {}
        self.assertTrue(str(stored_state.get("password") or "").startswith("enc1$"))
        self.assertTrue(str(stored_state.get("api_key") or "").startswith("enc1$"))
        self.assertTrue(str(stored_state.get("cm_password") or "").startswith("enc1$"))
        sealed_pw = stored_state.get("password")
        conn = db_mod.get_db()
        try:
            again = db_mod.get_hotel_settings(conn)
        finally:
            conn.close()
        self.assertEqual((again.get("asia_tech_state") or {}).get("password"), sealed_pw)
        import asia_tech_client

        unsealed = asia_tech_client.get_state(stored)
        self.assertEqual(unsealed.get("password"), secret)
        self.assertEqual(unsealed.get("api_key"), secret)
        self.assertEqual(unsealed.get("cm_password"), cm_secret)
        self.assertEqual(unsealed.get("username"), "desk-user")

    def test_hotel_invoice_seq_begin_immediate_and_no_collision(self):
        src = inspect.getsource(db_mod.next_hotel_room_invoice_seq)
        helper = inspect.getsource(db_mod._sqlite_begin_immediate)
        bump = inspect.getsource(db_mod._bump_named_invoice_seq)
        self.assertIn("_sqlite_begin_immediate", src)
        self.assertIn("BEGIN IMMEDIATE", helper)
        self.assertIn("MAX(last_seq", bump.replace(" ", ""))

        short_fy = db_mod.indian_fiscal_year_short_label()
        conn = db_mod.get_db()
        try:
            first = db_mod.allocate_hotel_room_invoice_number(conn)
            self.assertEqual(first, f"HBE/{short_fy}/00001")
            conn.commit()
        finally:
            conn.close()

        numbers = []
        errors = []

        def worker():
            c = db_mod.get_db()
            try:
                numbers.append(db_mod.allocate_hotel_room_invoice_number(c))
                c.commit()
            except Exception as exc:
                errors.append(exc)
            finally:
                c.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertFalse(errors, errors)
        self.assertEqual(len(set(numbers)), 2, numbers)
        self.assertTrue(all(n.startswith(f"HBE/{short_fy}/") for n in numbers), numbers)


if __name__ == "__main__":
    unittest.main()
