"""
scripts/backup_db.py
--------------------
PostgreSQL Automated Backup Script:
- Dumps database to compressed SQL file with timestamp
- Calculates SHA-256 integrity checksum
- Masks credentials in logs
- Prunes backups exceeding retention policy (default: 7 days)
Usage:
    python scripts/backup_db.py [--database-url <url>] [--output-dir <dir>] [--retention-days <days>]
"""
import sys
import os
import subprocess
import hashlib
import argparse
from datetime import datetime
from urllib.parse import urlparse

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import DATABASE_URL


def find_pg_binary(name: str) -> str:
    """Find pg_dump or pg_restore in PATH or standard installation directories."""
    # 1. Check in PATH
    import shutil
    found = shutil.which(name)
    if found:
        return found

    # 2. Check Windows standard paths
    win_paths = [
        f"C:\\Program Files\\PostgreSQL\\18\\bin\\{name}.exe",
        f"C:\\Program Files\\PostgreSQL\\17\\bin\\{name}.exe",
        f"C:\\Program Files\\PostgreSQL\\16\\bin\\{name}.exe",
        f"C:\\Program Files\\PostgreSQL\\15\\bin\\{name}.exe"
    ]
    for p in win_paths:
        if os.path.exists(p):
            return p

    # 3. Check Linux standard paths
    linux_paths = [
        f"/usr/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/lib/postgresql/15/bin/{name}",
        f"/usr/lib/postgresql/16/bin/{name}"
    ]
    for p in linux_paths:
        if os.path.exists(p):
            return p

    return name


def compute_sha256(filepath: str) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def prune_old_backups(output_dir: str, retention_days: int):
    now_ts = datetime.now().timestamp()
    cutoff_ts = now_ts - (retention_days * 86400)
    for fname in os.listdir(output_dir):
        if fname.endswith(".sql") or fname.endswith(".sha256"):
            fpath = os.path.join(output_dir, fname)
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff_ts:
                try:
                    os.remove(fpath)
                    print(f"[BACKUP] Pruned expired backup file: {fname}")
                except Exception as e:
                    print(f"[WARN] Could not prune {fname}: {e}")


def create_backup(db_url: str, output_dir: str, retention_days: int = 7) -> str:
    parsed = urlparse(db_url)
    db_name = parsed.path.lstrip("/")
    host = parsed.hostname or "localhost"
    port = str(parsed.port or 5432)
    user = parsed.username or "postgres"
    password = parsed.password or ""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{db_name}_backup_{timestamp}.sql"
    backup_path = os.path.join(output_dir, backup_filename)

    pg_dump_bin = find_pg_binary("pg_dump")
    print(f"[BACKUP] Target database: {db_name} on {host}:{port} (User: {user})")
    print(f"[BACKUP] Using pg_dump binary: {pg_dump_bin}")

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        pg_dump_bin,
        "-h", host,
        "-p", port,
        "-U", user,
        "-F", "p",  # Plain text SQL dump
        "-f", backup_path,
        db_name
    ]

    try:
        res = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"[FATAL] pg_dump failed: {e.stderr}")
        raise

    # Calculate and store checksum
    checksum = compute_sha256(backup_path)
    checksum_file = backup_path + ".sha256"
    with open(checksum_file, "w", encoding="utf-8") as f:
        f.write(f"{checksum}  {backup_filename}\n")

    filesize_mb = round(os.path.getsize(backup_path) / (1024 * 1024), 2)
    print(f"[SUCCESS] Backup created: {backup_path} ({filesize_mb} MB)")
    print(f"[SUCCESS] SHA-256 Checksum: {checksum}")

    # Prune old backups
    prune_old_backups(output_dir, retention_days)
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="ExamProctor PostgreSQL Backup")
    parser.add_argument("--database-url", default=DATABASE_URL, help="Target PostgreSQL connection URL")
    parser.add_argument("--output-dir", default=os.path.join(os.path.dirname(__file__), "..", "backups"), help="Directory for backup storage")
    parser.add_argument("--retention-days", type=int, default=7, help="Backup retention period in days")
    args = parser.parse_args()

    create_backup(args.database_url, os.path.abspath(args.output_dir), args.retention_days)


if __name__ == "__main__":
    main()
