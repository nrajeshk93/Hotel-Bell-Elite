# Hotel Bell Elite — Kivy / KivyMD mobile client

Native Python mobile frontend that talks to the **existing Flask server** over HTTP.
It does **not** import Flask, `db.py`, or change the web app.

## Requirements

- Python 3.10+ (3.11 recommended)
- Running Hotel Bell Elite Flask app (default `http://127.0.0.1:8002`)
- For device/emulator: Flask must listen on `0.0.0.0` and `SESSION_COOKIE_SECURE=0` for HTTP (same notes as [`../android/README.md`](../android/README.md))

## Setup

```bash
cd mobile_kivy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export HBE_API_BASE_URL=http://127.0.0.1:8002
python main.py
```

Server URL is configured via `HBE_API_BASE_URL` or `~/.hbe_mobile/settings.json` — it is not shown on the login screen.

### Production vs local

Mobile POS (including **Send KOT**) talks to the **same Flask app** the restaurant PC uses. Kitchen line state (`sent_qty` / KOT) lives in that shared database.

| Environment | Set `HBE_API_BASE_URL` to |
|---|---|
| Desktop `python main.py` | `http://127.0.0.1:8002` (default) |
| Android **debug** APK | `http://10.0.2.2:8002` (emulator → host Flask) |
| Android **release** APK | `https://belleliteaccounts.com` |
| Any build | `~/.hbe_mobile/settings.json` `api_base_url` always wins; else `HBE_API_BASE_URL` |

Example production setting:

```bash
export HBE_API_BASE_URL=https://your-hotel-bell-elite.example
# or write ~/.hbe_mobile/settings.json → {"api_base_url":"https://…"}
```

Preview `serve.py` uses the same variable (`FLASK_BASE`) when proxying `/preview-api/pos/*`. Point it at production only when intentionally testing against live data.

**Note:** Paper KOT printing still runs on the PC via Hotel Print Agent when someone uses web POS print. Mobile Send KOT updates the shared server so the logged-in PC sees the order as sent on refresh; auto-printing from the phone alone needs a future print-job queue.

## Architecture

| Package | Role |
|---------|------|
| `hbe_mobile/api/` | Cookie session + CSRF HTTP client; domain helpers |
| `hbe_mobile/models/` | Plain dataclasses (no ORM) |
| `hbe_mobile/screens/` | KivyMD UI |
| `hbe_mobile/widgets/` | Shared chrome (active nav, KPI cards) |

Auth: `POST /login` (form) → Flask session cookie → `X-CSRFToken` on mutating calls.

## Phase 1 screens

1. Login  
2. Home (+ `/home/api/notifications`)  
3. Dashboard (KPI parse from `#md-dashboard-data` + Android WebView hook / browser open)  
4. Products (`/stores/api/products-lite` + product-master form save)  
5. POS Invoice (`/point-of-sale/api/*`)  
6. Approvals (`/accounts/purchase-verification` embeds + JSON create/delete)

## Android (Buildozer)

```bash
# Install buildozer separately; then:
buildozer android debug
# release (same keystore every time — required for silent updates):
buildozer android release
```

See `buildozer.spec`. Package is `com.hotelbellelite.hbemobile`. iOS via kivy-ios after Android is stable.

Bump **both** `version` and `android.numeric_version` in `buildozer.spec` and the matching constants in `hbe_mobile/version.py` before a publish. `android.numeric_version` is the Android `versionCode` phones compare.

### Silent self-update (sideloaded APK)

AWS **cannot push** into phones. Your habit stays the same as server code:

**local change → git push → AWS Server sync → restart.**

For mobile UI/binary changes you also publish an APK into `static/mobile/` before that push. Installed phones **pull** `/api/mobile/version` + the APK from `https://belleliteaccounts.com` and install themselves (no in-app “Update now?”).

**First APK that contains the updater must be installed by hand once** on each hotel phone. Grant “Allow from this source” once. Later publishes auto-update. **Reuse the same keystore forever.** Debug and release signing keys cannot update each other.

OS limits that remain (not an in-app prompt):

- **One-time** “allow from this source” / `REQUEST_INSTALL_PACKAGES` grant. The app opens the system settings page if `canRequestPackageInstalls()` is false; after that, updates proceed without a staff tap on our UI.
- **Android 14+** may still show a **system** confirmation sheet (`STATUS_PENDING_USER_ACTION`). The app starts that intent; there is no custom dialog. Not 100% silent on every OS version (MDM/device-owner would be required for that).

Checks run: shortly after UI start, on **login**, on **app resume**, and about every **45 minutes**. Failures are logged and retried; POS / login are not blocked. Desktop `python main.py` does not install APKs.

### Future updates (your recurring workflow)

1. Change code locally (Flask and/or `mobile_kivy/`).
2. If the **phone APK** needs a new build:
   - Double-click **`Publish Mobile APK.command`** (in `Scripts/Hotel Bell Elite/`), **or**:
     ```bash
     .venv/bin/python scripts/bump_mobile_version.py --patch
     cd mobile_kivy && buildozer android release
     cd .. && .venv/bin/python scripts/publish_mobile_apk.py
     ```
3. `git add` (include `static/mobile/hbemobile.apk` + `version.json` when publishing) → your Mac→GitHub push.
4. Run **AWS Server sync.command** (pull + restart) as usual.
5. Phones already on an updater build self-download / install / relaunch.

After AWS sync, optionally verify:

```bash
.venv/bin/python scripts/verify_mobile_ota.py --base https://belleliteaccounts.com
```

Expect JSON from `/api/mobile/version` (login-free) with `versionCode` + non-empty `sha256` once an APK is published.

### Publish a new APK to AWS (phones pull it)

1. Bump versions together (preferred):
   ```bash
   .venv/bin/python scripts/bump_mobile_version.py --patch
   ```
   Or edit `version` + `android.numeric_version` in `buildozer.spec` and matching constants in `hbe_mobile/version.py`.
2. Build with the **same** release keystore: `cd mobile_kivy && buildozer android release`
3. From the repo root:
   ```bash
   .venv/bin/python scripts/publish_mobile_apk.py
   # or: .venv/bin/python scripts/publish_mobile_apk.py --apk mobile_kivy/bin/<your>.apk
   ```
   This copies the APK to `static/mobile/hbemobile.apk` and writes `static/mobile/version.json` (version, versionCode, sha256, apk_url).
4. `git add static/mobile/hbemobile.apk static/mobile/version.json` plus your source, then **you** `git push`. AWS syncs as usual.
5. Phones already on an updater build download, sha256-check, PackageInstaller-session install, and relaunch.

Existing `0.1.0` / versionCode `1` installs will not try to update until you publish a newer `versionCode`.

## Desktop notes

- Install `pygame` (listed in `requirements.txt`) so Kivy has a window provider.
- The workspace shell uses a custom side nav (not `MDNavigationDrawer` / `MDTopAppBar`) so the app runs on Kivy pygame builds that lack SDL2 `WindowController` (common on newer Python wheels). Android Buildozer builds can still host a WebView for Dashboard.

## Cursor browser preview

```bash
cd mobile_kivy/preview
# Repo .venv (Flask) — required for live Approve/Revert against localhost
../../.venv/bin/python serve.py
# open http://127.0.0.1:8765/
# Optional: HBE_API_BASE_URL=http://127.0.0.1:8002
```

`serve.py` serves the HTML look-alike, reads live Pending/Approved rows from `bell_elite.db`, and proxies **Approve / Revert / POS (menu, invoices, Send KOT, settle)** to Flask (`HBE_API_BASE_URL`, default `http://127.0.0.1:8002`). Use the **repo** `.venv` (Flask installed), not only `mobile_kivy/.venv`. The filter icon opens the web Approvals page. Approvals auto-refreshes quietly every few seconds while that screen is open.

## Tests (no UI)

```bash
cd mobile_kivy
python -m pytest tests/ -q
```

These tests do not start Kivy windows; they cover HTML JSON extraction and client helpers.
