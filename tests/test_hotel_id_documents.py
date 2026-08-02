"""Hotel ID document compression tests."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from werkzeug.datastructures import FileStorage

import hotel_id_documents as docs


class HotelIdDocumentCompressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self._orig_root = docs.hotel_id_docs_root
        docs.hotel_id_docs_root = lambda: self.root

    def tearDown(self):
        docs.hotel_id_docs_root = self._orig_root

    def _png_storage(self, name="id-card.png", size=(800, 500)):
        buf = io.BytesIO()
        Image.new("RGB", size, (240, 240, 245)).save(buf, format="PNG")
        buf.seek(0)
        return FileStorage(stream=buf, filename=name, content_type="image/png")

    def test_png_converts_to_webp(self):
        result = docs.process_uploaded_id_document(self._png_storage())
        self.assertTrue(result["storedName"].endswith(".webp"))
        self.assertEqual(result["mime"], "image/webp")
        stored = self.root / result["storedName"]
        self.assertTrue(stored.is_file())
        self.assertLess(result["compressedSize"], result["originalSize"])
        self.assertFalse(any(self.root.glob("src*")))

    def test_rejects_unsupported(self):
        buf = io.BytesIO(b"not-an-image")
        upload = FileStorage(stream=buf, filename="notes.txt", content_type="text/plain")
        with self.assertRaises(ValueError):
            docs.process_uploaded_id_document(upload)

    def test_pdf_uses_ghostscript_when_available(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        buf = io.BytesIO(pdf_bytes)
        upload = FileStorage(stream=buf, filename="aadhaar.pdf", content_type="application/pdf")

        def fake_gs(src, dest):
            dest.write_bytes(b"%PDF-1.4 compressed-smaller-content")

        with mock.patch.object(docs, "_find_ghostscript", return_value="/usr/bin/gs"):
            with mock.patch.object(docs, "compress_pdf_with_ghostscript", side_effect=fake_gs):
                result = docs.process_uploaded_id_document(upload)
        self.assertTrue(result["storedName"].endswith(".pdf"))
        self.assertIn("ghostscript", result["engine"])


class HotelIdDocumentRouteTests(unittest.TestCase):
    def setUp(self):
        import db as db_mod

        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._orig_path = db_mod.DATABASE_PATH
        db_mod.DATABASE_PATH = self.db_path
        db_mod.init_db()

        self.doc_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.doc_tmp.cleanup)
        self._orig_docs_root = docs.hotel_id_docs_root
        docs.hotel_id_docs_root = lambda: Path(self.doc_tmp.name)

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
        }
        self._get_user_patch = mock.patch.object(app_mod, "get_current_user", return_value=self.user)
        self._get_user_patch.start()

    def tearDown(self):
        import db as db_mod

        self._get_user_patch.stop()
        docs.hotel_id_docs_root = self._orig_docs_root
        db_mod.DATABASE_PATH = self._orig_path
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_upload_api_compresses_image(self):
        buf = io.BytesIO()
        Image.new("RGB", (640, 400), (220, 230, 240)).save(buf, format="JPEG", quality=95)
        buf.seek(0)
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={"file": (buf, "guest-id.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["document"]["storedName"].endswith(".webp"))
        stored = Path(self.doc_tmp.name) / body["document"]["storedName"]
        self.assertTrue(stored.is_file())

        file_resp = self.client.get(body["document"]["urlPath"])
        self.assertEqual(file_resp.status_code, 200)
        self.assertIn("image/webp", file_resp.headers.get("Content-Type", ""))


if __name__ == "__main__":
    unittest.main()
