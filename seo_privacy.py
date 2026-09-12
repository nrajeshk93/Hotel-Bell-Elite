"""Keep the app off search engines while staff can still open the real URL."""

import os

from flask import Response

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"
NOINDEX_ROBOTS = "noindex, nofollow, noarchive, nosnippet"

SECURITY_TXT_EXPIRES = "2027-09-12T00:00:00.000Z"


def _security_txt_body() -> str:
    contact = (os.environ.get("SECURITY_CONTACT") or "").strip()
    if not contact:
        contact = "mailto:security@belleliteaccounts.com"
    elif "://" not in contact and not contact.lower().startswith("mailto:"):
        contact = f"mailto:{contact}"
    return (
        f"Contact: {contact}\n"
        "Preferred-Languages: en\n"
        "Canonical: https://www.belleliteaccounts.com/.well-known/security.txt\n"
        f"Expires: {SECURITY_TXT_EXPIRES}\n"
    )


def register_seo_privacy(app):
    @app.route("/robots.txt")
    def robots_txt():
        response = Response(ROBOTS_TXT, mimetype="text/plain; charset=utf-8")
        response.headers["Cache-Control"] = "public, max-age=3600"
        response.headers["X-Robots-Tag"] = NOINDEX_ROBOTS
        return response

    @app.route("/sitemap.xml")
    def sitemap_xml():
        response = Response(b"", status=404, mimetype="text/xml; charset=utf-8")
        response.headers["X-Robots-Tag"] = NOINDEX_ROBOTS
        return response

    @app.route("/.well-known/security.txt", endpoint="security_txt")
    @app.route("/security.txt", endpoint="security_txt_root")
    def security_txt():
        response = Response(_security_txt_body(), mimetype="text/plain; charset=utf-8")
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    @app.after_request
    def discourage_search_indexing(response):
        response.headers["X-Robots-Tag"] = NOINDEX_ROBOTS
        content_type = (response.content_type or "").lower()
        if "text/html" in content_type:
            # Authenticated HTML is per-user. Without no-store, a refresh can
            # paint a previously cached limited-user /home over Administrator.
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, private, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            vary = response.headers.get("Vary") or ""
            if "Cookie" not in vary:
                response.headers["Vary"] = (
                    (vary + ", Cookie").strip(", ").strip() if vary else "Cookie"
                )
        return response
