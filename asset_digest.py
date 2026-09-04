"""Content-hash digest for Hotel Bell Elite static assets.

HTML responses get `?v=<content-hash>` so Cloudflare cannot pin an old file.
The in-memory digest rebuilds when static files or templates change on disk
(no gunicorn restart required). CACHE_VERSION includes those hashes, the
service-worker script, and a source fingerprint, so any UI change installs a
new worker. Stale `?v=` URLs are served no-store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading

_LOCK = threading.Lock()
_DIGEST = None  # type: dict | None
_FINGERPRINT = None  # type: str | None

# Python/templates/static mtimes. Skip vendor and phone-app trees.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "android",
    "mobile_kivy",
    "tests",
    "scripts",
}

HASH_LEN = 10
CACHE_PREFIX = "hbe-app-"

# Offline shell + POS/workspace assets the SW may precache. Session HTML
# (/home, /point-of-sale/invoice, /login) is NOT in this list — those pages
# are per-user and must not be pinned at install time.
PRECACHE_STATIC = (
    "offline_login.html",
    "offline_auth.js",
    "login_premium.css",
    "login_hero.jpg",
    "hbe_mark_sm.png",
    "hbe_mark_form_sm.png",
    "hbe_logo_sm.png",
    "hbe_logo_sm.webp",
    "manifest.webmanifest",
    "de_workspace_shell.css",
    "hbe_home_premium.css",
    "ep_form_listbox.css",
    "hbe_table_scroll.css",
    "hbe_kpi.css",
    "hbe_app_toast.css",
    "reports_page_scroll.css",
    "pos_invoice.css",
    "pos_invoice.js",
    "pos_offline.js",
    "hbe_offline_sync.js",
    "ep_form_listbox.js",
    "de_workspace_nav.js",
    "de_workspace_transitions.js",
    "hbe_table_scroll.js",
    "hbe_app_toast.js",
    "print_agent.js",
    "de_pwa.js",
    "pwa-icon-192.png",
    "pwa-icon-512.png",
    "favicon-32.png",
)

ALIAS_PATHS = (
    "offline_auth.js",
    "de_pwa.js",
    "offline_login.html",
)

_HASH_EXTS = (".js", ".css", ".html", ".webmanifest")
_STATIC_URL_RE = re.compile(
    r"(/static/([A-Za-z0-9_./\-]+?\.(?:js|css|html|webmanifest)))(\?v=[A-Za-z0-9._\-]*)?"
)


def static_root(explicit=None):
    if explicit:
        return explicit
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def _rel_key(root, path):
    rel = os.path.relpath(path, root).replace("\\", "/")
    return rel


def _file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 64), b""):
            h.update(chunk)
    return h.hexdigest()[:HASH_LEN]


def _feed_tree(stamp, root, *, exts, extra_names=(), skip_dirs=None):
    if not root or not os.path.isdir(root):
        return
    extra = set(extra_names or ())
    skip = {".git", "node_modules", "__pycache__"}
    if skip_dirs:
        skip.update(skip_dirs)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in files:
            if not fn.endswith(exts) and fn not in extra:
                continue
            path = os.path.join(dirpath, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root).replace("\\", "/")
            stamp.update(rel.encode("utf-8"))
            stamp.update(b":")
            stamp.update(str(int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))).encode("ascii"))
            stamp.update(b":")
            stamp.update(str(st.st_size).encode("ascii"))
            stamp.update(b"\n")


def _source_fingerprint(static_dir):
    """mtime/size of static, templates, and Python. Any code change busts the digest."""
    stamp = hashlib.sha256()
    _feed_tree(stamp, static_dir, exts=_HASH_EXTS, extra_names=PRECACHE_STATIC)
    project = os.path.dirname(os.path.abspath(__file__))
    _feed_tree(stamp, os.path.join(project, "templates"), exts=(".html",))
    _feed_tree(
        stamp,
        project,
        exts=(".py",),
        skip_dirs=_SKIP_DIRS,
    )
    return stamp.hexdigest()


def _build(root, fingerprint=""):
    hashes = {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for fn in files:
            if not fn.endswith(_HASH_EXTS):
                continue
            path = os.path.join(dirpath, fn)
            try:
                hashes[_rel_key(root, path)] = _file_digest(path)
            except OSError:
                continue
    for name in PRECACHE_STATIC:
        path = os.path.join(root, name)
        key = name.replace("\\", "/")
        if key in hashes:
            continue
        if os.path.isfile(path):
            try:
                hashes[key] = _file_digest(path)
            except OSError:
                continue
    hashed_url = {}
    for name, digest in hashes.items():
        hashed_url[name] = "/static/%s?v=%s" % (name, digest)

    precache = []
    seen = set()
    for name in PRECACHE_STATIC:
        url = hashed_url.get(name)
        if not url:
            url = "/static/%s" % name
        if url not in seen:
            precache.append(url)
            seen.add(url)
        bare = "/static/%s" % name
        if name in ALIAS_PATHS and bare not in seen:
            precache.append(bare)
            seen.add(bare)

    aliases = {}
    for name in ALIAS_PATHS:
        bare = "/static/%s" % name
        urls = []
        if name in hashed_url:
            urls.append(hashed_url[name])
        urls.append(bare)
        aliases[bare] = urls

    sw_path = os.path.join(root, "sw.js")
    sw_logic = b""
    try:
        with open(sw_path, "rb") as fh:
            sw_logic = fh.read()
    except OSError:
        pass
    stamp = hashlib.sha256()
    stamp.update(sw_logic)
    stamp.update(b"fp:")
    stamp.update((fingerprint or "").encode("utf-8"))
    stamp.update(b"\n")
    for key in sorted(hashes):
        stamp.update(key.encode("utf-8"))
        stamp.update(b":")
        stamp.update(hashes[key].encode("utf-8"))
        stamp.update(b"\n")
    version = CACHE_PREFIX + stamp.hexdigest()[:12]
    return {
        "hashes": hashes,
        "hashed_url": hashed_url,
        "precache": precache,
        "aliases": aliases,
        "version": version,
        "offline_login": hashed_url.get(
            "offline_login.html", "/static/offline_login.html"
        ),
        "offline_auth": hashed_url.get("offline_auth.js", "/static/offline_auth.js"),
        "de_pwa": hashed_url.get("de_pwa.js", "/static/de_pwa.js"),
    }


def get_digest(root=None):
    global _DIGEST, _FINGERPRINT
    root = static_root(root)
    fingerprint = _source_fingerprint(root)
    with _LOCK:
        if _DIGEST is None or _FINGERPRINT != fingerprint:
            _DIGEST = _build(root, fingerprint)
            _FINGERPRINT = fingerprint
        return _DIGEST


def reset_digest():
    """Tests / debug reloader."""
    global _DIGEST, _FINGERPRINT
    with _LOCK:
        _DIGEST = None
        _FINGERPRINT = None


def cache_version(root=None):
    return get_digest(root)["version"]


def hashed_static_url(filename, root=None):
    d = get_digest(root)
    name = str(filename or "").lstrip("/")
    if name.startswith("static/"):
        name = name[7:]
    return d["hashed_url"].get(name, "/static/%s" % name)


def current_static_hash(filename, root=None):
    """Content hash for a static relative path, or None if unknown."""
    name = str(filename or "").lstrip("/")
    if name.startswith("static/"):
        name = name[7:]
    return get_digest(root)["hashes"].get(name)


def rewrite_html_static_urls(text, root=None):
    """Replace /static/file.js?v=123 (or unversioned) with the content hash."""
    if not text:
        return text, 0
    d = get_digest(root)
    hashes = d["hashes"]
    n = [0]

    def repl(match):
        name = match.group(2)
        digest = hashes.get(name)
        if not digest:
            return match.group(0)
        n[0] += 1
        return "/static/%s?v=%s" % (name, digest)

    return _STATIC_URL_RE.sub(repl, text), n[0]


def render_service_worker(root=None):
    root = static_root(root)
    d = get_digest(root)
    path = os.path.join(root, "sw.js")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    # Hash any leftover /static refs in the template first. Doing this after
    # JSON inject rewrote alias keys to ?v= hashes and dropped the bare paths,
    # so Cloudflare/SW could keep serving an unversioned stale file.
    src, _ = rewrite_html_static_urls(src, root)
    src = src.replace("__HBE_CACHE_VERSION__", d["version"])
    src = src.replace("__HBE_OFFLINE_LOGIN_URL__", d["offline_login"])
    src = src.replace("__HBE_OFFLINE_AUTH_URL__", d["offline_auth"])
    src = src.replace("__HBE_CRITICAL_ALIASES__", json.dumps(d["aliases"]))
    src = src.replace("__HBE_PRECACHE__", json.dumps(d["precache"]))
    if "__HBE_" in src:
        raise RuntimeError("service worker placeholders were not filled")
    return src


def apply_no_store_cdn(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["CDN-Cache-Control"] = "no-store"
    return response
