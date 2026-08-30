[app]
title = Hotel Bell Elite
package.name = hbemobile
package.domain = com.hotelbellelite
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt
source.exclude_dirs = .venv,.git,.buildozer,bin,tests,preview,__pycache__,.pytest_cache
source.exclude_patterns = assets/.gitkeep
version = 0.1.5
# Must bump together with version. Reuse the SAME keystore for every build
# or already-installed phones cannot silent-update.
android.numeric_version = 6
requirements = python3,kivy==2.3.0,kivymd==1.2.0,httpx,certifi,pillow,android,pyjnius
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/bella_light_mark.png
android.permissions = INTERNET,ACCESS_NETWORK_STATE,REQUEST_INSTALL_PACKAGES
android.api = 31
android.minapi = 24
android.archs = arm64-v8a
android.allow_backup = False
android.private_storage = True
# Production APK is HTTPS-only. Desktop python main.py still uses http://127.0.0.1:8002.
android.res_xml = android/network_security_config.xml
android.extra_manifest_application_arguments = android/extra_manifest_application_arguments.xml
# Java PackageInstaller helper (PendingIntent / BroadcastReceiver).
android.add_src = java

[buildozer]
log_level = 2
warn_on_root = 0
