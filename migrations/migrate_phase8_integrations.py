"""
migrations/migrate_phase8_integrations.py
-----------------------------------------
Phase 8 External Integrations & Interoperability Migration:
- Creates integration_configs table (per-org / global integration configuration & credentials)
- Creates integration_logs table (sanitized execution audit trail)
- Creates sync_records table (idempotency, external reference mapping, and sync status tracking)
- Fully reversible (upgrade and downgrade)
- Compatible with PostgreSQL and SQLite
- Preserves 100% of existing historical data and records
"""
import sys
import os
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import models
from database import SessionLocal

def upgrade(db=None) -> dict:
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        is_postgres = (bind.dialect.name == "postgresql")
        existing_tables = inspector.get_table_names()

        tables_created = []

        # 1. Create integration_configs table if missing
        if "integration_configs" not in existing_tables:
            print("[MIGRATION] Creating integration_configs table...")
            models.IntegrationConfig.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("integration_configs")
            db.commit()

        # 2. Create integration_logs table if missing
        if "integration_logs" not in existing_tables:
            print("[MIGRATION] Creating integration_logs table...")
            models.IntegrationLog.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("integration_logs")
            db.commit()

        # 3. Create sync_records table if missing
        if "sync_records" not in existing_tables:
            print("[MIGRATION] Creating sync_records table...")
            models.SyncRecord.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("sync_records")
            db.commit()

        print(f"[MIGRATION] Phase 8 upgrade complete: created {tables_created}")
        return {
            "status": "success",
            "action": "upgrade",
            "tables_created": tables_created
        }

    finally:
        if should_close:
            db.close()


def downgrade(db=None) -> dict:
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        bind = db.get_bind()
        inspector = inspect(bind)
        existing_tables = inspector.get_table_names()

        tables_dropped = []

        # Drop child tables first
        for tbl_name, tbl_cls in [
            ("sync_records", models.SyncRecord),
            ("integration_logs", models.IntegrationLog),
            ("integration_configs", models.IntegrationConfig)
        ]:
            if tbl_name in existing_tables:
                print(f"[MIGRATION] Dropping {tbl_name} table...")
                tbl_cls.__table__.drop(bind=bind, checkfirst=True)
                tables_dropped.append(tbl_name)
                db.commit()

        print(f"[MIGRATION] Phase 8 downgrade complete: dropped {tables_dropped}")
        return {
            "status": "success",
            "action": "downgrade",
            "tables_dropped": tables_dropped
        }

    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action == "downgrade":
        downgrade()
    else:
        upgrade()
