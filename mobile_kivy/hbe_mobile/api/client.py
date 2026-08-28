"""HTTP client: Flask session cookies + CSRF. Never imports Flask internals."""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from hbe_mobile import config


class ApiError(Exception):
    def __init__(self, message: str, *, status_code: int = 0, payload: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload


class SessionExpired(ApiError):
    pass


_SCRIPT_JSON_RE = re.compile(
    r'<script[^>]*\bid=["\'](?P<id>[^"\']+)["\'][^>]*type=["\']application/json["\'][^>]*>'
    r"(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

_HISTORY_ROW_RE = re.compile(
    r'<tr[^>]*class="[^"]*cp-history-row[^"]*"[^>]*data-payment-id="(?P<id>\d+)"[^>]*>'
    r"(?P<html>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)

_OPTION_RE = re.compile(
    r'<option[^>]*value=["\'](?P<value>[^"\']*)["\'][^>]*>(?P<label>.*?)</option>',
    re.IGNORECASE | re.DOTALL,
)


def extract_script_json(html: str, script_id: str) -> Any:
    """Pull JSON from <script id="..." type="application/json"> embeds."""
    for match in _SCRIPT_JSON_RE.finditer(html or ""):
        if match.group("id") == script_id:
            raw = match.group("body").strip()
            if not raw:
                return None
            return json.loads(raw)
    return None


def extract_select_options(html: str, select_id: str) -> list[tuple[str, str]]:
    """Parse <select id=...> options as (value, label) pairs."""
    pattern = re.compile(
        rf'<select[^>]*\bid=["\']{re.escape(select_id)}["\'][^>]*>(?P<body>.*?)</select>',
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(html or "")
    if not m:
        return []
    options = []
    for opt in _OPTION_RE.finditer(m.group("body")):
        value = opt.group("value").strip()
        label = re.sub(r"<[^>]+>", "", opt.group("label")).strip()
        if value:
            options.append((value, label))
    return options


def parse_history_rows(html: str) -> list[dict[str, Any]]:
    """Best-effort parse of Approvals history table rows (no JSON embed on web)."""
    rows: list[dict[str, Any]] = []
    for match in _HISTORY_ROW_RE.finditer(html or ""):
        payment_id = int(match.group("id"))
        chunk = match.group("html")
        amounts = re.findall(r'data-amount="([^"]+)"', chunk)
        names = re.findall(r'class="pl-name">([^<]+)', chunk)
        dates = re.findall(r'class="pl-col-date"[^>]*data-sort-value="([^"]*)"', chunk)
        accounts = re.findall(r'data-sort-value="([^"]*)"[^>]*>', chunk)
        total = 0.0
        if amounts:
            try:
                total = float(amounts[-1])
            except ValueError:
                total = 0.0
        rows.append(
            {
                "id": payment_id,
                "supplier_name": names[0] if names else "",
                "total_amount": total,
                "payment_date": dates[0] if dates else "",
                "verification_account": "",
                "allocation_count": 0,
                "expense_codes": "",
            }
        )
        # Prefer dedicated account cell when present in verification history.
        if len(accounts) >= 2:
            rows[-1]["verification_account"] = accounts[-2] if accounts else ""
    return rows


class ApiClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or config.get_api_base_url()).rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=config.REQUEST_TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": "HBE-Mobile-Kivy/0.1"},
        )
        self.username = ""
        self.authenticated = False

    def close(self) -> None:
        self._client.close()

    def set_base_url(self, url: str) -> None:
        url = (url or "").rstrip("/")
        if url == self.base_url:
            return
        cookies = dict(self._client.cookies)
        self._client.close()
        self.base_url = url
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=config.REQUEST_TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": "HBE-Mobile-Kivy/0.1"},
            cookies=cookies,
        )
        config.set_api_base_url(url)

    def absolute_url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def csrf_token(self) -> str:
        return (self._client.cookies.get(config.CSRF_COOKIE) or "").strip()

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self._client.cookies.items())

    def _ensure_csrf(self) -> None:
        if self.csrf_token():
            return
        # Hitting an authenticated page (or login) seeds hbe_csrf via Set-Cookie.
        try:
            self._client.get("/home")
        except httpx.HTTPError:
            pass

    def _auth_headers(self, *, unsafe: bool) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json, text/html;q=0.9"}
        if unsafe:
            token = self.csrf_token()
            if token:
                headers[config.CSRF_HEADER] = token
                headers["X-CSRF-Token"] = token
            headers["X-Requested-With"] = "XMLHttpRequest"
        return headers

    def _raise_if_login_redirect(self, response: httpx.Response) -> None:
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location") or ""
            if location.rstrip("/").endswith("/login") or location in ("/", "/login"):
                self.authenticated = False
                raise SessionExpired("Session expired. Please sign in again.", status_code=response.status_code)
            # Follow one hop for non-login redirects when caller uses follow manually
        if response.status_code == 401:
            self.authenticated = False
            raise SessionExpired("Unauthorized", status_code=401)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: Any = None,
        params: Optional[dict] = None,
        follow_redirects: bool = True,
        expect_json: bool = False,
    ) -> httpx.Response:
        method_u = method.upper()
        unsafe = method_u in {"POST", "PUT", "PATCH", "DELETE"}
        if unsafe and self.authenticated:
            self._ensure_csrf()
        headers = self._auth_headers(unsafe=unsafe)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        kwargs: dict[str, Any] = {
            "method": method_u,
            "url": path,
            "headers": headers,
            "params": params,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data

        response = self._client.request(**kwargs)
        # Seed CSRF from any Set-Cookie on responses
        if response.status_code in (301, 302, 303, 307, 308) and follow_redirects:
            location = response.headers.get("location") or ""
            if location.rstrip("/").endswith("/login") or location in ("/", "/login"):
                self._raise_if_login_redirect(response)
            # Relative redirect
            next_path = location
            if location.startswith("http"):
                if not location.startswith(self.base_url):
                    return response
                next_path = location[len(self.base_url) :] or "/"
            response = self._client.request(
                "GET",
                next_path,
                headers=self._auth_headers(unsafe=False),
            )

        self._raise_if_login_redirect(response)
        if expect_json and response.status_code >= 400:
            try:
                payload = response.json()
            except Exception:
                payload = None
            msg = ""
            if isinstance(payload, dict):
                msg = str(payload.get("error") or payload.get("message") or "")
            raise ApiError(msg or f"HTTP {response.status_code}", status_code=response.status_code, payload=payload)
        return response

    def get_json(self, path: str, *, params: Optional[dict] = None) -> Any:
        response = self.request("GET", path, params=params, expect_json=True)
        if "application/json" not in (response.headers.get("content-type") or ""):
            # May be HTML login — treat as session loss if looks like login page
            text = response.text or ""
            if 'class="login-page"' in text or "/login" in text[:500]:
                raise SessionExpired("Session expired")
            raise ApiError("Expected JSON response", status_code=response.status_code)
        return response.json()

    def post_json(self, path: str, body: dict) -> Any:
        response = self.request("POST", path, json_body=body, expect_json=True)
        try:
            return response.json()
        except Exception as exc:
            raise ApiError("Invalid JSON response", status_code=response.status_code) from exc

    def get_text(self, path: str, *, params: Optional[dict] = None) -> str:
        response = self.request("GET", path, params=params)
        return response.text or ""

    def login(
        self,
        username: str,
        password: str,
        *,
        captcha: str = "",
    ) -> dict[str, Any]:
        # GET login first for cookies
        self._client.get("/login")
        form = {"username": username, "password": password}
        if captcha:
            form["captcha"] = captcha
        response = self._client.post(
            "/login",
            data=form,
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        location = response.headers.get("location") or ""
        if response.status_code in (301, 302, 303, 307, 308):
            if "/change-password" in location:
                self.authenticated = True
                self.username = username
                return {"ok": True, "must_change_password": True}
            if "/home" in location or location.endswith("/home"):
                self.authenticated = True
                self.username = username
                # Follow to seed CSRF cookie
                self.request("GET", "/home", follow_redirects=True)
                return {"ok": True, "must_change_password": False}
            # Other redirects — follow once
            next_path = location
            if location.startswith(self.base_url):
                next_path = location[len(self.base_url) :] or "/"
            elif location.startswith("http"):
                return {"ok": False, "error": f"Unexpected redirect: {location}", "captcha_required": False}
            followed = self._client.get(next_path, follow_redirects=True)
            if "/home" in str(followed.url):
                self.authenticated = True
                self.username = username
                return {"ok": True, "must_change_password": False}

        html = response.text or ""
        captcha_required = 'name="captcha"' in html or "captcha" in html.lower()
        error = "Invalid username or password."
        err_match = re.search(
            r'class="[^"]*login-error[^"]*"[^>]*>(.*?)</',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if err_match:
            error = re.sub(r"<[^>]+>", "", err_match.group(1)).strip() or error
        flash_match = re.search(r'class="[^"]*flash[^"]*"[^>]*>(.*?)</', html, re.I | re.S)
        if flash_match:
            error = re.sub(r"<[^>]+>", "", flash_match.group(1)).strip() or error
        self.authenticated = False
        return {"ok": False, "error": error, "captcha_required": captcha_required}

    def fetch_captcha_png(self) -> bytes:
        response = self._client.get("/login/captcha")
        response.raise_for_status()
        return response.content

    def logout(self) -> None:
        try:
            if self.authenticated:
                self._ensure_csrf()
                self.request("POST", "/logout", data={}, follow_redirects=True)
        except (ApiError, httpx.HTTPError):
            pass
        finally:
            self.authenticated = False
            self.username = ""
            self._client.cookies.clear()
