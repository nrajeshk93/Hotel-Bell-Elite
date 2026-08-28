#!/usr/bin/env python3
"""Run the Hotel Bell Elite Kivy/KivyMD mobile client.

  cd mobile_kivy
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  export HBE_API_BASE_URL=http://127.0.0.1:8002
  python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hbe_mobile.app import HbeMobileApp


if __name__ == "__main__":
    HbeMobileApp().run()
