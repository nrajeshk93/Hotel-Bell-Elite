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



## Restaurant / Bar Tables: occupancy must not look like “cache”

What staff call a “cache issue” on Tables is usually **stuck open bills** or a
**client floor snapshot**, not Cloudflare.

- At most **one** pre-invoice open dine-in bill per table (`customer_bill_sent=0`).
  Enforced in `save_pos_invoice` and by unique index
  `idx_pos_one_active_preinvoice_per_table`.
- After **Generate Invoice**, the tile frees for the next party; that bill may
  stay `status=open` until Settle — that is intentional. Do not create a second
  pre-invoice open on the same table.
- Available table click must not resume IndexedDB drafts with a server
  `invoiceId` / after an online by-table miss — purge those leftovers; only
  offline-unsynced drafts (no `invoiceId`) may hydrate locally.
- **POS invoice WhatsApp:** toolbar control next to PDF sends the generated bill via Meta template `hotel_bell_elite_invoice` (DOCUMENT header PDF + 4 body vars: guest first name, brand title case, invoice no, amount without ₹). Exact Meta body (blank lines + `*{{n}}*` bold + `₹` before `{{4}}`) is documented in `docs/whatsapp_pos_invoice_template.md` — Meta Business Manager must match; code cannot sync template text. The PDF must match the printed Spice thermal customer bill (`static/pos_customer_bill.js` / POS Print), not a separate A4 layout — see `pos_invoice_pdf.py`. Requires customer mobile; env `WHATSAPP_POS_INVOICE_TEMPLATE` / `_LANGUAGE` (defaults match Meta). Uses existing `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` (must be Meta id `1241737459022736` for sender **+91 96112 32344** / `+919611232344`; optional `WHATSAPP_SENDER_E164` mismatch check). Outbound Cloud API "from" is that phone_number_id, not body digits. Dry-run under `WHATSAPP_DRY_RUN` / tests.
- After **Generate Invoice** (`customer_bill_sent` or `customer_bill_at`), the
  bill drops out of Pending Kitchen even if `sent_qty` was never marked. Floor
  occupancy / `kot_sent` still do not filter that list; Settle can continue.
- Customer / cash bill **print** (Tables → Today’s Invoices Print, etc.) must
  run the same Generate Invoice path: set `customer_bill_sent`, remint provisional
  hex order numbers, free the floor tile, drop Pending Kitchen. Settle later is OK.
- Online Tables first paint **must not** show Occupied from session/local
  snapshot (`floorSnapshotForFirstPaint`); live `/api/floor` (`cache: no-store`)
  is the source of truth. Offline may use the snapshot.
- Never “fix” occupancy by only hard-refreshing — repair open invoices /
  settle zombies, then refresh.

### Permanent Available-click / ghost-cart contract

- **Available click:** `GET …/api/invoices/by-table` with no open pre-invoice
  returns `invoice: null` + `localShouldDrop: true`; client must purge
  server-linked IndexedDB drafts and start blank (never hydrate ghosts).
- **Settle sets inactive:** successful settle/close sets `is_active=0` so
  settled rows never look active to floor/open queries; ledger still sees
  them via `_pos_invoice_row_visible_sql`.
- **Always bump build with POS static:** changing `pos_invoice.js` /
  `pos_offline.js` / `pos_tables.js` (or related) must ship so
  `/hbe-build.json` `cacheVersion` (content digest) flips — otherwise
  PWA/soft-nav can stick old JS.
- **Never treat staff “cache” as CDN** until `by-table` + IndexedDB drafts
  are checked (ghost cart is usually local leftovers, not Cloudflare).

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

- **Modal backdrop dismiss:** overlay/backdrop click closes the same as Cancel (content clicks must not); keep this on masters modals, confirm dialogs, ep-/st-modals, and settle dialogs.

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

- **Stock transfer** creates a pending `TRF-…` document only (no qty change at create). Print/PDF slip opens for handover; receive under **Stock Inward → Transfers** (lists by **receiving** `to_outlet` — warehouse→Bar shows under Bar) → Verify & Receive to move stock. Soft-refresh Stock/Inward/Transfer Ledger (`deSoftRefresh` + invalidate `/stores/stock`, inward, `/stores/stock/transfers`). PDF: `GET /stores/stock/transfers/<id>/pdf`. **Transfer Ledger** (`/stores/stock/transfers`, header button on Store before Export) lists pending/received/cancelled with View/Download/Print/Cancel (cancel pending only).

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



## Restaurant / Bar Tables: occupancy must not look like “cache”

What staff call a “cache issue” on Tables is usually **stuck open bills** or a
**client floor snapshot**, not Cloudflare.

- At most **one** pre-invoice open dine-in bill per table (`customer_bill_sent=0`).
  Enforced in `save_pos_invoice` and by unique index
  `idx_pos_one_active_preinvoice_per_table`.
- After **Generate Invoice**, the tile frees for the next party; that bill may
  stay `status=open` until Settle — that is intentional. Do not create a second
  pre-invoice open on the same table.
- Available table click must not resume IndexedDB drafts with a server
  `invoiceId` / after an online by-table miss — purge those leftovers; only
  offline-unsynced drafts (no `invoiceId`) may hydrate locally.
- **POS invoice WhatsApp:** toolbar control next to PDF sends the generated bill via Meta template `hotel_bell_elite_invoice` (DOCUMENT header PDF + 4 body vars: guest first name, brand title case, invoice no, amount without ₹). Exact Meta body (blank lines + `*{{n}}*` bold + `₹` before `{{4}}`) is documented in `docs/whatsapp_pos_invoice_template.md` — Meta Business Manager must match; code cannot sync template text. The PDF must match the printed Spice thermal customer bill (`static/pos_customer_bill.js` / POS Print), not a separate A4 layout — see `pos_invoice_pdf.py`. Requires customer mobile; env `WHATSAPP_POS_INVOICE_TEMPLATE` / `_LANGUAGE` (defaults match Meta). Uses existing `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` (must be Meta id `1241737459022736` for sender **+91 96112 32344** / `+919611232344`; optional `WHATSAPP_SENDER_E164` mismatch check). Outbound Cloud API "from" is that phone_number_id, not body digits. Dry-run under `WHATSAPP_DRY_RUN` / tests.
- After **Generate Invoice** (`customer_bill_sent` or `customer_bill_at`), the
  bill drops out of Pending Kitchen even if `sent_qty` was never marked. Floor
  occupancy / `kot_sent` still do not filter that list; Settle can continue.
- Customer / cash bill **print** (Tables → Today’s Invoices Print, etc.) must
  run the same Generate Invoice path: set `customer_bill_sent`, remint provisional
  hex order numbers, free the floor tile, drop Pending Kitchen. Settle later is OK.
- Online Tables first paint **must not** show Occupied from session/local
  snapshot (`floorSnapshotForFirstPaint`); live `/api/floor` (`cache: no-store`)
  is the source of truth. Offline may use the snapshot.
- Never “fix” occupancy by only hard-refreshing — repair open invoices /
  settle zombies, then refresh.

### Permanent Available-click / ghost-cart contract

- **Available click:** `GET …/api/invoices/by-table` with no open pre-invoice
  returns `invoice: null` + `localShouldDrop: true`; client must purge
  server-linked IndexedDB drafts and start blank (never hydrate ghosts).
- **Settle sets inactive:** successful settle/close sets `is_active=0` so
  settled rows never look active to floor/open queries; ledger still sees
  them via `_pos_invoice_row_visible_sql`.
- **Always bump build with POS static:** changing `pos_invoice.js` /
  `pos_offline.js` / `pos_tables.js` (or related) must ship so
  `/hbe-build.json` `cacheVersion` (content digest) flips — otherwise
  PWA/soft-nav can stick old JS.
- **Never treat staff “cache” as CDN** until `by-table` + IndexedDB drafts
  are checked (ghost cart is usually local leftovers, not Cloudflare).

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

- **Modal backdrop dismiss:** overlay/backdrop click closes the same as Cancel (content clicks must not); keep this on masters modals, confirm dialogs, ep-/st-modals, and settle dialogs.

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

- **Stock transfer** creates a pending `TRF-…` document only (no qty change at create). Print/PDF slip opens for handover; receive under **Stock Inward → Transfers** (lists by **receiving** `to_outlet` — warehouse→Bar shows under Bar) → Verify & Receive to move stock. Soft-refresh Stock/Inward/Transfer Ledger (`deSoftRefresh` + invalidate `/stores/stock`, inward, `/stores/stock/transfers`). PDF: `GET /stores/stock/transfers/<id>/pdf`. **Transfer Ledger** (`/stores/stock/transfers`, header button on Store before Export) lists pending/received/cancelled with View/Download/Print/Cancel (cancel pending only).

## Deploying

- Nightly WhatsApp sales (`hotel_sales_update`) runs from **ubuntu crontab** via `deploy/lightsail/install_whatsapp_sales_cron.sh`, not gunicorn. Crontab survives `git pull`; re-run the installer only if app/venv path changes. Keep localhost `WHATSAPP_SALES_REPORT_SCHEDULE=0` so Mac never double-sends.


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

