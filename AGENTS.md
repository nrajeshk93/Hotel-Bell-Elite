# Working on Hotel Bell Elite

Read this before changing anything. Several different AI agents and people work
on this repository, so the conventions below are enforced by tests and a
pre-commit hook rather than by memory.

## Setup

- Python env: `.venv` in the repo root. Run tests as
  `PYTHONPATH=. .venv/bin/pytest tests -q` (both parts are required, or `db`
  will not import).
- Local dev server on port 8002, started from the repo root with
  `nohup .venv/bin/python app.py < /dev/null > /tmp/hbe_8002.log 2>&1 &!`
  (zsh; macOS has no `setsid`).
- `mobile_kivy/tests` is a separate app tree and fails to collect from the repo
  root. Run `pytest tests` and not bare `pytest`.


## Local `python app.py` (port 8002)

- Keep `FLASK_DEBUG=0` in `.env` unless you explicitly want Flask’s auto-reloader.
- `FLASK_DEBUG=1` spawns **two** processes and constantly watches the project tree — that shows up in the terminal as repeated scanning.
- Prefer `.venv/bin/python app.py` so `python-dotenv` loads `.env`.

## Static assets: never hand-write a version

Production serves `/static/` from nginx (currently `no-store` / CDN bypass) with
Cloudflare in front. A static file is still protected from staleness by the
**content hash in its URL** — that is the permanent correctness guarantee if
nginx caching is ever re-enabled.

- Use `{{ asset('file.css') }}` in templates.
- `{{ url_for('static', filename='file.css') }}` is safe too — `app.py` stamps
  the hash through an `@app.url_defaults` hook.
- Never write `?v=<number>` yourself. This is the single most repeated
  production bug in this codebase; a hand-maintained version is stale the
  instant the file changes.
- In JS source, never hardcode `?v=<number>` either — use a bare `/static/file.js` path (the HTML/JS rewrite stamps the live hash). `tests/test_asset_cache_bust.py` also guards this.
- `tests/test_asset_cache_bust.py` enforces this. If it fails, fix the template,
  never the test.

## Never load app JS/CSS from a public CDN

Employee Payroll hung for minutes because `employees.html` loaded Lucide from
`https://unpkg.com/lucide@latest/...`. Access Management had the same trap.
When unpkg / the network stalls, the page never finishes.

- Vendor any UI library under `static/` (e.g. `static/lucide.min.js`) and load
  it with `{{ asset('lucide.min.js') }}`.
- Forbidden in templates and app JS: `unpkg.com`, `cdn.jsdelivr.net`,
  `cdnjs.cloudflare.com`, `ajax.googleapis.com` **script/link tags for app
  behaviour**, and any `@latest` CDN URL.
- Google Fonts CSS with `display=swap` is allowed (fonts only). Do not use a
  font CDN as a place to pull JavaScript.
- `tests/test_asset_cache_bust.py` fails if a template reintroduces a CDN script.

## Soft-nav: instant shells, live lists, build-bound cache

`static/de_workspace_transitions.js` soft-navigates the shell. Wrong policy
here either (a) paints pre-deploy HTML or (b) makes Restaurant wait on a
loading bar every open.

- `IDLE_PREFETCH_PATHS` may only list light hubs: `/home`, `/main-dashboard`,
  `/master`, `/settings`, `/license`.
- **Prefetch** Restaurant/Bar shells (`/point-of-sale`, `/point-of-sale/invoice`,
  `/point-of-sale/menu`, and the bar equivalents) and Hotel Rooms/Reservations.
  Floor/occupancy still refreshes from API after paint. Hovering the Restaurant
  nav group must keep calling `prefetchRestaurantGroup()` (HTML + floor JSON +
  hashed script preload via `warmAssetsFromHtml`).
- **Live-only** (`mustFetchLiveSoftNavPath`): payroll, `/access-management`,
  POS invoice-ledger / sales-update / settings, hotel invoice/credit/settings,
  `/accounts`, `/stores`, `/communication-hub`, `/reports/sales/…`. Do **not**
  put `/point-of-sale` or `/bar-point-of-sale` as a blanket live-only prefix —
  that reintroduces the Restaurant lag.
- Soft-nav HTML cache is bound to `/hbe-build.json` (`syncSoftNavBuildId`). A
  new deploy clears the cache so hashed script URLs cannot go stale. Keep
  `clearSoftNavPrefetch()` on SW/build reload in `de_pwa.js`.
- After Home/Dashboard, `scheduleCriticalModuleWarm()` must idle-warm
  Restaurant, Bar, and Hotel Rooms/Reservations (HTML + hashed JS via
  `warmAssetsFromHtml`). Instant shells hide the soft-nav progress bar as soon
  as the DOM paints; POS still paints floor from snapshot then hits the API.
- App UI fonts are self-hosted (`hbe_fonts.css` / `hbe_login_fonts.css`). Do not
  reintroduce `fonts.googleapis.com` in templates.

## Deploying

- The app runs under gunicorn (`belleliteaccounts.service`), which has no
  reloader, so **Python changes require a service restart**. Templates are safe
  without one because `TEMPLATES_AUTO_RELOAD` is forced on in `app.py`.
- After any deploy, restart the service and confirm the new build id:
  `curl -s https://belleliteaccounts.com/hbe-build.json`.
- Static / template / soft-nav JS changes still need the updated files on the
  server; hashed URLs only help once the new bytes are there.

## Git

- The repository owner makes the commits. Do not commit, amend, or push unless
  explicitly asked.
- Enable the shared hooks once per clone: `git config core.hooksPath .githooks`.

## PWA offline / online
- Service Worker Cache Storage: **static + offline shells only**. Never cache business/API JSON.
- Floor + menu APIs are **NetworkOnly**; offline POS uses IndexedDB (`pos_offline.js`) + floor snapshots.
- On `online`, `HbeOfflineSync.runReconnect` is the single path: `PURGE_DATA_CACHES` → flush outbox → refresh menu catalog → refetch floor → `hbe:online-sync`.
- Keep floor snapshots if sync/floor fetch fails (never blank Tables).
- Settle Bill stays online-only; offline banner must say so.

