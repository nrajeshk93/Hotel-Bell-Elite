"""POS invoice WhatsApp template send (hotel_bell_elite_invoice)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import db as db_mod
import pos_invoice_whatsapp as wa_pos


class PosInvoiceWhatsAppUnitTests(unittest.TestCase):
    def test_template_name_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WHATSAPP_POS_INVOICE_TEMPLATE", None)
            os.environ.pop("WHATSAPP_POS_INVOICE_TEMPLATE_LANGUAGE", None)
            name, lang = wa_pos.pos_invoice_template_config()
        self.assertEqual(name, "hotel_bell_elite_invoice")
        self.assertEqual(lang, "en")

    def test_template_params_mapping(self):
        invoice = {
            "id": 12,
            "order_no": "SPC/2260/2026-27",
            "customer_name": "Rajesh",
            "customer_mobile": "9876543210",
            "grand_total": 3447,
        }
        params = wa_pos.build_pos_invoice_template_params(
            invoice, business_name="SPICE MULTICUISINE"
        )
        self.assertEqual(
            params,
            ["Rajesh", "Spice Multicuisine", "SPC/2260/2026-27", "3,447.00"],
        )

    def test_guest_name_uses_first_token_only(self):
        self.assertEqual(wa_pos.format_pos_invoice_guest_name("Rajesh"), "Rajesh")
        self.assertEqual(wa_pos.format_pos_invoice_guest_name("Rajesh Kumar"), "Rajesh")
        self.assertEqual(wa_pos.format_pos_invoice_guest_name("  Maya, Sharma "), "Maya")
        self.assertEqual(wa_pos.format_pos_invoice_guest_name(""), "Guest")
        self.assertEqual(wa_pos.format_pos_invoice_guest_name(None), "Guest")

    def test_brand_display_title_case_not_all_caps(self):
        self.assertEqual(
            wa_pos.format_pos_invoice_brand_display("SPICE MULTICUISINE"),
            "Spice Multicuisine",
        )
        self.assertEqual(
            wa_pos.format_pos_invoice_brand_display("IRISH BARREL HOUSE BAR"),
            "Irish Barrel House Bar",
        )
        self.assertEqual(
            wa_pos.format_pos_invoice_brand_display("spice multicuisine"),
            "Spice Multicuisine",
        )
        self.assertEqual(wa_pos.format_pos_invoice_brand_display(""), "Hotel Bell Elite")

    def test_amount_format_no_rupee_glyph(self):
        self.assertEqual(wa_pos.format_pos_invoice_amount(6362), "6,362.00")
        self.assertEqual(wa_pos.format_pos_invoice_amount(6362.0), "6,362.00")
        self.assertEqual(wa_pos.format_pos_invoice_amount("105"), "105.00")
        self.assertEqual(wa_pos.format_pos_invoice_amount(None), "0.00")
        self.assertNotIn("₹", wa_pos.format_pos_invoice_amount(6362))

    def test_template_params_full_name_and_amount(self):
        invoice = {
            "id": 99,
            "order_no": "SPC/2287/2026-27",
            "customer_name": "Rajesh Kumar",
            "grand_total": 6362,
        }
        params = wa_pos.build_pos_invoice_template_params(
            invoice, business_name="SPICE MULTICUISINE"
        )
        self.assertEqual(
            params,
            ["Rajesh", "Spice Multicuisine", "SPC/2287/2026-27", "6,362.00"],
        )
        # Four slots only — never collapse the letter into one variable.
        self.assertEqual(len(params), 4)

    def test_rejects_missing_mobile(self):
        phone, err = wa_pos.resolve_pos_invoice_mobile(
            {"customer_name": "Guest", "customer_mobile": ""}
        )
        self.assertEqual(phone, "")
        self.assertIn("mobile", err.lower())

    def test_payload_shape_has_document_header_and_body(self):
        payload = wa_pos.build_template_send_payload_shape(
            phone="919876543210",
            template_name="hotel_bell_elite_invoice",
            template_language="en",
            body_parameters=["Rajesh", "Spice Multicuisine", "SPC/1/2026-27", "100.00"],
            header_document_id="media-123",
            header_document_filename="SPC-1-2026-27.pdf",
        )
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["name"], "hotel_bell_elite_invoice")
        comps = payload["template"]["components"]
        self.assertEqual(comps[0]["type"], "header")
        self.assertEqual(comps[0]["parameters"][0]["type"], "document")
        self.assertEqual(comps[0]["parameters"][0]["document"]["id"], "media-123")
        self.assertEqual(comps[1]["type"], "body")
        texts = [p["text"] for p in comps[1]["parameters"]]
        self.assertEqual(texts, ["Rajesh", "Spice Multicuisine", "SPC/1/2026-27", "100.00"])


class PosInvoiceWhatsAppApiTests(unittest.TestCase):
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

    def _save_invoice(self, *, mobile="9876543210", customer_bill=True, **extra):
        data = {
            "orderNo": "SPC/9001/2026-27",
            "savedAt": "2026-09-05 12:00:00",
            "orderDate": "2026-09-05",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Rajesh",
            "customerMobile": mobile,
            "customerBill": customer_bill,
            "lines": [{"uid": "1", "name": "Coffee", "rate": 100, "qty": 1}],
            "totals": {
                "subtotal": 100,
                "discount": 0,
                "gst": 5,
                "vat": 0,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 105,
            },
        }
        data.update(extra)
        res = self.client.post("/point-of-sale/api/invoices", json=data)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body.get("ok"), body)
        return body["invoice"]

    def test_api_rejects_missing_mobile(self):
        invoice = self._save_invoice(mobile="")
        res = self.client.post(
            f"/point-of-sale/api/invoices/{invoice['id']}/send-whatsapp"
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertFalse(body.get("ok"))
        self.assertIn("mobile", (body.get("error") or "").lower())

    def test_api_dry_run_payload_uses_template(self):
        invoice = self._save_invoice()
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False):
            res = self.client.post(
                f"/point-of-sale/api/invoices/{invoice['id']}/send-whatsapp"
            )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        body = res.get_json()
        self.assertTrue(body.get("ok"), body)
        self.assertTrue(body.get("dry_run"))
        self.assertEqual(body.get("template_name"), "hotel_bell_elite_invoice")
        params = body.get("template_params") or []
        self.assertEqual(len(params), 4)
        self.assertEqual(params[0], "Rajesh")
        self.assertEqual(params[1], "Spice Multicuisine")
        self.assertEqual(params[2], invoice.get("order_no"))
        self.assertEqual(params[3], "105.00")
        payload = body.get("payload") or {}
        self.assertEqual(payload.get("type"), "template")
        self.assertEqual(payload["template"]["name"], "hotel_bell_elite_invoice")
        comps = payload["template"]["components"]
        self.assertEqual(comps[0]["type"], "header")
        self.assertEqual(comps[0]["parameters"][0]["type"], "document")
        self.assertEqual(comps[1]["type"], "body")

    def test_bar_api_uses_same_template(self):
        data = {
            "orderNo": "IBH/1/2026-27",
            "savedAt": "2026-09-05 12:00:00",
            "orderDate": "2026-09-05",
            "orderType": "takeaway",
            "table": "",
            "customerName": "Guest",
            "customerMobile": "9123456780",
            "customerBill": True,
            "lines": [{"uid": "1", "name": "Beer", "rate": 200, "qty": 1}],
            "totals": {
                "subtotal": 200,
                "discount": 0,
                "gst": 0,
                "vat": 20,
                "service": 0,
                "tip": 0,
                "roundOff": 0,
                "total": 220,
            },
        }
        save = self.client.post("/bar-point-of-sale/api/invoices", json=data)
        self.assertEqual(save.status_code, 200, save.get_data(as_text=True))
        invoice = save.get_json()["invoice"]
        with mock.patch.dict(os.environ, {"WHATSAPP_DRY_RUN": "1"}, clear=False):
            res = self.client.post(
                f"/bar-point-of-sale/api/invoices/{invoice['id']}/send-whatsapp"
            )
        body = res.get_json()
        self.assertEqual(res.status_code, 200, body)
        self.assertEqual(body.get("template_name"), "hotel_bell_elite_invoice")
        self.assertEqual(body["template_params"][1], "Irish Barrel House Bar")

    def test_api_requires_generated_invoice(self):
        invoice = self._save_invoice(customer_bill=False)
        # Takeaway without customerBill may still auto-set depending on save path;
        # force clear if needed.
        conn = db_mod.get_db()
        try:
            conn.execute(
                "UPDATE pos_invoices SET customer_bill_sent = 0, customer_bill_at = '' WHERE id = ?",
                (invoice["id"],),
            )
            conn.commit()
        finally:
            conn.close()
        res = self.client.post(
            f"/point-of-sale/api/invoices/{invoice['id']}/send-whatsapp"
        )
        self.assertEqual(res.status_code, 400)
        body = res.get_json()
        self.assertIn("Generate", body.get("error") or "")


if __name__ == "__main__":
    unittest.main()
