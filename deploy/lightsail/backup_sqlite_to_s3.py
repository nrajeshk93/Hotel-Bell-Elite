#!/usr/bin/env python3
"""Online SQLite backup → gzip → S3 (non-disruptive; does not restart the app)."""

from __future__ import annotations

import argparse
import gzip
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required setting: {name}")
    return value


def _online_sqlite_backup(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    try:
        dst = sqlite3.connect(str(dest), timeout=60)
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup belleliteaccounts SQLite to S3")
    parser.add_argument(
        "--env-file",
        default=os.environ.get(
            "BACKUP_ENV_FILE",
            str(Path.home() / ".belleliteaccounts-backup" / "credentials.env"),
        ),
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("SQLITE_PATH", "/home/ubuntu/belleliteaccounts/bell_elite.db"),
    )
    parser.add_argument("--keep-local", type=int, default=1, help="Local gzip copies to keep")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))

    bucket = _require("BACKUP_S3_BUCKET")
    prefix = os.environ.get("BACKUP_S3_PREFIX", "belleliteaccounts").strip().strip("/")
    region = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1").strip()
    storage_class = os.environ.get("BACKUP_S3_STORAGE_CLASS", "STANDARD").strip() or "STANDARD"
    _require("AWS_ACCESS_KEY_ID")
    _require("AWS_SECRET_ACCESS_KEY")

    db_path = Path(args.db)
    if not db_path.is_file():
        raise SystemExit(f"Database not found: {db_path}")

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise SystemExit("boto3 is required. Install with: pip install boto3") from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    object_key = f"{prefix}/bell_elite_{stamp}.db.gz"
    local_dir = Path.home() / ".belleliteaccounts-backup" / "local"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_gz = local_dir / f"bell_elite_{stamp}.db.gz"

    with tempfile.TemporaryDirectory(prefix="belleliteaccounts-backup-") as tmp:
        tmp_db = Path(tmp) / "bell_elite.db"
        print(f"[{stamp}] Creating online SQLite snapshot from {db_path}")
        _online_sqlite_backup(db_path, tmp_db)
        print(f"[{stamp}] Compressing snapshot")
        with tmp_db.open("rb") as src, gzip.open(local_gz, "wb", compresslevel=9) as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    size = local_gz.stat().st_size
    print(f"[{stamp}] Uploading s3://{bucket}/{object_key} ({size} bytes, {storage_class})")
    s3 = boto3.client("s3", region_name=region)
    try:
        s3.upload_file(
            str(local_gz),
            bucket,
            object_key,
            ExtraArgs={
                "StorageClass": storage_class,
                "ServerSideEncryption": "AES256",
                "Metadata": {
                    "app": "belleliteaccounts",
                    "source": str(db_path),
                    "created_utc": stamp,
                },
            },
        )
    except (BotoCoreError, ClientError) as exc:
        raise SystemExit(f"S3 upload failed: {exc}") from exc

    # Rotate local copies (remote retention is handled by S3 lifecycle).
    keep = max(0, int(args.keep_local))
    locals_sorted = sorted(local_dir.glob("bell_elite_*.db.gz"))
    for old in locals_sorted[:-keep] if keep else locals_sorted:
        try:
            old.unlink()
        except OSError as exc:
            print(f"Warning: could not remove {old}: {exc}", file=sys.stderr)

    print(f"[{stamp}] OK uploaded s3://{bucket}/{object_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
