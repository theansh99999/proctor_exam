"""
migrate_group_members.py — Database Relationship Migration & Rollback
----------------------------------------------------------------------
Migrates group_members from string-based student_email to relational student_id foreign key.
Preserves all existing records and provides safe rollback capabilities.
Compatible with both PostgreSQL and SQLite.
"""

import sys
import os
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import models
import auth
from database import engine, SessionLocal

def upgrade(db=None) -> dict:
    """
    Run forward migration:
    1. Ensures 'student_id' column exists in 'group_members'.
    2. Populates 'student_id' for all existing rows by matching student_email to users.email.
    3. If any student_email has no matching User record, creates a placeholder User so no member is lost.
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        from sqlalchemy.orm import sessionmaker
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        # Check dialect
        bind = db.get_bind()
        inspector = inspect(bind)
        columns = [c["name"] for c in inspector.get_columns("group_members")]

        if "student_id" not in columns:
            print("[MIGRATION] Adding student_id column to group_members...")
            if bind.dialect.name == "postgresql":
                db.execute(text("ALTER TABLE group_members ADD COLUMN student_id INTEGER REFERENCES users(id)"))
                db.execute(text("CREATE INDEX IF NOT EXISTS ix_group_members_student_id ON group_members(student_id)"))
            else:
                # SQLite
                db.execute(text("ALTER TABLE group_members ADD COLUMN student_id INTEGER"))
            db.commit()

        # Populate student_id from existing records
        members = db.query(models.GroupMember).all()
        updated_count = 0
        created_users_count = 0

        for m in members:
            if m.student_id is None and m.student_email:
                email = m.student_email.strip().lower()
                user = db.query(models.User).filter(models.User.email == email).first()
                if not user:
                    # Create student user so member record is preserved
                    user = models.User(
                        email=email,
                        name=email.split("@")[0].capitalize(),
                        role="student",
                        password_hash=auth.get_password_hash("ChangeMe123!")
                    )
                    db.add(user)
                    db.commit()
                    db.refresh(user)
                    created_users_count += 1

                m.student_id = user.id
                m.student_email = user.email
                updated_count += 1

        db.commit()
        result = {
            "status": "success",
            "action": "upgrade",
            "members_updated": updated_count,
            "placeholder_users_created": created_users_count
        }
        print(f"[MIGRATION] Upgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION] Upgrade failed: {e}")
        raise
    finally:
        if should_close:
            db.close()


def downgrade(db=None) -> dict:
    """
    Rollback migration:
    1. Ensures student_email column is populated from User.email for any records with student_id.
    2. Drops student_id column on PostgreSQL if desired, or sets student_id to NULL.
    """
    should_close = False
    if db is None:
        db = SessionLocal()
        should_close = True
    elif hasattr(db, "connect") and not hasattr(db, "get_bind"):
        from sqlalchemy.orm import sessionmaker
        SessionMaker = sessionmaker(bind=db)
        db = SessionMaker()
        should_close = True

    try:
        bind = db.get_bind()
        # Restore student_email from student_id for all members
        members = db.query(models.GroupMember).all()
        restored_count = 0
        for m in members:
            if m.student_id is not None and not m.student_email:
                user = db.query(models.User).filter(models.User.id == m.student_id).first()
                if user:
                    m.student_email = user.email
                    restored_count += 1
        db.commit()

        if bind.dialect.name == "postgresql":
            db.execute(text("ALTER TABLE group_members DROP COLUMN IF EXISTS student_id"))
            db.commit()

        result = {
            "status": "success",
            "action": "downgrade",
            "emails_restored": restored_count
        }
        print(f"[MIGRATION] Downgrade complete: {result}")
        return result
    except Exception as e:
        db.rollback()
        print(f"[MIGRATION] Downgrade failed: {e}")
        raise
    finally:
        if should_close:
            db.close()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    if action == "downgrade":
        downgrade()
    else:
        upgrade()
