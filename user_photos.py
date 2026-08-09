"""Store and resolve workspace user profile photos."""

from __future__ import annotations

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

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif"}
WEBP_QUALITY = 84
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_EDGE = 512


def user_photos_root():
    base = Path(__file__).resolve().parent / "uploads" / "user_photos"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ext(filename):
    return Path(filename or "").suffix.lower()


def process_uploaded_user_photo(upload_file, filename=None):
    """Compress an uploaded image to a square-ish WebP and return the stored filename."""
    if Image is None:
        raise RuntimeError("Pillow is required to process user photos.")
    name = filename or getattr(upload_file, "filename", "") or ""
    ext = _ext(name)
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError("Choose a JPG, PNG, WebP, or HEIC image.")

    raw = upload_file.read()
    if not raw:
        raise ValueError("The selected photo is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Photo must be 5 MB or smaller.")

    stored_name = f"{uuid.uuid4().hex}.webp"
    dest = user_photos_root() / stored_name
    tmp = user_photos_root() / f".tmp-{stored_name}"
    try:
        tmp.write_bytes(raw)
        with Image.open(tmp) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
            img.thumbnail((MAX_EDGE, MAX_EDGE), resample)
            img.save(dest, format="WEBP", quality=WEBP_QUALITY, method=6, optimize=True)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except TypeError:
            if tmp.exists():
                tmp.unlink()
    return stored_name


def resolve_stored_user_photo(stored_name):
    name = secure_filename(Path(stored_name or "").name)
    if not name or name != Path(stored_name or "").name:
        return None
    path = user_photos_root() / name
    if not path.is_file():
        return None
    return path


def delete_stored_user_photo(stored_name):
    path = resolve_stored_user_photo(stored_name)
    if path:
        try:
            path.unlink()
        except OSError:
            pass


def role_accent_index(role_name):
    """Stable 0–5 index for role color accents in the users grid."""
    text = (role_name or "user").strip().lower() or "user"
    return sum(ord(ch) for ch in text) % 6


def avatar_accent_index(seed):
    text = str(seed or "u").strip().lower() or "u"
    return sum(ord(ch) for ch in text) % 6
