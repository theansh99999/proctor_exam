"""
scripts/seed_super_admin.py
----------------------------
Secure Super Admin Provisioning Script for ExamProctor:
- Connects to configured database (local or production via DATABASE_URL)
- Hashes passwords using passlib bcrypt via auth.get_password_hash
- Prevents duplicate super admin creation
- Supports secure interactive input (getpass), environment variables, or CLI flags
- Never hardcodes or logs sensitive credentials
- Safe for one-time initialization on bare metal, Docker, or Render

Usage:
    # Interactive (secure password prompt):
    python scripts/seed_super_admin.py --email admin@example.com

    # Non-interactive with environment variables (ideal for CI/CD or Render One-Off jobs):
    SUPER_ADMIN_PASSWORD="StrongPassword123!" python scripts/seed_super_admin.py --email admin@example.com --non-interactive

    # Reset password of existing Super Admin:
    python scripts/seed_super_admin.py --email admin@example.com --reset-password
"""
import sys
import os
import argparse
import getpass
import re
import logging

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_super_admin")


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.match(pattern, email.strip()))


def main():
    parser = argparse.ArgumentParser(description="ExamProctor Secure Super Admin Provisioning")
    parser.add_argument(
        "--email",
        type=str,
        default=os.getenv("SUPER_ADMIN_EMAIL"),
        help="Super Admin email address (defaults to SUPER_ADMIN_EMAIL env var)"
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.getenv("DATABASE_URL"),
        help="Target database connection URL (defaults to DATABASE_URL env var)"
    )
    parser.add_argument(
        "--name",
        type=str,
        default=os.getenv("SUPER_ADMIN_NAME", "Platform Super Administrator"),
        help="Super Admin full name"
    )
    parser.add_argument(
        "--password",
        type=str,
        default=os.getenv("SUPER_ADMIN_PASSWORD"),
        help="Super Admin password (if omitted, prompts securely via getpass)"
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Update password if Super Admin account already exists"
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt for interactive input; fail if required fields are missing"
    )

    args = parser.parse_args()

    # 1. Resolve and validate email
    email = args.email
    if not email:
        if args.non-interactive:
            logger.error("Email is required in non-interactive mode. Pass --email or set SUPER_ADMIN_EMAIL.")
            sys.exit(1)
        email = input("Enter Super Admin email: ").strip()

    email = email.strip().lower()
    if not validate_email(email):
        logger.error("Invalid email address format: '%s'", email)
        sys.exit(1)

    name = args.name.strip() if args.name else "Platform Super Administrator"

    # 2. Resolve and validate password
    password = args.password
    if not password:
        if args.non-interactive:
            logger.error("Password is required in non-interactive mode. Pass --password or set SUPER_ADMIN_PASSWORD.")
            sys.exit(1)

        password = getpass.getpass("Enter Super Admin password (min 8 characters): ")
        confirm_password = getpass.getpass("Confirm Super Admin password: ")
        if password != confirm_password:
            logger.error("Passwords do not match.")
            sys.exit(1)

    if len(password) < 8:
        logger.error("Password must be at least 8 characters long.")
        sys.exit(1)

    # 3. Database operations
    try:
        import database
        import models
        import auth
        from core.rbac import PlatformRole
    except ImportError as e:
        logger.error("Failed to import ExamProctor core modules: %s", e)
        sys.exit(1)

    if args.database_url:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        engine = create_engine(args.database_url)
        models.Base.metadata.create_all(bind=engine)
        CustomSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = CustomSessionLocal()
    else:
        db = database.SessionLocal()
    try:
        existing_user = db.query(models.User).filter(models.User.email == email).first()

        if existing_user:
            if existing_user.role == PlatformRole.SUPER_ADMIN:
                if args.reset_password:
                    existing_user.password_hash = auth.get_password_hash(password)
                    existing_user.name = name
                    # Ensure active
                    if hasattr(existing_user, "is_active"):
                        existing_user.is_active = True
                    if hasattr(existing_user, "is_suspended"):
                        existing_user.is_suspended = False
                    db.commit()
                    logger.info("Successfully updated password for existing Super Admin: %s", email)
                    sys.exit(0)
                else:
                    logger.info("Super Admin account '%s' already exists (use --reset-password to update password).", email)
                    sys.exit(0)
            else:
                if args.reset_password:
                    logger.info("Elevating existing user '%s' (role: %s) to Super Admin...", email, existing_user.role)
                    existing_user.role = PlatformRole.SUPER_ADMIN
                    existing_user.password_hash = auth.get_password_hash(password)
                    existing_user.name = name
                    if hasattr(existing_user, "is_active"):
                        existing_user.is_active = True
                    if hasattr(existing_user, "is_suspended"):
                        existing_user.is_suspended = False
                    db.commit()
                    logger.info("Successfully elevated user '%s' to Super Admin.", email)
                    sys.exit(0)
                else:
                    logger.error("User with email '%s' already exists with role '%s'. Use --reset-password to elevate.", email, existing_user.role)
                    sys.exit(1)

        # Create new Super Admin
        logger.info("Creating new Super Admin account for: %s", email)
        hashed_password = auth.get_password_hash(password)

        new_super_admin = models.User(
            email=email,
            password_hash=hashed_password,
            name=name,
            role=PlatformRole.SUPER_ADMIN,
            organization_id=None,
            is_active=True,
            is_suspended=False
        )
        db.add(new_super_admin)
        db.commit()
        db.refresh(new_super_admin)

        # Log audit record if AdminService is available
        try:
            from modules.admin.service import AdminService
            AdminService.log_audit(
                db=db,
                action="admin.bootstrap_super_admin",
                entity_type="user",
                entity_id=str(new_super_admin.id),
                actor_id=new_super_admin.id,
                org_id=None,
                metadata={"email": email, "role": PlatformRole.SUPER_ADMIN}
            )
        except Exception:
            pass  # Audit logging failure should not abort successful admin creation

        logger.info("=" * 60)
        logger.info("SUPER ADMIN PROVISIONED SUCCESSFULLY")
        logger.info("Email: %s", email)
        logger.info("Name:  %s", name)
        logger.info("Role:  %s", PlatformRole.SUPER_ADMIN)
        logger.info("Login: Access the live website at /login using this email.")
        logger.info("=" * 60)

    except Exception as e:
        db.rollback()
        logger.error("Database error while provisioning Super Admin: %s", e)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
