"""
migrations/migrate_phase9_notifications.py
-----------------------------------------
Phase 9 Notifications & Communication Center Migration:
- Creates notifications table (in-app notifications, categories, read/dismissed state)
- Creates notification_preferences table (per-user preferences for email, in-app, reminders, results, announcements)
- Creates announcements table (examiner communication history and targets)
- Creates notification_delivery_logs table (delivery audit, channels, idempotency, retries)
- Fully reversible (upgrade and downgrade)
- Compatible with PostgreSQL and SQLite
- Preserves 100% of existing historical data and records
"""
import sys
import os
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

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
        existing_tables = inspector.get_table_names()

        tables_created = []

        # 1. Create parent tables first, then child tables
        if "notification_preferences" not in existing_tables:
            print("[MIGRATION] Creating notification_preferences table...")
            models.NotificationPreference.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("notification_preferences")
            db.commit()

        if "notifications" not in existing_tables:
            print("[MIGRATION] Creating notifications table...")
            models.Notification.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("notifications")
            db.commit()

        if "announcements" not in existing_tables:
            print("[MIGRATION] Creating announcements table...")
            models.Announcement.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("announcements")
            db.commit()

        if "notification_delivery_logs" not in existing_tables:
            print("[MIGRATION] Creating notification_delivery_logs table...")
            models.NotificationDeliveryLog.__table__.create(bind=bind, checkfirst=True)
            tables_created.append("notification_delivery_logs")
            db.commit()

        print(f"[MIGRATION] Phase 9 upgrade complete: created {tables_created}")
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

        is_postgres = (bind.dialect.name == "postgresql")
        tables_dropped = []

        # Drop child tables first
        for tbl_name, tbl_cls in [
            ("notification_delivery_logs", models.NotificationDeliveryLog),
            ("announcements", models.Announcement),
            ("notifications", models.Notification),
            ("notification_preferences", models.NotificationPreference)
        ]:
            if tbl_name in existing_tables:
                print(f"[MIGRATION] Dropping {tbl_name} table...")
                if is_postgres:
                    from sqlalchemy import text
                    db.execute(text(f"DROP TABLE IF EXISTS {tbl_name} CASCADE;"))
                else:
                    tbl_cls.__table__.drop(bind=bind, checkfirst=True)
                tables_dropped.append(tbl_name)
                db.commit()

        print(f"[MIGRATION] Phase 9 downgrade complete: dropped {tables_dropped}")
        return {
            "status": "success",
            "action": "downgrade",
            "tables_dropped": tables_dropped
        }

    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Phase 9 Notifications Migration")
    parser.add_argument("--downgrade", action="store_true", help="Run downgrade migration")
    args = parser.parse_args()

    if args.downgrade:
        res = downgrade()
    else:
        res = upgrade()
    print("Migration result:", res)
