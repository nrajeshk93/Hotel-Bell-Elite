"""Hotel ID document refs must stay UUID-backed end-to-end.

Display labels like "Karthik Nemala.pdf" must never become fetch URLs — production
files are always <hex32>.pdf (disk + SQLite blob).
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import FileStorage

import db as db_mod
import hotel_id_documents as docs


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_PATH = os.path.join(PROJECT_ROOT, "static", "hotel_room_detail.js")


class HotelIdDocumentRefTests(unittest.TestCase):
    def test_basename_rejects_human_display_labels(self):
        self.assertEqual(db_mod._hotel_id_document_basename("Karthik Nemala.pdf"), "")
        self.assertEqual(
            db_mod._hotel_id_document_basename(
                "/hotel/api/id-documents/view/Karthik%20Nemala.pdf/raw"
            ),
            "",
        )
        self.assertEqual(
            db_mod._hotel_id_document_view_path(
                "Karthik Nemala.pdf",
                "/hotel/api/id-documents/view/Karthik%20Nemala.pdf/raw",
            ),
            "",
        )

    def test_basename_keeps_uuid_storage_keys(self):
        uuid_name = "94905c4b2a884e51a0856e8df31897d2.pdf"
        self.assertEqual(db_mod._hotel_id_document_basename(uuid_name), uuid_name)
        path = db_mod._hotel_id_document_view_path(
            uuid_name, "/hotel/api/id-documents/view/%s/raw" % uuid_name
        )
        self.assertEqual(path, "/hotel/api/id-documents/view/%s/raw" % uuid_name)

    def test_normalize_stay_scrubs_human_id_paths(self):
        stay = {
            "firstName": "Karthik",
            "lastName": "Nemala",
            "idDocumentName": "Karthik Nemala Aadhaar.pdf",
            "idDocumentPath": "/hotel/api/id-documents/view/Karthik%20Nemala.pdf/raw",
            "idDocumentStoredName": "Karthik Nemala.pdf",
            "idDocumentMime": "application/pdf",
        }
        out = db_mod._normalize_hotel_room_stay(stay)
        self.assertEqual(out.get("idDocumentName") or "", "")
        self.assertEqual(out.get("idDocumentPath") or "", "")
        self.assertEqual(out.get("idDocumentStoredName") or "", "")
        self.assertEqual(out.get("idDocumentMime") or "", "")

    def test_normalize_stay_keeps_uuid_id_refs(self):
        uuid_name = "94905c4b2a884e51a0856e8df31897d2.pdf"
        stay = {
            "firstName": "Harpreet",
            "idDocumentName": "Harpreet Singh Chopra Aadhaar.pdf",
            "idDocumentPath": "/hotel/api/id-documents/view/%s/raw" % uuid_name,
            "idDocumentStoredName": uuid_name,
            "idDocumentMime": "application/pdf",
        }
        out = db_mod._normalize_hotel_room_stay(stay)
        self.assertEqual(out.get("idDocumentStoredName"), uuid_name)
        self.assertEqual(
            out.get("idDocumentPath"),
            "/hotel/api/id-documents/view/%s/raw" % uuid_name,
        )
        self.assertEqual(out.get("idDocumentName"), "Harpreet Singh Chopra Aadhaar.pdf")

    def test_normalize_extra_guest_scrubs_human_paths(self):
        stay = {
            "firstName": "Host",
            "additionalGuests": [
                {
                    "name": "Extra Guest",
                    "idType": "Aadhaar",
                    "idDocumentName": "Extra Guest.pdf",
                    "idDocumentPath": "/hotel/api/id-documents/view/Extra%20Guest.pdf/raw",
                    "idDocumentStoredName": "Extra Guest.pdf",
                }
            ],
        }
        out = db_mod._normalize_hotel_room_stay(stay)
        guests = out.get("additionalGuests") or []
        self.assertEqual(len(guests), 1)
        self.assertEqual(guests[0].get("idDocumentPath") or "", "")
        self.assertEqual(guests[0].get("idDocumentStoredName") or "", "")
        self.assertEqual(guests[0].get("idDocumentName") or "", "")


class HotelIdDocumentUploadUuidTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self._orig_root = docs.hotel_id_docs_root
        docs.hotel_id_docs_root = lambda: self.root

    def tearDown(self):
        docs.hotel_id_docs_root = self._orig_root

    def _png_storage(self, name="id-card.png"):
        buf = io.BytesIO()
        Image.new("RGB", (400, 240), (240, 240, 245)).save(buf, format="PNG")
        buf.seek(0)
        return FileStorage(stream=buf, filename=name, content_type="image/png")

    def test_upload_persists_uuid_stored_name_not_display_label(self):
        result = docs.process_uploaded_id_document(
            self._png_storage(),
            guest_name="Karthik Nemala",
            id_type="Aadhaar",
        )
        stored = result.get("storedName") or ""
        self.assertTrue(stored.endswith(".pdf"), stored)
        stem = stored.rsplit(".", 1)[0]
        self.assertRegex(stem, r"^[0-9a-f]{32}$")
        self.assertIn(stored, result.get("urlPath") or "")
        self.assertNotIn("Karthik", stored)
        self.assertNotIn(" ", stored)
        self.assertTrue((self.root / stored).is_file())
        # Display label is for UI only — must not exist as a file key.
        display = result.get("displayName") or ""
        self.assertTrue(display)
        self.assertNotEqual(display, stored)
        self.assertFalse((self.root / display).is_file())


class HotelIdDocumentClientGuardTests(unittest.TestCase):
    def test_client_js_rejects_display_name_as_storage_key(self):
        with io.open(JS_PATH, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("Only UUID storage keys", src)
        self.assertNotIn(
            "idDocumentViewUrl(displayName)",
            src,
            "display labels must not build view URLs",
        )
        # Old permissive pattern that accepted "Karthik Nemala.pdf".
        self.assertIsNone(
            re.search(r"\[\^A-Za-z0-9\._ -\]\+", src),
            "client must not accept spaced human filenames as storage keys",
        )
        self.assertIn("idDocumentLabelForSave", src)
        self.assertIn(
            "Fabricated",
            src,
            "client must refuse fabricated Guest Name.pdf links",
        )


if __name__ == "__main__":
    unittest.main()
