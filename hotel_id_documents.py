"""Compress and store hotel guest ID proof documents."""

from __future__ import annotations

import io
import os
import re
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
MAX_ID_IMAGES = 8
MAX_PAGE_EDGE = 1280
JPEG_QUALITY = 62
JPEG_QUALITY_RECAP = 45
MAX_STORED_BYTES = 500 * 1024
GS_DPI = 120
GS_DPI_RECAP = 96


def hotel_id_docs_root():
    """Absolute directory for compressed ID documents."""
    env = os.environ.get("HOTEL_ID_DOCS_DIR", "").strip()
    if env:
        base = Path(env)
    else:
        base = Path(__file__).resolve().parent / "uploads" / "hotel_id_docs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def id_document_view_url(stored_name):
    """Public GET URL that does not end in .pdf/.webp (nginx often intercepts those)."""
    name = stored_id_document_basename(stored_name) or _raw_id_document_basename(
        stored_name
    )
    if not name:
        return ""
    return f"/hotel/api/id-documents/view/{name}/raw"


def _mime_for_suffix(suffix):
    return {
        ".pdf": "application/pdf",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(str(suffix or "").lower(), "application/pdf")


def persist_id_document_bytes(stored_name, data, mime="application/pdf"):
    """Keep a copy in SQLite so deploys that wipe uploads/ can still serve the ID."""
    name = stored_id_document_basename(stored_name) or _raw_id_document_basename(
        stored_name
    )
    if not name or not data:
        return
    try:
        import sqlite3

        import db as db_mod
    except Exception:
        return
    conn = db_mod.get_db()
    try:
        db_mod.ensure_hotel_id_documents_schema(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO hotel_id_documents (stored_name, mime, payload)
            VALUES (?, ?, ?)
            """,
            (name, mime or "application/pdf", sqlite3.Binary(bytes(data))),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def load_id_document_bytes(stored_name):
    """Return (bytes, mime, stored_name) from SQLite, or (None, None, None)."""
    try:
        import db as db_mod
    except Exception:
        return None, None, None
    conn = db_mod.get_db()
    try:
        db_mod.ensure_hotel_id_documents_schema(conn)
        for name in id_document_lookup_names(stored_name):
            row = conn.execute(
                """
                SELECT stored_name, mime, payload
                FROM hotel_id_documents
                WHERE stored_name = ?
                """,
                (name,),
            ).fetchone()
            if row and row["payload"]:
                return (
                    bytes(row["payload"]),
                    row["mime"] or "application/pdf",
                    row["stored_name"],
                )
    except Exception:
        return None, None, None
    finally:
        conn.close()
    return None, None, None


def open_id_document_payload(stored_name):
    """Disk first, then SQLite. Returns (data, mime, filename) or (None, None, None)."""
    path = resolve_stored_id_document(stored_name)
    if path:
        data = path.read_bytes()
        mime = _mime_for_suffix(path.suffix)
        persist_id_document_bytes(path.name, data, mime)
        return data, mime, path.name
    return load_id_document_bytes(stored_name)


def _unlink_quietly(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def _purge_image_files(paths):
    """Delete source photos after they have been written into a PDF."""
    for path in paths or []:
        path = Path(path)
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file():
            _unlink_quietly(path)


def _purge_replaced_images_for_pdf(pdf_path):
    """Remove leftover image files that share the stored PDF stem."""
    pdf_path = Path(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        return
    root = pdf_path.parent
    stems = {pdf_path.stem}
    compact = pdf_path.stem.replace("-", "")
    if len(compact) == 32 and all(c in "0123456789abcdefABCDEF" for c in compact):
        lower = compact.lower()
        stems.add(lower)
        stems.add(
            f"{lower[:8]}-{lower[8:12]}-{lower[12:16]}-{lower[16:20]}-{lower[20:]}"
        )
    for stem in stems:
        for ext in IMAGE_EXTENSIONS:
            leftover = root / f"{stem}{ext}"
            if leftover.is_file():
                _unlink_quietly(leftover)


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


def _image_to_rgb(img):
    """EXIF-transpose and flatten an image to RGB for PDF pages."""
    if ImageOps is not None:
        img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img.convert("RGB")


def _downscale_long_edge(img, max_edge=MAX_PAGE_EDGE):
    """Shrink so the longer side is at most max_edge pixels."""
    if img is None:
        return img
    width, height = img.size
    long_edge = max(width, height)
    limit = int(max_edge or 0)
    if limit <= 0 or long_edge <= limit:
        return img
    scale = limit / float(long_edge)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
    return img.resize(new_size, resample)


def _page_from_image_file(src_path, max_edge=MAX_PAGE_EDGE, quality=JPEG_QUALITY):
    """Load, downscale, and JPEG-roundtrip a photo so the PDF embeds DCT data."""
    if Image is None:
        raise RuntimeError("Pillow is required to convert ID images to PDF.")
    with Image.open(src_path) as img:
        rgb = _image_to_rgb(img)
        rgb = _downscale_long_edge(rgb, max_edge)
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=int(quality), optimize=True)
        buf.seek(0)
        with Image.open(buf) as jpeg:
            return jpeg.convert("RGB")


def compress_image_to_webp(src_path, dest_path, quality=WEBP_QUALITY):
    """Convert any supported image to WebP while preserving orientation."""
    if Image is None:
        raise RuntimeError("Pillow is required to compress ID images.")
    with Image.open(src_path) as img:
        rgb = _image_to_rgb(img)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        rgb.save(
            dest_path,
            format="WEBP",
            quality=int(quality),
            method=6,
            optimize=True,
        )


def images_to_pdf(
    image_paths, dest_path, max_edge=MAX_PAGE_EDGE, quality=JPEG_QUALITY
):
    """Combine one or more images into a JPEG-compressed PDF."""
    if Image is None:
        raise RuntimeError("Pillow is required to convert ID images to PDF.")
    if not image_paths:
        raise ValueError("Choose an ID document to upload.")
    pages = []
    try:
        for src in image_paths:
            pages.append(
                _page_from_image_file(src, max_edge=max_edge, quality=quality)
            )
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        first = pages[0]
        rest = pages[1:]
        first.save(
            dest_path,
            format="PDF",
            save_all=True,
            append_images=rest,
            resolution=72,
            quality=int(quality),
            optimize=True,
        )
    finally:
        for page in pages:
            try:
                page.close()
            except Exception:
                pass


def compress_pdf_with_ghostscript(
    src_path,
    dest_path,
    *,
    preset="/ebook",
    color_dpi=GS_DPI,
    gray_dpi=GS_DPI,
    mono_dpi=300,
    jpeg_quality=None,
):
    """Compress a PDF via Ghostscript (/ebook, downsampled color)."""
    gs = _find_ghostscript()
    if not gs:
        raise RuntimeError("Ghostscript is not installed.")
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={preset}",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dColorImageDownsampleType=/Bicubic",
        "-dGrayImageDownsampleType=/Bicubic",
        "-dMonoImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={int(color_dpi)}",
        f"-dGrayImageResolution={int(gray_dpi)}",
        f"-dMonoImageResolution={int(mono_dpi)}",
    ]
    if jpeg_quality is not None:
        quality = max(1, min(100, int(jpeg_quality)))
        cmd.extend(
            [
                f"-dJPEGQ={quality}",
                "-dAutoFilterColorImages=false",
                "-dColorImageFilter=/DCTEncode",
                "-dAutoFilterGrayImages=false",
                "-dGrayImageFilter=/DCTEncode",
            ]
        )
    cmd.extend(
        [
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={dest_path}",
            str(src_path),
        ]
    )
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


def compress_pdf(
    src_path, dest_path, *, color_dpi=GS_DPI, jpeg_quality=None
):
    """Prefer Ghostscript; fall back to pypdf. Keep the smaller output."""
    src_path = Path(src_path)
    dest_path = Path(dest_path)
    if _find_ghostscript():
        compress_pdf_with_ghostscript(
            src_path,
            dest_path,
            color_dpi=color_dpi,
            gray_dpi=color_dpi,
            jpeg_quality=jpeg_quality,
        )
        engine = "ghostscript"
    else:
        compress_pdf_fallback(src_path, dest_path)
        engine = "pypdf"
    _keep_smaller_file(src_path, dest_path)
    return engine


def _keep_smaller_file(src_path, dest_path):
    """Replace dest with src when dest is missing or larger."""
    src_path = Path(src_path)
    dest_path = Path(dest_path)
    if not src_path.is_file() or src_path.stat().st_size <= 0:
        return
    if not dest_path.is_file() or dest_path.stat().st_size <= 0:
        shutil.copyfile(src_path, dest_path)
        return
    if dest_path.stat().st_size > src_path.stat().st_size:
        shutil.copyfile(src_path, dest_path)


def _recompress_pdf_to_cap(out_path, tmp_dir, engine, image_paths=None):
    """Second pass at 96 dpi / quality 45 if the stored PDF is still over 500 KB."""
    out_path = Path(out_path)
    if not out_path.is_file() or out_path.stat().st_size <= MAX_STORED_BYTES:
        return engine
    recap_src = Path(tmp_dir) / "recap-src.pdf"
    recap_dst = Path(tmp_dir) / "recap-out.pdf"
    if image_paths:
        images_to_pdf(
            image_paths,
            recap_src,
            quality=JPEG_QUALITY_RECAP,
        )
    else:
        shutil.copyfile(out_path, recap_src)
    extra = compress_pdf(
        recap_src,
        recap_dst,
        color_dpi=GS_DPI_RECAP,
        jpeg_quality=JPEG_QUALITY_RECAP,
    )
    if recap_dst.is_file() and recap_dst.stat().st_size and recap_dst.stat().st_size < out_path.stat().st_size:
        shutil.copyfile(recap_dst, out_path)
    return f"{engine}+recap+{extra}"


_TITLE_PREFIX_RE = re.compile(
    r"^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+",
    re.IGNORECASE,
)
_UNSAFE_LABEL_RE = re.compile(r'[\\/:*?"<>|]+')


def id_document_display_name(guest_name="", id_type="", fallback=""):
    """Human filename like 'Arun Shetty Aadhaar.pdf' from guest + ID type."""
    name = _TITLE_PREFIX_RE.sub("", str(guest_name or "").strip())
    name = re.sub(r"\s+", " ", name).strip()
    id_type = re.sub(r"\s+", " ", str(id_type or "").strip())
    parts = [part for part in (name, id_type) if part]
    if parts:
        label = _UNSAFE_LABEL_RE.sub("", " ".join(parts)).strip(" .")
        if label:
            return label[:100] + ".pdf"
    fallback = str(fallback or "").strip()
    if fallback:
        stem = Path(fallback).stem or fallback
        return (stem[:100] or "document") + ".pdf"
    return ""


def _upload_size(file_storage):
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return 0
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    return size


def _classify_id_uploads(file_storages):
    items = []
    for fs in file_storages or []:
        if not fs:
            continue
        original = getattr(fs, "filename", "") or "document"
        safe_name = secure_filename(original) or "document"
        ext = _ext(safe_name)
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError("Only JPG, JPEG, PNG, HEIC, and PDF files are allowed.")
        items.append((fs, safe_name, ext))
    if not items:
        raise ValueError("Choose an ID document to upload.")
    pdfs = [item for item in items if item[2] in PDF_EXTENSIONS]
    images = [item for item in items if item[2] in IMAGE_EXTENSIONS]
    if pdfs and images:
        raise ValueError("Upload either one PDF or photo files, not both.")
    if len(pdfs) > 1:
        raise ValueError("Upload a single PDF, or photo files to combine into one PDF.")
    if len(images) > MAX_ID_IMAGES:
        raise ValueError("You can combine at most 8 photos into one ID PDF.")
    total = 0
    for item in items:
        total += _upload_size(item[0])
        if total > MAX_UPLOAD_BYTES:
            raise ValueError("File is too large (max 15MB).")
    return pdfs, images


def _finish_stored_pdf(out_path, out_name, stored_label, original_name, original_size, engine, page_count):
    compressed_size = out_path.stat().st_size
    return {
        "storedName": out_name,
        "displayName": stored_label,
        "aliasName": "",
        "originalName": original_name,
        "mime": "application/pdf",
        "originalSize": original_size,
        "compressedSize": compressed_size,
        "engine": engine,
        "pageCount": int(page_count or 1),
        "urlPath": id_document_view_url(out_name),
    }


def process_uploaded_id_documents(file_storages, guest_name=None, id_type=None):
    """Compress uploads into one stored PDF.

    One PDF is compressed in place. One or more images are merged into a
    single PDF, then compressed. Temporary originals are always deleted.
    """
    pdfs, images = _classify_id_uploads(file_storages)
    tmp_dir = Path(tempfile.mkdtemp(prefix="hrd_id_"))
    out_name = None
    out_path = None
    try:
        stem = _unique_stem()
        root = hotel_id_docs_root()
        out_name = f"{stem}.pdf"
        out_path = root / out_name

        if pdfs:
            file_storage, safe_name, ext = pdfs[0]
            tmp_src = tmp_dir / f"src{ext}"
            file_storage.save(str(tmp_src))
            original_size = tmp_src.stat().st_size
            engine = compress_pdf(tmp_src, out_path)
            engine = _recompress_pdf_to_cap(out_path, tmp_dir, engine)
            fallback_label = Path(safe_name).stem + ".pdf"
            page_count = 1
            original_name = safe_name
        else:
            paths = []
            original_size = 0
            first_safe = images[0][1]
            for index, (file_storage, _safe, ext) in enumerate(images):
                tmp_src = tmp_dir / f"src{index}{ext}"
                file_storage.save(str(tmp_src))
                original_size += tmp_src.stat().st_size
                paths.append(tmp_src)
            merged = tmp_dir / "merged.pdf"
            images_to_pdf(paths, merged)
            engine = "images-pdf+" + compress_pdf(merged, out_path)
            engine = _recompress_pdf_to_cap(
                out_path, tmp_dir, engine, image_paths=paths
            )
            _purge_image_files(paths)
            fallback_label = Path(first_safe).stem + ".pdf"
            page_count = len(images)
            original_name = first_safe if len(images) == 1 else fallback_label

        stored_label = (
            id_document_display_name(guest_name, id_type, fallback_label) or fallback_label
        )
        _purge_replaced_images_for_pdf(out_path)
        return _finish_stored_pdf(
            out_path,
            out_name,
            stored_label,
            original_name,
            original_size,
            engine,
            page_count,
        )
    except Exception:
        if out_path and out_path.is_file():
            try:
                out_path.unlink()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def process_uploaded_id_document(
    file_storage, original_name=None, guest_name=None, id_type=None
):
    """Compress a single uploaded ID document into a stored PDF."""
    if file_storage is None:
        raise ValueError("Choose an ID document to upload.")
    if original_name:
        file_storage.filename = original_name
    return process_uploaded_id_documents(
        [file_storage], guest_name=guest_name, id_type=id_type
    )


_ID_DOC_EXTS = (".pdf", ".webp", ".jpg", ".jpeg", ".png", ".heic", ".heif")


def _raw_id_document_basename(stored_name):
    """Filename only, keeping spaces; rejects path traversal."""
    text = str(stored_name or "").strip().replace("\\", "/")
    text = text.split("?")[0].split("#")[0].rstrip("/")
    if text.endswith("/raw") or text.endswith("/content"):
        text = text.rsplit("/", 1)[0]
    if "/id-documents/view/" in text:
        text = text.split("/id-documents/view/")[-1]
    elif "/id-documents/" in text:
        text = text.split("/id-documents/")[-1]
        if text in ("view", "file"):
            return ""
    elif "/" in text:
        text = text.split("/")[-1]
    if not text or ".." in text or "/" in text:
        return ""
    return text


def stored_id_document_basename(stored_name):
    """Filename only from a stored name or /hotel/api/id-documents/<file> URL."""
    text = _raw_id_document_basename(stored_name)
    if not text:
        return ""
    name = secure_filename(text)
    if not name or ".." in name:
        return ""
    return name


def _uuid_stem_variants(stem):
    text = str(stem or "").strip()
    if not text:
        return []
    variants = [text]
    compact = text.replace("-", "")
    if len(compact) == 32 and all(c in "0123456789abcdefABCDEF" for c in compact):
        lower = compact.lower()
        variants.append(lower)
        variants.append(
            f"{lower[:8]}-{lower[8:12]}-{lower[12:16]}-{lower[16:20]}-{lower[20:]}"
        )
    seen = set()
    out = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def id_document_lookup_names(stored_name):
    """Candidate on-disk filenames for a stored name, URL, or display label."""
    raw = _raw_id_document_basename(stored_name)
    safe = stored_id_document_basename(stored_name)
    bases = []
    for item in (raw, safe):
        if item and item not in bases:
            bases.append(item)
    names = []
    seen = set()

    def add(name):
        name = str(name or "").strip()
        if not name or name in seen or ".." in name:
            return
        seen.add(name)
        names.append(name)

    for base in bases:
        add(base)
        stem, ext = os.path.splitext(base)
        if not ext:
            stem, ext = base, ""
        ext = ext.lower() if ext else ""
        for variant in _uuid_stem_variants(stem):
            if ext:
                add(variant + ext)
            for other in _ID_DOC_EXTS:
                add(variant + other)
        if ext and ext not in _ID_DOC_EXTS:
            for other in _ID_DOC_EXTS:
                add(stem + other)
    return names


def resolve_stored_id_document(stored_name):
    """Return absolute Path for a stored document, or None if invalid/missing.

    Looks up the exact name, a secure_filename alias, UUID hyphen/hex variants,
    and the same stem with .pdf/.webp/image extensions so older stays that
    still point at a .webp filename can open the stored PDF.
    """
    root = hotel_id_docs_root()
    root_resolved = root.resolve()
    for name in id_document_lookup_names(stored_name):
        path = root / name
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None
