"""Hotel ID document compression tests."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image
from pypdf import PdfReader
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

    def test_png_converts_to_pdf(self):
        result = docs.process_uploaded_id_document(self._png_storage())
        self.assertTrue(result["storedName"].endswith(".pdf"))
        self.assertEqual(result["mime"], "application/pdf")
        self.assertEqual(result["displayName"], "id-card.pdf")
        self.assertEqual(result["pageCount"], 1)
        stored = self.root / result["storedName"]
        self.assertTrue(stored.is_file())
        self.assertFalse(any(self.root.glob("src*")))
        self.assertFalse((self.root / result["displayName"]).is_file())
        self.assertTrue(docs.resolve_stored_id_document(result["storedName"]))
        self.assertEqual(len(PdfReader(str(stored)).pages), 1)
        self.assertFalse(list(self.root.glob("*.png")))
        self.assertFalse(list(self.root.glob("*.jpg")))
        self.assertFalse(list(self.root.glob("*.webp")))

    def test_display_name_uses_guest_and_id_type(self):
        result = docs.process_uploaded_id_document(
            self._png_storage(),
            guest_name="Mr Arun Shetty",
            id_type="Aadhaar",
        )
        self.assertEqual(result["displayName"], "Arun Shetty Aadhaar.pdf")
        alias = docs.stored_id_document_basename(result["displayName"])
        self.assertEqual(alias, "Arun_Shetty_Aadhaar.pdf")
        self.assertFalse((self.root / alias).is_file())
        self.assertTrue((self.root / result["storedName"]).is_file())
        original = "f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.png"
        result = docs.process_uploaded_id_document(self._png_storage(original))
        self.assertEqual(
            result["displayName"],
            "f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.pdf",
        )
        self.assertNotEqual(result["storedName"], result["displayName"])
        self.assertTrue((self.root / result["storedName"]).is_file())
        self.assertFalse((self.root / result["displayName"]).is_file())
        self.assertTrue(docs.resolve_stored_id_document(result["storedName"]))

    def test_images_merge_into_one_pdf(self):
        result = docs.process_uploaded_id_documents(
            [
                self._png_storage("front.png"),
                self._png_storage("back.png", size=(600, 400)),
            ]
        )
        self.assertTrue(result["storedName"].endswith(".pdf"))
        self.assertEqual(result["mime"], "application/pdf")
        self.assertEqual(result["pageCount"], 2)
        self.assertEqual(result["displayName"], "front.pdf")
        stored = self.root / result["storedName"]
        self.assertTrue(stored.is_file())
        self.assertEqual(len(PdfReader(str(stored)).pages), 2)
        self.assertFalse(list(self.root.glob("*.png")))

    def test_deletes_source_images_and_leftover_webp(self):
        leftover_webp = self.root / "abc123def456.webp"
        leftover_jpg = self.root / "abc123def456.jpg"
        leftover_webp.write_bytes(b"old-webp")
        leftover_jpg.write_bytes(b"old-jpg")
        with mock.patch.object(docs, "_unique_stem", return_value="abc123def456"):
            result = docs.process_uploaded_id_document(self._png_storage())
        self.assertEqual(result["storedName"], "abc123def456.pdf")
        self.assertTrue((self.root / "abc123def456.pdf").is_file())
        self.assertFalse(leftover_webp.is_file())
        self.assertFalse(leftover_jpg.is_file())
        self.assertFalse(list(self.root.glob("*.png")))
        self.assertFalse(list(self.root.glob("*.webp")))

    def test_rejects_mixed_pdf_and_image(self):
        pdf = FileStorage(
            stream=io.BytesIO(b"%PDF-1.4\n%%EOF\n"),
            filename="id.pdf",
            content_type="application/pdf",
        )
        with self.assertRaises(ValueError):
            docs.process_uploaded_id_documents([self._png_storage(), pdf])

    def test_rejects_too_many_images(self):
        files = [self._png_storage("page-%s.png" % i) for i in range(9)]
        with self.assertRaises(ValueError):
            docs.process_uploaded_id_documents(files)

    def test_resolve_accepts_api_url_path(self):
        result = docs.process_uploaded_id_document(self._png_storage())
        path = docs.resolve_stored_id_document(result["urlPath"])
        self.assertTrue(path and path.is_file())
        self.assertEqual(
            docs.stored_id_document_basename(result["urlPath"]),
            result["storedName"],
        )

    def test_resolve_falls_back_from_webp_name_to_pdf(self):
        pdf = self.root / "f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        found = docs.resolve_stored_id_document(
            "f3dd5b8c-2958-4e62-adbd-b62b9e6f89eb.webp"
        )
        self.assertTrue(found and found.is_file())
        self.assertEqual(found.name, pdf.name)
        found_hex = docs.resolve_stored_id_document(
            "/hotel/api/id-documents/f3dd5b8c29584e62adbdb62b9e6f89eb.webp"
        )
        self.assertTrue(found_hex and found_hex.is_file())
        self.assertEqual(found_hex.name, pdf.name)

    def test_rejects_unsupported(self):
        buf = io.BytesIO(b"not-an-image")
        upload = FileStorage(stream=buf, filename="notes.txt", content_type="text/plain")
        with self.assertRaises(ValueError):
            docs.process_uploaded_id_document(upload)

    def test_pdf_uses_ghostscript_when_available(self):
        pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        buf = io.BytesIO(pdf_bytes)
        upload = FileStorage(stream=buf, filename="aadhaar.pdf", content_type="application/pdf")

        def fake_gs(src, dest, **_kwargs):
            dest = Path(dest)
            dest.write_bytes(b"%PDF-1.4 compressed-smaller-content")

        with mock.patch.object(docs, "_find_ghostscript", return_value="/usr/bin/gs"):
            with mock.patch.object(docs, "compress_pdf_with_ghostscript", side_effect=fake_gs):
                result = docs.process_uploaded_id_document(upload)
        self.assertTrue(result["storedName"].endswith(".pdf"))
        self.assertIn("ghostscript", result["engine"])

    def test_large_photo_stores_under_size_cap(self):
        buf = io.BytesIO()
        noisy = Image.frombytes(
            "RGB", (4000, 3000), os.urandom(4000 * 3000 * 3)
        )
        noisy.save(buf, format="JPEG", quality=95)
        original_size = buf.tell()
        buf.seek(0)
        upload = FileStorage(
            stream=buf, filename="phone.jpg", content_type="image/jpeg"
        )
        result = docs.process_uploaded_id_document(
            upload, guest_name="Arun Shetty", id_type="Aadhaar"
        )
        stored = self.root / result["storedName"]
        self.assertTrue(stored.is_file())
        self.assertLessEqual(stored.stat().st_size, 500 * 1024)
        self.assertLess(stored.stat().st_size, original_size)
        self.assertEqual(result["displayName"], "Arun Shetty Aadhaar.pdf")
        self.assertFalse((self.root / "Arun_Shetty_Aadhaar.pdf").is_file())
        self.assertEqual(len(list(self.root.glob("*.pdf"))), 1)
        self.assertEqual(len(PdfReader(str(stored)).pages), 1)


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

    def _jpeg_tuple(self, name, size=(640, 400), color=(220, 230, 240)):
        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="JPEG", quality=95)
        buf.seek(0)
        return (buf, name)

    def test_upload_api_converts_image_to_pdf(self):
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={"file": self._jpeg_tuple("guest-id.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["document"]["storedName"].endswith(".pdf"))
        self.assertEqual(body["document"]["mime"], "application/pdf")
        stored = Path(self.doc_tmp.name) / body["document"]["storedName"]
        self.assertTrue(stored.is_file())

        file_resp = self.client.get(body["document"]["urlPath"])
        self.assertEqual(file_resp.status_code, 200)
        self.assertIn("application/pdf", file_resp.headers.get("Content-Type", ""))

        alias_resp = self.client.get(
            "/hotel/api/id-documents/" + body["document"]["displayName"]
        )
        self.assertEqual(alias_resp.status_code, 404)

        via_url = docs.resolve_stored_id_document(body["document"]["urlPath"])
        self.assertTrue(via_url and via_url.is_file())

    def test_get_api_serves_pdf_when_stay_still_has_webp_name(self):
        pdf = Path(self.doc_tmp.name) / "8883c8fa0c18439bbd38fefcf5e83905.pdf"
        pdf.write_bytes(b"%PDF-1.4 guest-id\n%%EOF\n")
        resp = self.client.get(
            "/hotel/api/id-documents/8883c8fa0c18439bbd38fefcf5e83905.webp"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/pdf", resp.headers.get("Content-Type", ""))
        self.assertTrue(resp.data.startswith(b"%PDF"))

    def test_view_raw_url_does_not_end_with_pdf(self):
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={"file": self._jpeg_tuple("guest-id.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        url = body["document"]["urlPath"]
        self.assertTrue(url.endswith("/raw"), url)
        self.assertFalse(url.endswith(".pdf"), url)
        self.assertIn("/id-documents/view/", url)
        file_resp = self.client.get(url)
        self.assertEqual(file_resp.status_code, 200)
        self.assertIn("application/pdf", file_resp.headers.get("Content-Type", ""))
        self.assertTrue(file_resp.data.startswith(b"%PDF"))

    def test_view_url_serves_from_db_after_disk_file_removed(self):
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={"file": self._jpeg_tuple("guest-id.jpg")},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        stored = Path(self.doc_tmp.name) / body["document"]["storedName"]
        self.assertTrue(stored.is_file())
        stored.unlink()
        self.assertFalse(stored.is_file())
        file_resp = self.client.get(body["document"]["urlPath"])
        self.assertEqual(file_resp.status_code, 200)
        self.assertIn("application/pdf", file_resp.headers.get("Content-Type", ""))
        self.assertTrue(file_resp.data.startswith(b"%PDF"))

    def test_upload_api_names_file_from_guest_and_id_type(self):
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={
                "file": self._jpeg_tuple("scan.jpg"),
                "guestName": "Mr Arun Shetty",
                "idType": "Aadhaar",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["document"]["displayName"], "Arun Shetty Aadhaar.pdf")
        alias = docs.stored_id_document_basename(body["document"]["displayName"])
        self.assertFalse((Path(self.doc_tmp.name) / alias).is_file())
        stored = Path(self.doc_tmp.name) / body["document"]["storedName"]
        self.assertTrue(stored.is_file())

    def test_upload_api_merges_two_images(self):
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={
                "file": [
                    self._jpeg_tuple("front.jpg", color=(200, 210, 220)),
                    self._jpeg_tuple("back.jpg", size=(480, 320), color=(180, 190, 200)),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["document"]["pageCount"], 2)
        stored = Path(self.doc_tmp.name) / body["document"]["storedName"]
        self.assertEqual(len(PdfReader(str(stored)).pages), 2)

    def test_upload_api_rejects_mixed_pdf_and_image(self):
        pdf_buf = io.BytesIO(b"%PDF-1.4\n%%EOF\n")
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={
                "file": [
                    self._jpeg_tuple("front.jpg"),
                    (pdf_buf, "id.pdf"),
                ]
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["ok"])

    def test_upload_api_rejects_nine_images(self):
        files = [self._jpeg_tuple("page-%s.jpg" % i) for i in range(9)]
        resp = self.client.post(
            "/hotel/api/id-documents",
            data={"file": files},
            content_type="multipart/form-data",
        )
        self.assertEqual(resp.status_code, 400)
        body = resp.get_json()
        self.assertFalse(body["ok"])


if __name__ == "__main__":
    unittest.main()
