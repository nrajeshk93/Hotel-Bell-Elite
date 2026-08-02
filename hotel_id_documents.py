"""Compress and store hotel guest ID proof documents."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None
    ImageOps = None

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover
    pass

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
PDF_EXTENSIONS = {".pdf"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS
WEBP_QUALITY = 82
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def hotel_id_docs_root():
    """Absolute directory for compressed ID documents."""
    base = Path(__file__).resolve().parent / "uploads" / "hotel_id_docs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ext(filename):
    return Path(filename or "").suffix.lower()


def _find_ghostscript():
    for name in ("gs", "gswin64c", "gswin32c"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _unique_stem():
    return uuid.uuid4().hex


def compress_image_to_webp(src_path, dest_path, quality=WEBP_QUALITY):
    """Convert any supported image to WebP while preserving orientation."""
    if Image is None:
        raise RuntimeError("Pillow is required to compress ID images.")
    with Image.open(src_path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        # Prefer RGB for ID scans; keep alpha only when present.
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(
            dest_path,
            format="WEBP",
            quality=int(quality),
            method=6,
            optimize=True,
        )


def compress_pdf_with_ghostscript(src_path, dest_path):
    """Visually lossless PDF compression via Ghostscript (/printer)."""
    gs = _find_ghostscript()
    if not gs:
        raise RuntimeError("Ghostscript is not installed.")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dPDFSETTINGS=/printer",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dMonoImageDownsampleType=/Bicubic",
        "-dColorImageResolution=150",
        "-dGrayImageResolution=150",
        "-dMonoImageResolution=300",
        "-dNOPAUSE",
        "-dQUIET",
        "-dBATCH",
        f"-sOutputFile={dest_path}",
        str(src_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0 or not dest_path.is_file() or dest_path.stat().st_size <= 0:
        err = (result.stderr or result.stdout or "Ghostscript failed.").strip()
        raise RuntimeError(err[:400] or "Ghostscript failed to compress PDF.")


def compress_pdf_fallback(src_path, dest_path):
    """Mild PDF stream compression when Ghostscript is unavailable."""
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError(
            "PDF compression requires Ghostscript or the pypdf package."
        ) from exc
    reader = PdfReader(str(src_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
        try:
            writer.pages[-1].compress_content_streams()
        except Exception:
            pass
    if reader.metadata:
        try:
            writer.add_metadata(reader.metadata)
        except Exception:
            pass
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as fh:
        writer.write(fh)


def compress_pdf(src_path, dest_path):
    """Prefer Ghostscript; fall back to pypdf stream compression."""
    if _find_ghostscript():
        compress_pdf_with_ghostscript(src_path, dest_path)
        return "ghostscript"
    compress_pdf_fallback(src_path, dest_path)
    return "pypdf"


def process_uploaded_id_document(file_storage, original_name=None):
    """Compress an uploaded ID document and store only the compressed file.

    Returns a dict with stored filename, original name, sizes, and mime.
    Temporary originals are always deleted.
    """
    original_name = original_name or getattr(file_storage, "filename", "") or "document"
    safe_name = secure_filename(original_name) or "document"
    ext = _ext(safe_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Only JPG, JPEG, PNG, HEIC, and PDF files are allowed.")

    # Size guard from stream if possible
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("File is too large (max 15MB).")

    tmp_dir = Path(tempfile.mkdtemp(prefix="hrd_id_"))
    tmp_src = tmp_dir / f"src{ext}"
    out_name = None
    out_path = None
    engine = None
    try:
        file_storage.save(str(tmp_src))
        original_size = tmp_src.stat().st_size
        stem = _unique_stem()
        root = hotel_id_docs_root()

        if ext in IMAGE_EXTENSIONS:
            out_name = f"{stem}.webp"
            out_path = root / out_name
            compress_image_to_webp(tmp_src, out_path)
            engine = "webp"
            mime = "image/webp"
            stored_label = Path(safe_name).stem + ".webp"
        else:
            out_name = f"{stem}.pdf"
            out_path = root / out_name
            engine = compress_pdf(tmp_src, out_path)
            # Keep Ghostscript result only if smaller; otherwise keep original bytes.
            if out_path.stat().st_size >= original_size:
                shutil.copyfile(tmp_src, out_path)
                engine = engine + "+passthrough"
            mime = "application/pdf"
            stored_label = Path(safe_name).stem + ".pdf"

        compressed_size = out_path.stat().st_size
        return {
            "storedName": out_name,
            "displayName": stored_label,
            "originalName": safe_name,
            "mime": mime,
            "originalSize": original_size,
            "compressedSize": compressed_size,
            "engine": engine,
            "urlPath": f"/hotel/api/id-documents/{out_name}",
        }
    except Exception:
        if out_path and out_path.is_file():
            try:
                out_path.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def resolve_stored_id_document(stored_name):
    """Return absolute Path for a stored document, or None if invalid/missing."""
    name = secure_filename(stored_name or "")
    if not name or "/" in stored_name or "\\" in stored_name or ".." in stored_name:
        return None
    path = hotel_id_docs_root() / name
    if not path.is_file():
        return None
    # Ensure path stays inside the docs root.
    try:
        path.resolve().relative_to(hotel_id_docs_root().resolve())
    except ValueError:
        return None
    return path
