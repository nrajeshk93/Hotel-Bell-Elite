"""App version reported by the client.

Keep in sync with mobile_kivy/buildozer.spec (`version` and
`android.numeric_version`). On Android the updater prefers PackageManager
values from the installed APK, which are written from that spec at build time.
"""

from __future__ import annotations

APP_VERSION = "0.1.2"
APP_VERSION_CODE = 3
ANDROID_PACKAGE = "com.hotelbellelite.hbemobile"
