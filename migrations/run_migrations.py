"""
migrations/run_migrations.py
----------------------------
Centralized, ordered database migration runner for ExamProctor:
- Tracks executed migrations in schema_migrations table
- Applies migrations in strict sequential dependency order
- Provides status inspection, upgrade, and downgrade operations
- Safety gate: prevents accidental execution against production without explicit --confirm
"""
import sys
import os
import argparse
from datetime import datetime
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import DATABASE_URL, IS_PRODUCTION
from time_utils import utc_now

# Migration modules in exact sequential execution order
MIGRATION_STEPS = [
    ("phase_1_foundation", "migrations.migrate_phase1_foundation", "Phase 1: Foundation, Organizations, Multi-purpose Assessments"),
    ("group_members_student_id", "migrations.migrate_group_members", "Group Members: relational student_id column and backfill"),
    ("phase_2_assignments", "migrations.migrate_phase2_assignments", "Phase 2: Candidate and Group Assignments & Scheduling"),
    ("phase_3_question_bank", "migrations.migrate_phase3_question_bank", "Phase 3: Centralized Question Bank & Six Question Types"),
    ("phase_4_candidate_engine", "migrations.migrate_phase4_candidate_engine", "Phase 4: Candidate Examination Flow, Multi-attempt Sessions"),
    ("phase_5_proctoring", "migrations.migrate_phase5_proctoring", "Phase 5: Proctoring Policies, Cheat Flags & Integrity Scoring"),
    ("phase_6_evaluation", "migrations.migrate_phase6_evaluation", "Phase 6: Unified Evaluation, Sections, Results Release"),
    ("phase_8_integrations", "migrations.migrate_phase8_integrations", "Phase 8: External Integrations (ServiceNow, Question Generator)"),
    ("phase_9_notifications", "migrations.migrate_phase9_notifications", "Phase 9: In-App & Email Notifications & Announcements"),
    ("phase_10_admin", "migrations.migrate_phase10_admin", "Phase 10: Platform & Org Administration, Audit Logs"),
    ("phase_11_advanced", "migrations.migrate_phase11_advanced_assessments", "Phase 11: Blueprints, Templates, Adaptive Engine, Attempt Policies")
]


def ensure_migration_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(100) PRIMARY KEY,
            description VARCHAR(255) NOT NULL,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()


def get_applied_migrations(conn):
    ensure_migration_table(conn)
    result = conn.execute(text("SELECT version FROM schema_migrations ORDER BY applied_at ASC"))
    return {row[0] for row in result.fetchall()}


def show_status(engine):
    inspector = inspect(engine)
    print("=" * 70)
    print(f"DATABASE MIGRATION STATUS (Target: {engine.url.render_as_string(hide_password=True)})")
    print("=" * 70)
    with engine.connect() as conn:
        applied = get_applied_migrations(conn)

    for version, mod_path, desc in MIGRATION_STEPS:
        status_label = "[APPLIED]" if version in applied else "[PENDING]"
        print(f"{status_label:<12} {version:<26} {desc}")
    print("=" * 70)


def run_upgrade(engine, confirm: bool = False):
    is_prod_target = "exam_proctor" in str(engine.url) and "staging" not in str(engine.url)
    if is_prod_target and not confirm:
        print("[ABORT] Target database appears to be PRODUCTION!")
        print("Explicit confirmation is required. Re-run with --confirm.")
        sys.exit(1)

    with engine.connect() as conn:
        applied = get_applied_migrations(conn)

    print(f"[MIGRATION] Starting migration upgrade on: {engine.url.render_as_string(hide_password=True)}")

    for version, mod_path, desc in MIGRATION_STEPS:
        if version in applied:
            print(f"[SKIP] {version} is already applied.")
            continue

        print(f"\n[APPLYING] {version}: {desc}...")
        try:
            mod = __import__(mod_path, fromlist=["upgrade"])
            res = mod.upgrade(engine)
            with engine.connect() as conn:
                conn.execute(
                    text("INSERT INTO schema_migrations (version, description, applied_at) VALUES (:ver, :desc, :now)"),
                    {"ver": version, "desc": desc, "now": utc_now()}
                )
                conn.commit()
            print(f"[SUCCESS] {version} applied successfully. Result: {res}")
        except Exception as e:
            print(f"[FATAL] Error applying migration {version}: {e}")
            raise


def run_downgrade(engine, target_version: str, confirm: bool = False):
    is_prod_target = "exam_proctor" in str(engine.url) and "staging" not in str(engine.url)
    if is_prod_target and not confirm:
        print("[ABORT] Target database appears to be PRODUCTION! Downgrade blocked without --confirm.")
        sys.exit(1)

    matching = next((m for m in MIGRATION_STEPS if m[0] == target_version), None)
    if not matching:
        print(f"[ERROR] Unknown migration version '{target_version}'.")
        print("Available versions:", [m[0] for m in MIGRATION_STEPS])
        sys.exit(1)

    version, mod_path, desc = matching
    with engine.connect() as conn:
        applied = get_applied_migrations(conn)
        if version not in applied:
            print(f"[WARN] {version} is not marked as applied in schema_migrations.")

    print(f"\n[REVERSING] {version}: {desc}...")
    try:
        mod = __import__(mod_path, fromlist=["downgrade"])
        res = mod.downgrade(engine)
        with engine.connect() as conn:
            conn.execute(text("DELETE FROM schema_migrations WHERE version = :ver"), {"ver": version})
            conn.commit()
        print(f"[SUCCESS] {version} downgraded successfully. Result: {res}")
    except Exception as e:
        print(f"[FATAL] Error downgrading {version}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="ExamProctor Migration Runner")
    parser.add_argument("action", choices=["status", "upgrade", "downgrade"], help="Action to perform")
    parser.add_argument("--version", help="Specific migration version (for downgrade)")
    parser.add_argument("--database-url", help="Override DATABASE_URL target")
    parser.add_argument("--confirm", action="store_true", help="Explicit confirmation for production operations")
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL
    target_engine = create_engine(db_url)

    if args.action == "status":
        show_status(target_engine)
    elif args.action == "upgrade":
        run_upgrade(target_engine, confirm=args.confirm)
    elif args.action == "downgrade":
        if not args.version:
            print("[ERROR] --version is required for downgrade.")
            sys.exit(1)
        run_downgrade(target_engine, target_version=args.version, confirm=args.confirm)


if __name__ == "__main__":
    main()
