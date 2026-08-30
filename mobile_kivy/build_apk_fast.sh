#!/usr/bin/env bash
# Fast native APK (~2 min) — loads the mobile UI at /mobile-app/ on production.
# No Docker. Requires JDK 17 + Android SDK (brew install openjdk@17 android-commandlinetools).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID="$ROOT/android"
OUT="$ROOT/mobile_kivy/bin"
APK_NAME="Hotel-Bell-Elite.apk"

export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:/opt/homebrew/bin:$PATH"

mkdir -p "$OUT"
echo "==> Syncing designed mobile UI into APK assets…"
"$ROOT/.venv/bin/python" "$ROOT/scripts/sync_mobile_assets.py"
# Fail the build if assets drifted from the preview source.
PREVIEW_LINES="$(wc -l < "$ROOT/mobile_kivy/preview/mobile_ui_preview.html" | tr -d ' ')"
ASSET_LINES="$(wc -l < "$ANDROID/app/src/main/assets/mobile/mobile_ui_preview.html" | tr -d ' ')"
if [[ "$PREVIEW_LINES" != "$ASSET_LINES" ]]; then
  echo "ERROR: asset HTML line count ($ASSET_LINES) != preview ($PREVIEW_LINES)" >&2
  exit 1
fi
printf 'sdk.dir=%s\n' "$ANDROID_HOME" > "$ANDROID/local.properties"

if [[ ! -x "$ANDROID/gradlew" ]]; then
  echo "==> Generating Gradle wrapper…"
  gradle -p "$ANDROID" wrapper --gradle-version 8.9 --distribution-type bin
fi

echo "==> Building $APK_NAME"
echo "==> Mobile UI: bundled in APK + production cookie auth (/api/mobile/login)"
cd "$ANDROID"
chmod +x gradlew
./gradlew --no-daemon assembleDebug

cp "$ANDROID/app/build/outputs/apk/debug/app-debug.apk" "$OUT/$APK_NAME"
ls -lh "$OUT/$APK_NAME"
echo "==> Done — install $OUT/$APK_NAME"
echo "==> For auto-update on phones already running 1.0.2+:"
echo "    .venv/bin/python scripts/publish_android_shell_apk.py"
echo "    git add static/mobile/hbe.apk static/mobile/hbe_shell_version.json && git push && AWS sync"
echo "==> UI HTML also updates live from https://belleliteaccounts.com/mobile-app/ after AWS sync"
echo "    (no APK needed for HTML/CSS/JS). Deploy app.py + mobile_kivy/preview/ + mobile_preview_flask.py."
echo "==> Deploy app.py + mobile_preview_flask.py to AWS so /mobile-app/ and /preview-api/ work on production."
