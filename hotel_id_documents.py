"""Compress and store hotel guest ID proof documents."""

from __future__ import annotations

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


def images_to_pdf(image_paths, dest_path):
    """Combine one or more image files into a single PDF."""
    if Image is None:
        raise RuntimeError("Pillow is required to convert ID images to PDF.")
    if not image_paths:
        raise ValueError("Choose an ID document to upload.")
    pages = []
    try:
        for src in image_paths:
            with Image.open(src) as img:
                pages.append(_image_to_rgb(img).copy())
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        first = pages[0]
        rest = pages[1:]
        first.save(
            dest_path,
            format="PDF",
            save_all=True,
            append_images=rest,
            resolution=150,
        )
    finally:
        for page in pages:
            try:
                page.close()
            except Exception:
                pass


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
    alias_name = stored_id_document_basename(stored_label)
    if alias_name and alias_name != out_name:
        alias_path = hotel_id_docs_root() / alias_name
        try:
            if not alias_path.exists():
                shutil.copy2(out_path, alias_path)
        except OSError:
            alias_name = ""
    else:
        alias_name = ""
    return {
        "storedName": out_name,
        "displayName": stored_label,
        "aliasName": alias_name,
        "originalName": original_name,
        "mime": "application/pdf",
        "originalSize": original_size,
        "compressedSize": compressed_size,
        "engine": engine,
        "pageCount": int(page_count or 1),
        "urlPath": f"/hotel/api/id-documents/{out_name}",
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
            if out_path.stat().st_size >= original_size:
                shutil.copyfile(tmp_src, out_path)
                engine = engine + "+passthrough"
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
            if out_path.stat().st_size >= merged.stat().st_size:
                shutil.copyfile(merged, out_path)
                engine = engine + "+passthrough"
            fallback_label = Path(first_safe).stem + ".pdf"
            page_count = len(images)
            original_name = first_safe if len(images) == 1 else fallback_label

        stored_label = (
            id_document_display_name(guest_name, id_type, fallback_label) or fallback_label
        )
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
    if "/" in text:
        text = text.split("/")[-1]
    if not text or ".." in text:
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
