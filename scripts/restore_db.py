"""
scripts/restore_db.py
---------------------
PostgreSQL Database Restore Script:
- Verifies SHA-256 integrity checksum before restoration
- Safety barrier: strictly blocks restoring to production unless explicit override flag is passed
- Executes psql restore cleanly
Usage:
    python scripts/restore_db.py <backup_file.sql> [--database-url <url>] [--confirm-production]
"""
import sys
import os
import subprocess
import hashlib
import argparse
from urllib.parse import urlparse

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.backup_db import find_pg_binary, compute_sha256


def verify_checksum(sql_file: str) -> bool:
    sha_file = sql_file + ".sha256"
    if not os.path.exists(sha_file):
        print("[WARN] No .sha256 checksum file found. Skipping checksum verification.")
        return True

    with open(sha_file, "r", encoding="utf-8") as f:
        line = f.readline().strip()
        expected = line.split()[0]

    actual = compute_sha256(sql_file)
    if expected.lower() == actual.lower():
        print(f"[CHECK] SHA-256 checksum matched: {actual}")
        return True
    else:
        print(f"[ERROR] Checksum MISMATCH! Expected: {expected}, Computed: {actual}")
        return False


def restore_backup(backup_file: str, db_url: str, confirm_production: bool = False):
    if not os.path.exists(backup_file):
        print(f"[FATAL] Backup file not found: {backup_file}")
        sys.exit(1)

    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or ""

    # Production safety check
    is_prod = (db_name == "exam_proctor" or "production" in db_name)
    if is_prod and not confirm_production:
        print("[CRITICAL SAFETY ERROR] Target database is PRODUCTION ('exam_proctor')!")
        print("Restoring over production destroys existing active data.")
        print("To proceed, you must pass --confirm-production explicitly.")
        sys.exit(1)

    # Integrity verification
    if not verify_checksum(backup_file):
        print("[FATAL] Aborting restore due to checksum verification failure.")
        sys.exit(1)

    psql_bin = find_pg_binary("psql")
    print(f"[RESTORE] Restoring {backup_file} into {db_name} on {host}:{port}...")

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        psql_bin,
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", db_name,
        "-f", backup_file
    ]

    try:
        res = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        print(f"[SUCCESS] Database '{db_name}' restored successfully from {backup_file}.")
    except subprocess.CalledProcessError as e:
        print(f"[FATAL] psql restore failed: {e.stderr}")
        raise


def main():
    parser = argparse.ArgumentParser(description="ExamProctor PostgreSQL Restore")
    parser.add_argument("backup_file", help="Path to the .sql backup file to restore")
    parser.add_argument("--database-url", required=True, help="Target PostgreSQL connection URL")
    parser.add_argument("--confirm-production", action="store_true", help="Explicit confirmation if restoring to production")
    args = parser.parse_args()

    restore_backup(args.backup_file, args.database_url, confirm_production=args.confirm_production)


if __name__ == "__main__":
    main()
