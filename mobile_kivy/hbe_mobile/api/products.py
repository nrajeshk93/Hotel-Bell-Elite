"""Product Master client — list via products-lite; mutate via form posts."""

from __future__ import annotations

from typing import Optional

from hbe_mobile.api.client import ApiClient, ApiError, extract_select_options
from hbe_mobile.models import Product


def list_products(
    client: ApiClient,
    *,
    q: str = "",
    outlet: str = "all",
) -> list[Product]:
    params = {"q": q, "outlet": outlet or "all"}
    data = client.get_json("/stores/api/products-lite", params=params)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed"))
    rows = data.get("products") or []
    return [Product.from_api(r) for r in rows if isinstance(r, dict)]


def list_categories(client: ApiClient) -> list[tuple[str, str]]:
    html = client.get_text("/stores/product-master")
    # Prefer category select on product form
    for select_id in ("st-product-category", "category_id", "st-pm-category"):
        opts = extract_select_options(html, select_id)
        if opts:
            return opts
    # Fallback: any select whose name is category_id
    import re

    m = re.search(
        r'<select[^>]*name=["\']category_id["\'][^>]*>(.*?)</select>',
        html or "",
        re.I | re.S,
    )
    if not m:
        return []
    from hbe_mobile.api.client import _OPTION_RE

    out = []
    for opt in _OPTION_RE.finditer(m.group(1)):
        value = opt.group("value").strip()
        label = re.sub(r"<[^>]+>", "", opt.group("label")).strip()
        if value:
            out.append((value, label))
    return out


def save_product(
    client: ApiClient,
    *,
    name: str,
    category_id: str,
    outlet: str,
    unit: str = "kg",
    approximate_price: str = "",
    product_id: Optional[int] = None,
) -> None:
    data = {
        "action": "save_product",
        "product_id": str(product_id or ""),
        "category_id": str(category_id),
        "name": name,
        "outlet": outlet,
        "variant_qty": ["1"],
        "variant_unit": [unit or "kg"],
        "variant_approximate_price": [approximate_price or "0"],
    }
    response = client.request("POST", "/stores/product-master", data=data, follow_redirects=True)
    text = response.text or ""
    if response.status_code >= 400:
        raise ApiError(f"Save failed ({response.status_code})")
    lowered = text.lower()
    if "product name is required" in lowered or "choose a category" in lowered:
        raise ApiError("Product validation failed on server")
    if "that product already exists" in lowered:
        raise ApiError("That product already exists in this category.")


def delete_product(client: ApiClient, product_id: int) -> None:
    response = client.request(
        "GET",
        f"/stores/product-master/{int(product_id)}/delete",
        follow_redirects=True,
    )
    if response.status_code >= 400:
        raise ApiError(f"Delete failed ({response.status_code})")
