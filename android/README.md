# Hotel Bell Elite — Android WebView shell

Native Android wrapper that loads the existing Flask website (same layout and logic).

## Requirements

- Android Studio (Ladybug or newer recommended)
- JDK 17
- Flask server reachable from the device/emulator

## URLs

| Build   | Default URL                         |
|---------|-------------------------------------|
| Debug   | `http://10.0.2.2:8002` (emulator → host `app.py`) |
| Release | `https://YOUR_HTTPS_HOST` in `app/build.gradle.kts` |

Edit `SERVER_URL` in [`app/build.gradle.kts`](app/build.gradle.kts) before a release build.

### Physical phone (debug)

1. In `app.py`, run Flask with `host="0.0.0.0"` (not only `127.0.0.1`).
2. Set debug `SERVER_URL` to your Mac’s LAN IP, e.g. `http://192.168.1.20:8002`.

## Local HTTP + secure cookies

Your repo `.env` may set `SESSION_COOKIE_SECURE=1`. That **blocks login on HTTP**.

- Emulator/debug over HTTP: temporarily set `SESSION_COOKIE_SECURE=0` (or comment `FLASK_ENV=production`) in `.env`, restart Flask.
- Production / Play release: keep `SESSION_COOKIE_SECURE=1` and use **HTTPS** only.

## Run

1. Start Flask on the host: `.venv/bin/python app.py` (port **8002**).
2. Open the `android/` folder in Android Studio → Trust Gradle → Sync.
3. Run the **app** configuration on an emulator or device (Debug).

## What the shell handles

- Cookie sessions (login)
- File picker (Excel uploads)
- Downloads (exports / reports) via DownloadManager
- Android back → WebView history
- Offline / retry screen if the server is unreachable
