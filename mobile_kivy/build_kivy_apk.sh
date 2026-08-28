#!/usr/bin/env bash
# Build native Kivy APK entirely inside Linux Docker volumes (avoids macOS bind-mount tar bugs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/bin"
APK_NAME="Hotel-Bell-Elite.apk"
IMAGE="${HBE_BUILDOZER_IMAGE:-kivy/buildozer:latest}"
SDK_VOLUME="${HBE_BUILDOZER_VOLUME:-hbe_buildozer_cache}"
WORK_VOLUME="${HBE_KIVY_WORK_VOLUME:-hbe_kivy_work}"

mkdir -p "$OUT"
echo "==> Native Kivy APK → $OUT/$APK_NAME"
echo "==> Production: https://belleliteaccounts.com"

docker volume create "$SDK_VOLUME" >/dev/null 2>&1 || true
docker volume create "$WORK_VOLUME" >/dev/null 2>&1 || true

echo "==> Syncing source into Linux volume (one-time per volume refresh)…"
docker run --rm \
  -v "$ROOT:/src:ro" \
  -v "$WORK_VOLUME:/work" \
  alpine sh -c '
    apk add --no-cache rsync >/dev/null
    mkdir -p /work/app
    rsync -a --delete \
      --exclude .buildozer \
      --exclude bin \
      --exclude .venv \
      --exclude preview \
      --exclude tests \
      --exclude __pycache__ \
      --exclude .pytest_cache \
      /src/ /work/app/
  '

echo "==> Compiling inside Docker (first run ~20–40 min)…"
docker run --rm \
  --platform linux/amd64 \
  --entrypoint /bin/bash \
  --volume "$SDK_VOLUME:/home/user/.buildozer" \
  --volume "$WORK_VOLUME:/work" \
  --volume "$OUT:/out" \
  -e HOME=/home/user \
  -e PATH=/home/user/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  "$IMAGE" \
  -lc '
set -euo pipefail
cd /work/app
SDK=/home/user/.buildozer/android/platform/android-sdk
if [[ -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  SM="$SDK/cmdline-tools/latest/bin/sdkmanager"
elif [[ -x "$SDK/tools/bin/sdkmanager" ]]; then
  SM="$SDK/tools/bin/sdkmanager"
else
  SM="$(command -v sdkmanager)"
fi
yes | "$SM" --sdk_root="$SDK" --licenses >/dev/null || true
"$SM" --sdk_root="$SDK" "platform-tools" "platforms;android-31" "build-tools;31.0.0" "build-tools;35.0.0" >/dev/null || true
buildozer android debug
APK="$(ls -t bin/*-debug.apk | head -1)"
cp "$APK" "/out/Hotel-Bell-Elite.apk"
echo "Built $(basename "$APK")"
'

ls -lh "$OUT/$APK_NAME"
echo "==> Done"
