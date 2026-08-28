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
echo "==> Deploy app.py + mobile_preview_flask.py to AWS so /mobile-app/ and /preview-api/ work on production."
