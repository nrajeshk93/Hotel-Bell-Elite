"""Generate Hotel Bell Elite daily sales report image for WhatsApp.

Visual system cloned from Neeraj Textile sales_whatsapp_report_image.py
(same layout, colors, card style, icons, typography, INR footer).

Content mapping:
  Hero  → TOTAL SALES
  Cards → HOTEL / RESTAURANT / BAR
  Bottom → DIFFERENCE (vs yesterday)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


_DESIGN_W, _DESIGN_H = 1200, 628
_DEFAULT_REPORT_WIDTH = 1200
_DEFAULT_SUPERSAMPLE = 4

# Palette — matched to Neeraj Textile mockup
BG = '#F8FAFC'
SURFACE = '#FFFFFF'
TEXT = '#111827'
MUTED = '#6B7280'
PRIMARY = '#5B4BFF'
PRIMARY_SOFT = '#F3F0FF'
HOTEL = '#2563EB'
HOTEL_SOFT = '#EFF6FF'
RESTAURANT = '#F97316'
RESTAURANT_SOFT = '#FFF7ED'
BAR = '#7C3AED'
BAR_SOFT = '#F5F3FF'
SUCCESS = '#16A34A'
SUCCESS_BG = '#ECFDF5'
DANGER = '#DC2626'
DANGER_BG = '#FEF2F2'

TINT_HERO = '#FCFBFF'
TINT_HOTEL = '#F8FBFF'
TINT_RESTAURANT = '#FFF9F5'
TINT_BAR = '#FAF8FF'
TINT_NET = '#F0FDF8'

# Layout (design px)
_OUTER_MARGIN = 4
_CARD_INNER_PAD = 32
_SECTION_GAP = 16
_CARD_GAP = 20
_OUTER_RADIUS = 28
_INNER_RADIUS = 16
_HEADER_H = 82
_HERO_H = 160
_SUMMARY_H = 142
_DIFF_H = 100
_FOOTER_H = 22
_LOGO_H = 64
_HERO_CIRCLE = 110
_SUMMARY_ICON = 82
_DIFF_CIRCLE = 76
_PILL_W = 200
_PILL_H = 66
_ACCENT_LINE = 4

_BRAND_LOGO: Image.Image | None | bool = False


def _report_export_size() -> tuple[int, int]:
    raw = (os.environ.get('WHATSAPP_REPORT_WIDTH') or str(_DEFAULT_REPORT_WIDTH)).strip()
    try:
        width = int(raw)
    except (TypeError, ValueError):
        width = _DEFAULT_REPORT_WIDTH
    width = max(800, min(width, 1200))
    return width, int(round(width / 1.91))


def _supersample_factor() -> int:
    raw = (os.environ.get('WHATSAPP_REPORT_SUPERSAMPLE') or str(_DEFAULT_SUPERSAMPLE)).strip()
    try:
        factor = int(raw)
    except (TypeError, ValueError):
        factor = _DEFAULT_SUPERSAMPLE
    return max(1, min(factor, 6))


def _report_render_size() -> tuple[int, int]:
    ew, eh = _report_export_size()
    ss = _supersample_factor()
    return ew * ss, eh * ss


W, H = _report_render_size()
_SX = W / _DESIGN_W
_SY = H / _DESIGN_H
_DEFAULT_EXPORT_SCALE = 1.0


def _export_scale() -> float:
    raw = (os.environ.get('WHATSAPP_SALES_REPORT_IMAGE_SCALE') or str(_DEFAULT_EXPORT_SCALE)).strip()
    try:
        scale = float(raw)
    except (TypeError, ValueError):
        scale = _DEFAULT_EXPORT_SCALE
    return max(1.0, min(scale, 1.0))


def _png_compress_level() -> int:
    raw = (os.environ.get('WHATSAPP_SALES_REPORT_PNG_COMPRESS') or '1').strip()
    try:
        level = int(raw)
    except (TypeError, ValueError):
        level = 3
    return max(0, min(level, 9))


def _soft_shadows_enabled() -> bool:
    return (os.environ.get('WHATSAPP_REPORT_FLAT_SHADOW') or '0').strip().lower() not in {
        '1', 'true', 'yes', 'on',
    }


def _jpeg_quality() -> int:
    raw = (os.environ.get('WHATSAPP_REPORT_JPEG_QUALITY') or '95').strip()
    try:
        quality = int(raw)
    except (TypeError, ValueError):
        quality = 95
    return max(85, min(quality, 100))


def _report_image_format() -> str:
    fmt = (os.environ.get('WHATSAPP_REPORT_FORMAT') or 'jpeg').strip().lower()
    return 'png' if fmt == 'png' else 'jpeg'


def report_image_extension() -> str:
    return '.png' if _report_image_format() == 'png' else '.jpg'


def report_image_mime_type() -> str:
    return 'image/png' if _report_image_format() == 'png' else 'image/jpeg'


def _finalize_report_image(img: Image.Image) -> Image.Image:
    export_w, export_h = _report_export_size()
    if img.size != (export_w, export_h):
        img = img.resize((export_w, export_h), Image.Resampling.LANCZOS)
    return img.convert('RGB')


def _save_report_image(img: Image.Image, output_path: str) -> None:
    scale = _export_scale()
    if scale != 1.0:
        img = img.resize(
            (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    img = _finalize_report_image(img)
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    if _report_image_format() == 'png':
        img.save(output_path, format='PNG', compress_level=_png_compress_level())
    else:
        img.save(output_path, format='JPEG', quality=_jpeg_quality(), subsampling=0, optimize=True)


def _s(v: float) -> int:
    return int(round(v * _SX))


def _sy(v: float) -> int:
    return int(round(v * _SY))


def _sf(v: float) -> int:
    return max(8, int(round(v * (_SX + _SY) / 2)))


def _hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip('#')
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _font_paths() -> list[str]:
    base = os.path.dirname(__file__)
    return [
        os.path.join(base, 'static', 'fonts'),
        os.path.join(os.path.dirname(ImageFont.__file__), 'fonts'),
        '/usr/share/fonts/truetype/inter',
        '/usr/share/fonts/truetype/noto',
        '/usr/share/fonts/truetype/dejavu',
        '/usr/share/fonts/truetype/liberation2',
        '/usr/share/fonts/truetype/ubuntu',
        '/System/Library/Fonts/Supplemental',
        '/Library/Fonts',
    ]


def _font_candidates(*names: str) -> list[str]:
    out: list[str] = []
    for name in names:
        if not name:
            continue
        out.append(name)
        for d in _font_paths():
            out.append(os.path.join(d, name))
    return out


def _load_font(candidates: list[str], size: int, index: int = 0):
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.sep in path and not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    return None


def _font(size: int, weight: str = 'medium') -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    w = weight.lower()
    if w in ('extrabold', '800'):
        names = ('Inter-ExtraBold.ttf', 'Inter-Bold.ttf', 'NotoSans-Bold.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf', 'Ubuntu-B.ttf')
    elif w in ('bold', '700'):
        names = ('Inter-Bold.ttf', 'NotoSans-Bold.ttf', 'Roboto-Bold.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf', 'Ubuntu-B.ttf')
    elif w in ('semibold', '600'):
        names = ('Inter-SemiBold.ttf', 'NotoSans-SemiBold.ttf', 'DejaVuSans-Bold.ttf', 'LiberationSans-Bold.ttf', 'Ubuntu-B.ttf')
    else:
        names = ('Inter-Medium.ttf', 'NotoSans-Medium.ttf', 'DejaVuSans.ttf', 'LiberationSans-Regular.ttf', 'Ubuntu-R.ttf')
    candidates = _font_candidates(*names)
    candidates.extend([
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf' if w in ('bold', '700', 'extrabold', '800') else '/System/Library/Fonts/Supplemental/Arial.ttf',
    ])
    font = _load_font(candidates, size)
    return font if font else ImageFont.load_default()


def _amount_font(size: int, weight: str = 'bold') -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Prefer Devanagari / Unicode fonts so ₹ renders (Arial Bold lacks it)."""
    bold = weight in ('bold', '700', 'extrabold', '800')
    devanagari = '/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc'
    if os.path.isfile(devanagari):
        font = _load_font([devanagari], size, index=1 if bold else 0)
        if font:
            return font
    candidates = _font_candidates(
        'NotoSans-Bold.ttf' if bold else 'NotoSans-Regular.ttf',
        'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf',
        'Arial Unicode.ttf',
    )
    candidates.extend([
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/Library/Fonts/Arial Unicode.ttf',
    ])
    font = _load_font(candidates, size)
    return font if font else _font(size, weight)


def _rupee_font(size: int):
    return _amount_font(size, 'bold')


def _logo_path() -> str:
    here = Path(__file__).resolve().parent
    for name in ('static/hbe_logo.png', 'static/hbe_logo_sm.png'):
        p = here / name
        if p.is_file():
            return str(p)
    return str(here / 'static/hbe_logo.png')


def _load_brand_logo() -> Image.Image | None:
    global _BRAND_LOGO
    if _BRAND_LOGO is not False:
        return _BRAND_LOGO  # type: ignore[return-value]
    path = _logo_path()
    if not os.path.isfile(path):
        _BRAND_LOGO = None
        return None
    try:
        logo = Image.open(path).convert('RGBA')
    except OSError:
        _BRAND_LOGO = None
        return None
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    _BRAND_LOGO = logo
    return logo


def _paste_logo(img: Image.Image, box: tuple[int, int, int, int]) -> bool:
    logo = _load_brand_logo()
    if not logo:
        return False
    x0, y0, x1, y1 = box
    mw, mh = max(1, x1 - x0), max(1, y1 - y0)
    sc = min(mw / logo.width, mh / logo.height)
    sz = (max(1, int(logo.width * sc)), max(1, int(logo.height * sc)))
    r = logo.resize(sz, Image.Resampling.LANCZOS)
    img.alpha_composite(r, (x0, y0 + (mh - sz[1]) // 2))
    return True


def format_inr(amount: float | int | None) -> str:
    """Indian-grouped INR string (public helper retained for callers)."""
    neg, digits = _inr_parts(amount)
    return f"{'-' if neg else ''}₹{digits}"


def format_report_date(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or '').strip()
        dt = None
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                dt = datetime.strptime(raw[:10], fmt)
                break
            except ValueError:
                continue
        if dt is None:
            dt = datetime.now()
    return dt.strftime('%d %b %Y')


def _inr_parts(amount: float | int | None) -> tuple[bool, str]:
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    neg = value < 0
    value = abs(value)
    s = str(int(round(value)))
    if len(s) <= 3:
        grouped = s
    else:
        last3, rest = s[-3:], s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ','.join(parts) + ',' + last3
    return neg, grouped


def _text_len(draw: ImageDraw.ImageDraw, text: str, font) -> float:
    return float(draw.textlength(text, font=font))


def _fit_font(draw, text, max_w, max_sz, min_sz, weight='bold'):
    for size in range(max_sz, min_sz - 1, -1):
        font = _font(size, weight)
        if _text_len(draw, text, font) <= max_w:
            return font, size
    return _font(min_sz, weight), min_sz


def _fit_amount_font(draw, text, max_w, max_sz, min_sz, weight='bold'):
    for size in range(max_sz, min_sz - 1, -1):
        font = _amount_font(size, weight)
        if _text_len(draw, text, font) <= max_w:
            return font, size
    return _amount_font(min_sz, weight), min_sz


def _pct_change(current: float, prior: float | None) -> float | None:
    if prior is None:
        return None
    try:
        p = float(prior)
    except (TypeError, ValueError):
        return None
    if abs(p) < 1e-9:
        return None
    return round(((float(current) - p) / abs(p)) * 100.0, 1)


def _pct_meta(pct: float | None) -> tuple[str, str, str, bool | None]:
    if pct is None:
        return ('--', MUTED, SURFACE, None)
    try:
        v = float(pct)
    except (TypeError, ValueError):
        return ('--', MUTED, SURFACE, None)
    up = v >= 0
    return (
        f'{abs(v):.1f}%',
        SUCCESS if up else DANGER,
        SUCCESS_BG if up else DANGER_BG,
        up,
    )


def _clean_supporting_text(value: Any, fallback: str = '') -> str:
    text = str(value or '').strip()
    if text in {'-', '–', '—', '--'}:
        return fallback
    return text or fallback


def _weekday_from_label(date_label: str) -> str:
    try:
        return datetime.strptime(date_label, '%d %b %Y').strftime('%A')
    except (TypeError, ValueError):
        return ''


def _parse_sales_date(sales_date: str) -> datetime | None:
    raw = str(sales_date or '').strip()[:10]
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _draw_arrow(draw, cx, cy, up: bool, color: str, size: int, width: int):
    shaft = max(4, int(size * 0.62))
    if up:
        draw.line((cx, cy + shaft // 2, cx, cy - shaft // 2), fill=color, width=width)
        draw.line((cx, cy - shaft // 2, cx - size // 3, cy - shaft // 6), fill=color, width=width)
        draw.line((cx, cy - shaft // 2, cx + size // 3, cy - shaft // 6), fill=color, width=width)
    else:
        draw.line((cx, cy - shaft // 2, cx, cy + shaft // 2), fill=color, width=width)
        draw.line((cx, cy + shaft // 2, cx - size // 3, cy + shaft // 6), fill=color, width=width)
        draw.line((cx, cy + shaft // 2, cx + size // 3, cy + shaft // 6), fill=color, width=width)


def _draw_trend_text(draw, x, y, pct, *, font, anchor='lm'):
    txt, color, _, up = _pct_meta(pct)
    if up is None:
        draw.text((x, y), txt, font=font, fill=color, anchor=anchor)
        return
    text_w = _text_len(draw, txt, font)
    arrow_sz = max(_s(12), int(getattr(font, 'size', _sf(18)) * 0.72))
    gap = max(_s(6), arrow_sz // 3)
    total = arrow_sz + gap + text_w
    if anchor.endswith('m') or anchor.endswith('b') or anchor.endswith('t'):
        if anchor.startswith('m'):
            start_x = x - total / 2
        elif anchor.startswith('r'):
            start_x = x - total
        else:
            start_x = x
    else:
        start_x = x
    _draw_arrow(draw, int(start_x + arrow_sz / 2), y, up, color, arrow_sz, max(2, _s(3)))
    draw.text((start_x + arrow_sz + gap, y), txt, font=font, fill=color, anchor='lm')


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _card_shadow(base, box, radius, *, dy=None, blur=None, alpha=12):
    if not _soft_shadows_enabled():
        return
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    shadow_dy = dy if dy is not None else max(2, _sy(8))
    shadow_blur = blur if blur is not None else max(6, _s(14))
    ld.rounded_rectangle((x0, y0 + shadow_dy, x1, y1 + shadow_dy), radius=radius, fill=(15, 23, 42, alpha))
    base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(shadow_blur)))


def _gradient_tile(w: int, h: int, left: str, right: str) -> Image.Image:
    lr, lg, lb = _hex_rgb(left)
    rr, rg, rb = _hex_rgb(right)
    tile = Image.new('RGBA', (max(1, w), max(1, h)), (0, 0, 0, 0))
    px = tile.load()
    for x in range(tile.width):
        mix = x / max(1, tile.width - 1)
        rgb = (
            int(lr * (1 - mix) + rr * mix),
            int(lg * (1 - mix) + rg * mix),
            int(lb * (1 - mix) + rb * mix),
        )
        for y in range(tile.height):
            px[x, y] = (*rgb, 255)
    return tile


def _radial_circle(diameter: int, inner: str, outer: str) -> Image.Image:
    size = max(1, diameter)
    tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    px = tile.load()
    cx = cy = size / 2
    ir, ig, ib = _hex_rgb(inner)
    or_, og, ob = _hex_rgb(outer)
    for y in range(size):
        for x in range(size):
            dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / (size / 2)
            if dist <= 1.0:
                mix = min(1.0, dist)
                rgb = (
                    int(ir * (1 - mix) + or_ * mix),
                    int(ig * (1 - mix) + og * mix),
                    int(ib * (1 - mix) + ob * mix),
                )
                px[x, y] = (*rgb, 255)
    return tile


def _hero_waves(base: Image.Image, box):
    x0, y0, x1, y1 = box
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    w, h = x1 - x0, y1 - y0
    for idx, alpha in enumerate((18, 12, 8)):
        offset = idx * _s(18)
        pts = []
        for step in range(0, 11):
            t = step / 10
            px = x0 + int(w * (0.45 + t * 0.52)) + offset
            py = y0 + int(h * (0.18 + 0.12 * (step % 3) + idx * 0.08))
            pts.append((px, py))
        if len(pts) >= 2:
            ld.line(pts, fill=(91, 75, 255, alpha), width=max(1, _s(2)), joint='curve')
    base.alpha_composite(layer)


def _dashed_vline(draw, x, y0, y1):
    y = y0 + _sy(10)
    while y < y1 - _sy(10):
        draw.line((x, y, x, y + _sy(6)), fill='#D8DCE3', width=max(1, _s(1)))
        y += _sy(12)


def _circle_icon(img, draw, cx, cy, diameter, inner, outer, color, icon_fn):
    circle = _radial_circle(diameter, inner, outer)
    img.alpha_composite(circle, (cx - diameter // 2, cy - diameter // 2))
    pad = max(8, diameter // 4)
    icon_fn(draw, (cx - diameter // 2 + pad, cy - diameter // 2 + pad,
                   cx + diameter // 2 - pad, cy + diameter // 2 - pad), color)


def _draw_title_clipped(draw, x, y, max_w, title, color, max_sz=16, min_sz=9):
    font, sz = _fit_font(draw, title, max_w, _sf(max_sz), _sf(min_sz), 'semibold')
    if _text_len(draw, title, font) <= max_w:
        draw.text((x, y), title, font=font, fill=color, anchor='lt')
        return sz + _sy(2)
    words = title.split()
    if len(words) >= 2:
        mid = len(words) // 2
        line1 = ' '.join(words[:mid])
        line2 = ' '.join(words[mid:])
        f1, s1 = _fit_font(draw, line1, max_w, _sf(max_sz), _sf(min_sz), 'semibold')
        f2, s2 = _fit_font(draw, line2, max_w, _sf(max_sz), _sf(min_sz), 'semibold')
        draw.text((x, y), line1, font=f1, fill=color, anchor='lt')
        draw.text((x, y + s1 + _sy(1)), line2, font=f2, fill=color, anchor='lt')
        return s1 + s2 + _sy(3)
    draw.text((x, y), title, font=font, fill=color, anchor='lt')
    return sz + _sy(2)


def _icon_pin(draw, box, color):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    hy = y0 + (y1 - y0) * 0.36
    r = min(x1 - x0, y1 - y0) * 0.24
    lw = max(2, int(r * 0.32))
    draw.ellipse((cx - r, hy - r, cx + r, hy + r), outline=color, width=lw)
    draw.ellipse((cx - r * 0.28, hy - r * 0.28, cx + r * 0.28, hy + r * 0.28), fill=color)
    draw.polygon([(cx, y1 - 1), (cx - r * 0.75, hy + r * 0.52), (cx + r * 0.75, hy + r * 0.52)], fill=color)


def _icon_calendar(draw, box, color):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    body = (x0 + w * 0.12, y0 + h * 0.22, x1 - w * 0.12, y1 - h * 0.08)
    lw = max(2, int(min(w, h) * 0.1))
    _rounded(draw, body, int(min(w, h) * 0.14), outline=color, width=lw)
    draw.line((body[0], y0 + h * 0.42, body[2], y0 + h * 0.42), fill=color, width=lw)
    for px in (x0 + w * 0.32, x1 - w * 0.32):
        draw.line((px, y0 + h * 0.12, px, y0 + h * 0.28), fill=color, width=lw)


def _icon_bars_arrow(draw, box, color):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    lw = max(3, int(min(w, h) * 0.08))
    base = y1 - h * 0.14
    bar_w = w * 0.16
    for idx, height in enumerate((0.28, 0.46, 0.68)):
        bx0 = x0 + w * (0.14 + idx * 0.24)
        _rounded(
            draw,
            (bx0, base - h * height, bx0 + bar_w, base),
            int(bar_w * 0.25),
            fill=color,
        )
    draw.line(
        [(x0 + w * 0.12, y0 + h * 0.45), (x0 + w * 0.5, y0 + h * 0.32), (x1 - w * 0.16, y0 + h * 0.12)],
        fill=color,
        width=lw,
        joint='curve',
    )
    draw.line((x1 - w * 0.16, y0 + h * 0.12, x1 - w * 0.17, y0 + h * 0.34), fill=color, width=lw)
    draw.line((x1 - w * 0.16, y0 + h * 0.12, x1 - w * 0.38, y0 + h * 0.12), fill=color, width=lw)


def _icon_bed(draw, box, color):
    """Simple hotel/bed glyph for HOTEL card."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    lw = max(2, int(min(w, h) * 0.1))
    # headboard / pillow
    _rounded(draw, (x0 + w * 0.12, y0 + h * 0.22, x0 + w * 0.42, y0 + h * 0.48), int(min(w, h) * 0.08), outline=color, width=lw)
    # mattress
    _rounded(draw, (x0 + w * 0.1, y0 + h * 0.5, x1 - w * 0.1, y0 + h * 0.72), int(min(w, h) * 0.08), outline=color, width=lw)
    # legs
    draw.line((x0 + w * 0.18, y0 + h * 0.72, x0 + w * 0.18, y1 - h * 0.12), fill=color, width=lw)
    draw.line((x1 - w * 0.18, y0 + h * 0.72, x1 - w * 0.18, y1 - h * 0.12), fill=color, width=lw)


def _icon_fork(draw, box, color):
    """Simple plate/fork glyph for RESTAURANT card."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    lw = max(2, int(min(w, h) * 0.1))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    r = min(w, h) * 0.34
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=lw)
    # fork tines hint on left
    fx = x0 + w * 0.22
    for dx in (-0.08, 0, 0.08):
        draw.line((fx + w * dx, y0 + h * 0.28, fx + w * dx, y0 + h * 0.52), fill=color, width=max(1, lw - 1))
    draw.line((fx, y0 + h * 0.52, fx, y1 - h * 0.22), fill=color, width=lw)


def _icon_glass(draw, box, color):
    """Simple glass glyph for BAR card."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    lw = max(2, int(min(w, h) * 0.1))
    top = (x0 + w * 0.22, y0 + h * 0.18, x1 - w * 0.22, y0 + h * 0.22)
    draw.line((top[0], top[1], top[2], top[3]), fill=color, width=lw)
    draw.line((top[0], top[1], x0 + w * 0.34, y0 + h * 0.62), fill=color, width=lw)
    draw.line((top[2], top[3], x1 - w * 0.34, y0 + h * 0.62), fill=color, width=lw)
    draw.line((x0 + w * 0.34, y0 + h * 0.62, x1 - w * 0.34, y0 + h * 0.62), fill=color, width=lw)
    draw.line(((x0 + x1) / 2, y0 + h * 0.62, (x0 + x1) / 2, y1 - h * 0.14), fill=color, width=lw)
    draw.line((x0 + w * 0.34, y1 - h * 0.14, x1 - w * 0.34, y1 - h * 0.14), fill=color, width=lw)


def _icon_calc(draw, box, color):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    body = (x0 + w * 0.1, y0 + h * 0.1, x1 - w * 0.1, y1 - h * 0.1)
    lw = max(2, int(min(w, h) * 0.09))
    _rounded(draw, body, int(min(w, h) * 0.12), outline=color, width=lw)
    dot = max(2, int(min(w, h) * 0.065))
    for c, r in ((0.28, 0.54), (0.5, 0.54), (0.72, 0.54), (0.28, 0.74), (0.5, 0.74), (0.72, 0.74)):
        px, py = x0 + w * c, y0 + h * r
        draw.ellipse((px - dot, py - dot, px + dot, py + dot), fill=color)


def _draw_rupee_amount(draw, x, y, max_x, amount, max_sz, min_sz, fill, weight='bold', underline=False):
    neg, digits = _inr_parts(amount)
    minus = '-' if neg else ''
    probe = f'{minus}₹{digits}'
    font, sz = _fit_amount_font(draw, probe, max(30, max_x - x), max_sz, min_sz, weight)
    cur = x
    if neg:
        minus_font = _font(sz, weight)
        draw.text((cur, y), minus, font=minus_font, fill=fill, anchor='lm')
        cur += int(_text_len(draw, minus, minus_font)) + max(2, sz // 14)
    draw.text((cur, y), '₹', font=font, fill=fill, anchor='lm')
    rupee_w = int(_text_len(draw, '₹', font))
    if underline:
        draw.line((cur, y + sz // 2 + _sy(4), cur + rupee_w, y + sz // 2 + _sy(4)), fill=PRIMARY, width=max(2, _s(3)))
    cur += rupee_w + max(3, sz // 12)
    draw.text((cur, y), digits, font=font, fill=fill, anchor='lm')


def _draw_badge(img, draw, right_x, cy, pct, vs_label):
    _, _, bg, _ = _pct_meta(pct)
    pw, ph = _s(_PILL_W), _sy(_PILL_H)
    x0, y0 = right_x - pw, cy - ph // 2
    x1, y1 = right_x, y0 + ph
    _card_shadow(img, (x0, y0, x1, y1), _s(18), dy=_sy(4), blur=_s(8), alpha=8)
    _rounded(draw, (x0, y0, x1, y1), _s(18), fill=bg)
    _draw_trend_text(draw, x0 + pw / 2, y0 + ph * 0.36, pct, font=_font(_sf(28), 'bold'), anchor='mm')
    draw.text((x0 + pw / 2, y0 + ph * 0.78), vs_label, font=_font(_sf(16), 'medium'), fill=MUTED, anchor='mm')


def _draw_header(img, draw, location, date_label, weekday, x0, x1, y0, h):
    y1 = y0 + h
    third = (x1 - x0) // 3
    s0, s1, s2 = x0, x0 + third, x0 + 2 * third
    logo_h = _s(_LOGO_H)
    mid = (y0 + y1) // 2
    if not _paste_logo(img, (s0 + _s(4), mid - logo_h // 2, s1 - _s(16), mid + logo_h // 2)):
        draw.text((s0 + _s(8), mid), 'Hotel Bell Elite', font=_font(_sf(20), 'bold'), fill=TEXT, anchor='lm')

    _dashed_vline(draw, s1, y0, y1)
    pin_x = s1 + (s2 - s1) // 2 - _s(110)
    _icon_pin(draw, (pin_x - _s(24), mid - _s(24), pin_x + _s(24), mid + _s(24)), PRIMARY)
    loc_font, _ = _fit_font(draw, location, (s2 - s1) - _s(64), _sf(36), _sf(18), 'bold')
    draw.text((pin_x + _s(32), mid), location, font=loc_font, fill=TEXT, anchor='lm')

    _dashed_vline(draw, s2, y0, y1)
    cal_tile = (s2 + _s(70), mid - _s(34), s2 + _s(138), mid + _s(34))
    _rounded(draw, cal_tile, _s(14), fill=PRIMARY_SOFT)
    _icon_calendar(draw, (cal_tile[0] + _s(13), cal_tile[1] + _s(13), cal_tile[2] - _s(13), cal_tile[3] - _s(13)), PRIMARY)
    tx = cal_tile[2] + _s(18)
    draw.text((tx, mid - _sy(15)), date_label, font=_font(_sf(21), 'bold'), fill=TEXT, anchor='lm')
    draw.text((tx, mid + _sy(15)), weekday, font=_font(_sf(17), 'medium'), fill=MUTED, anchor='lm')


def _draw_hero(img, draw, box, amount, trend, vs_label):
    x0, y0, x1, y1 = box
    _card_shadow(img, box, _s(_INNER_RADIUS), dy=_sy(10), blur=_s(18), alpha=14)
    draw = ImageDraw.Draw(img)
    _rounded(draw, box, _s(_INNER_RADIUS), fill=TINT_HERO, outline='#DDD6FE', width=max(1, _s(1)))
    grad = _gradient_tile(x1 - x0, y1 - y0, '#FCFBFF', '#FFFFFF')
    mask = Image.new('L', (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), radius=_s(_INNER_RADIUS), fill=255)
    img.paste(grad, (x0, y0), mask)
    _hero_waves(img, box)
    draw = ImageDraw.Draw(img)

    pad = _s(_CARD_INNER_PAD)
    cy = (y0 + y1) // 2
    cd = _s(_HERO_CIRCLE)
    icon_cx = x0 + pad + cd // 2
    _circle_icon(img, draw, icon_cx, cy, cd, '#F8F5FF', '#DDD6FE', PRIMARY, _icon_bars_arrow)

    tx = icon_cx + cd // 2 + _s(54)
    draw.text((tx, cy - _sy(48)), 'TOTAL SALES', font=_font(_sf(27), 'bold'), fill=PRIMARY, anchor='lm')
    reserve = _s(_PILL_W) + pad + _s(10)
    _draw_rupee_amount(draw, tx, cy + _sy(26), x1 - pad - reserve, amount, _sf(78), _sf(42), TEXT, 'extrabold', underline=True)
    if trend is not None:
        pill_x = x1 - pad - _s(_PILL_W)
        draw.line((pill_x - _s(56), y0 + _sy(44), pill_x - _s(56), y1 - _sy(44)), fill='#D8DEE8', width=max(1, _s(1)))
        _draw_badge(img, draw, x1 - pad, cy, trend, vs_label)


def _draw_summary(img, draw, box, tint, accent, circle_inner, circle_outer, icon_fn, title, amount, trend):
    x0, y0, x1, y1 = box
    _card_shadow(img, box, _s(_INNER_RADIUS), dy=_sy(6), blur=_s(12), alpha=10)
    draw = ImageDraw.Draw(img)
    _rounded(draw, box, _s(_INNER_RADIUS), fill=tint, outline='#E2E8F0', width=max(1, _s(1)))
    bar_h = _sy(_ACCENT_LINE)
    draw.rectangle((x0, y1 - bar_h, x1, y1), fill=accent)

    pad = _s(24)
    bottom = y1 - bar_h
    icon_sz = _s(_SUMMARY_ICON)
    icon_cx = x0 + pad + icon_sz // 2
    icon_cy = y0 + (bottom - y0) // 2
    _circle_icon(img, draw, icon_cx, icon_cy, icon_sz, circle_inner, circle_outer, accent, icon_fn)

    tx = x0 + pad + icon_sz + _s(22)
    text_w = max(40, x1 - tx - pad)
    ty = y0 + _sy(34)
    _draw_title_clipped(draw, tx, ty, text_w, title, accent, max_sz=19, min_sz=12)
    _draw_rupee_amount(draw, tx, y0 + _sy(82), x1 - pad, amount, _sf(42), _sf(24), TEXT, 'bold')
    _draw_trend_text(draw, tx, y0 + _sy(118), trend, font=_font(_sf(24), 'bold'), anchor='lm')


def _draw_difference(img, draw, box, amount, trend, vs_label):
    x0, y0, x1, y1 = box
    _card_shadow(img, box, _s(_INNER_RADIUS), dy=_sy(6), blur=_s(12), alpha=10)
    draw = ImageDraw.Draw(img)
    _rounded(draw, box, _s(_INNER_RADIUS), fill=TINT_NET, outline='#A7F3D0', width=max(1, _s(1)))
    bar_h = _sy(_ACCENT_LINE)
    draw.rectangle((x0, y1 - bar_h, x1, y1), fill=SUCCESS)

    pad = _s(_CARD_INNER_PAD)
    cy = (y0 + y1 - bar_h) // 2
    cd = _s(_DIFF_CIRCLE)
    icon_cx = x0 + pad + cd // 2
    _circle_icon(img, draw, icon_cx, cy, cd, '#ECFDF5', '#D1FAE5', SUCCESS, _icon_calc)

    tx = icon_cx + cd // 2 + _s(34)
    draw.text((tx, cy - _sy(25)), 'DIFFERENCE', font=_font(_sf(20), 'bold'), fill=TEXT, anchor='lm')
    reserve = _s(_PILL_W) + pad + _s(10)
    _draw_rupee_amount(draw, tx, cy + _sy(22), x1 - pad - reserve, amount, _sf(55), _sf(28), SUCCESS, 'bold')
    if trend is not None:
        pill_x = x1 - pad - _s(_PILL_W)
        draw.line((pill_x - _s(58), y0 + _sy(34), pill_x - _s(58), y1 - bar_h - _sy(34)), fill='#D8DEE8', width=max(1, _s(1)))
        _draw_badge(img, draw, x1 - pad, cy, trend, vs_label)


def _draw_footer(draw, x0, x1, y0, h):
    y1 = y0 + h
    mid = (y0 + y1) // 2
    label = 'All values are in INR'
    font = _font(_sf(13), 'medium')
    lw = int(_text_len(draw, label, font))
    cx = (x0 + x1) // 2
    gap = _s(12)
    line_y = mid
    draw.line((x0, line_y, cx - lw // 2 - gap, line_y), fill='#E5E7EB', width=max(1, _s(1)))
    draw.text((cx, mid), label, font=font, fill=MUTED, anchor='mm')
    draw.line((cx + lw // 2 + gap, line_y, x1, line_y), fill='#E5E7EB', width=max(1, _s(1)))


def collect_daily_sales(
    conn,
    sales_date: str,
    *,
    outlet_totals: dict[str, float] | None = None,
    prior_outlet_totals: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Outlet totals for the WhatsApp image (Hotel / Restaurant / Bar / Total).

    By default uses the same SU ∪ invoice merge as the template body
    (``collect_sales_report_metrics``). Optional ``outlet_totals`` /
    ``prior_outlet_totals`` keep the CLI/API stable for callers that already
    computed merged amounts (keys: hotel, restaurant, bar).
    """
    day = str(sales_date)[:10]

    def _merged_outlet_totals(for_day: str) -> tuple[float, float, float, float, dict, dict, dict]:
        # Lazy import avoids circular import with hotel_sales_whatsapp_report.
        from hotel_sales_whatsapp_report import collect_sales_report_metrics

        metrics = collect_sales_report_metrics(conn, for_day)
        per = metrics.get('per_outlet') or {}
        hotel_vals = (per.get('Hotel') or {}).get('values') or {}
        rest_vals = (per.get('Restaurant') or {}).get('values') or {}
        bar_vals = (per.get('Bar') or {}).get('values') or {}
        h = round(float(hotel_vals.get('total_sales') or 0), 2)
        r = round(float(rest_vals.get('total_sales') or 0), 2)
        b = round(float(bar_vals.get('total_sales') or 0), 2)
        return h, r, b, round(h + r + b, 2), hotel_vals, rest_vals, bar_vals

    def _from_override(ov: dict[str, float]) -> tuple[float, float, float, float]:
        h = round(float(ov.get('hotel') or 0), 2)
        r = round(float(ov.get('restaurant') or 0), 2)
        b = round(float(ov.get('bar') or 0), 2)
        return h, r, b, round(h + r + b, 2)

    if outlet_totals is not None:
        h, r, b, total = _from_override(outlet_totals)
        hotel = restaurant = bar = {}
    else:
        h, r, b, total, hotel, restaurant, bar = _merged_outlet_totals(day)

    prior_hotel = prior_restaurant = prior_bar = prior_total = None
    prior_date = None
    dt = _parse_sales_date(day)
    if dt is not None:
        prior_date = (dt - timedelta(days=1)).strftime('%Y-%m-%d')
        if prior_outlet_totals is not None:
            prior_hotel, prior_restaurant, prior_bar, prior_total = _from_override(prior_outlet_totals)
        else:
            prior_hotel, prior_restaurant, prior_bar, prior_total, _, _, _ = _merged_outlet_totals(prior_date)

    weekday = ''
    if dt is not None:
        weekday = dt.strftime('%A')

    return {
        'sales_date': day,
        'date_label': format_report_date(day),
        'weekday': weekday,
        'location': 'Hotel Bell Elite',
        'hotel': h,
        'restaurant': r,
        'bar': b,
        'total': total,
        'prior_date': prior_date,
        'prior_hotel': prior_hotel,
        'prior_restaurant': prior_restaurant,
        'prior_bar': prior_bar,
        'prior_total': prior_total,
        'trend_hotel': _pct_change(h, prior_hotel),
        'trend_restaurant': _pct_change(r, prior_restaurant),
        'trend_bar': _pct_change(b, prior_bar),
        'trend_total': _pct_change(total, prior_total),
        'hotel_detail': hotel,
        'restaurant_detail': restaurant,
        'bar_detail': bar,
    }


def generate_daily_sales_report_image(
    payload: dict[str, Any],
    *,
    output_path: str | Path | None = None,
    logo_path: str | None = None,
) -> str:
    """Render Textile-style executive sales dashboard for WhatsApp. Returns absolute path."""
    global W, H, _SX, _SY, _BRAND_LOGO

    if logo_path:
        # Allow caller override without mutating cache permanently for default path.
        _BRAND_LOGO = False
        # Temporarily point via env-less path by monkeypatching load: open override into cache.
        try:
            logo = Image.open(logo_path).convert('RGBA')
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)
            _BRAND_LOGO = logo
        except OSError:
            _BRAND_LOGO = False

    ew, eh = _report_export_size()
    ss = _supersample_factor()
    W, H = ew * ss, eh * ss
    _SX, _SY = W / _DESIGN_W, H / _DESIGN_H

    hotel = float(payload.get('hotel') or 0)
    restaurant = float(payload.get('restaurant') or 0)
    bar = float(payload.get('bar') or 0)
    total = float(payload.get('total') or (hotel + restaurant + bar))
    difference = float(payload.get('difference') if payload.get('difference') is not None else 0)
    date_label = _clean_supporting_text(payload.get('date_label'), format_report_date(payload.get('sales_date')))
    weekday = _clean_supporting_text(payload.get('weekday'), _weekday_from_label(date_label))
    location = _clean_supporting_text(payload.get('location'), 'Hotel Bell Elite')
    vs_label = _clean_supporting_text(payload.get('vs_label'), 'vs yesterday')
    if vs_label and not vs_label.lower().startswith('vs '):
        vs_label = f'vs {vs_label}'

    trend_total = payload.get('trend_total')
    trend_hotel = payload.get('trend_hotel')
    trend_restaurant = payload.get('trend_restaurant')
    trend_bar = payload.get('trend_bar')
    trend_difference = payload.get('trend_difference')
    if trend_total is None and payload.get('prior_total') is not None:
        trend_total = _pct_change(total, payload.get('prior_total'))
    if trend_hotel is None and payload.get('prior_hotel') is not None:
        trend_hotel = _pct_change(hotel, payload.get('prior_hotel'))
    if trend_restaurant is None and payload.get('prior_restaurant') is not None:
        trend_restaurant = _pct_change(restaurant, payload.get('prior_restaurant'))
    if trend_bar is None and payload.get('prior_bar') is not None:
        trend_bar = _pct_change(bar, payload.get('prior_bar'))
    if trend_difference is None and payload.get('prior_difference') is not None:
        trend_difference = _pct_change(difference, payload.get('prior_difference'))

    img = Image.new('RGBA', (W, H), BG)
    draw = ImageDraw.Draw(img)

    margin = _s(_OUTER_MARGIN)
    outer = (margin, margin, W - margin, H - margin)
    _card_shadow(img, outer, _s(_OUTER_RADIUS), dy=_sy(10), blur=_s(20), alpha=16)
    draw = ImageDraw.Draw(img)
    _rounded(draw, outer, _s(_OUTER_RADIUS), fill=SURFACE)

    pad = _s(_CARD_INNER_PAD)
    gap = _s(_SECTION_GAP)
    card_gap = _s(_CARD_GAP)
    x0, x1 = outer[0] + pad, outer[2] - pad
    y = outer[1] + pad

    _draw_header(img, draw, location, date_label, weekday, x0, x1, y, _sy(_HEADER_H))
    y += _sy(_HEADER_H) + gap

    hero = (x0, y, x1, y + _sy(_HERO_H))
    _draw_hero(img, draw, hero, total, trend_total, vs_label)
    y += _sy(_HERO_H) + gap

    cw = (x1 - x0 - card_gap * 2) // 3
    specs = [
        ('HOTEL', hotel, trend_hotel, HOTEL, TINT_HOTEL, '#EEF5FF', '#DBEAFE', _icon_bed),
        ('RESTAURANT', restaurant, trend_restaurant, RESTAURANT, TINT_RESTAURANT, '#FFF4E8', '#FFE8D1', _icon_fork),
        ('BAR', bar, trend_bar, BAR, TINT_BAR, '#F3E8FF', '#E9D5FF', _icon_glass),
    ]
    for i, (title, amt, tr, accent, tint, ci, co, icon) in enumerate(specs):
        bx0 = x0 + i * (cw + card_gap)
        box = (bx0, y, bx0 + cw, y + _sy(_SUMMARY_H))
        _draw_summary(img, draw, box, tint, accent, ci, co, icon, title, amt, tr)

    y += _sy(_SUMMARY_H) + gap
    net = (x0, y, x1, y + _sy(_DIFF_H))
    _draw_difference(img, draw, net, difference, trend_difference, vs_label)
    y += _sy(_DIFF_H) + gap

    draw = ImageDraw.Draw(img)
    _draw_footer(draw, x0, x1, y, _sy(_FOOTER_H))

    if output_path is None:
        stamp = str(payload.get('sales_date') or datetime.now().strftime('%Y-%m-%d'))
        output_path = (
            Path(__file__).resolve().parent
            / 'static'
            / 'generated'
            / 'whatsapp_reports'
            / f'HBE_Daily_Sales_{stamp}.jpg'
        )
    out_path = Path(output_path)
    if not str(out_path).lower().endswith(('.png', '.jpg', '.jpeg')):
        out_path = Path(f'{out_path}{report_image_extension()}')
    _save_report_image(img, str(out_path))
    return str(out_path.resolve())


if __name__ == '__main__':
    import sqlite3

    import db as db_mod

    date = os.environ.get('SALES_REPORT_DATE') or '2026-09-07'
    conn = db_mod.get_db()
    conn.row_factory = sqlite3.Row
    try:
        data = collect_daily_sales(conn, date)
    finally:
        conn.close()
    path = generate_daily_sales_report_image(data)
    print(data)
    print(path)
