"""
testing/test_role_navigation_and_settings.py
--------------------------------------------
Automated regression tests for:
1. Super Admin Profile Role Identity (displays canonical Super Admin badge, not Student)
2. Centralized Dashboard Redirection (/dashboard routes correctly by role)
3. Profile Settings & Security (password confirmation, audit logging, cancel button)
4. Platform Maintenance Mode (candidate/examiner 503 block, Super Admin bypass, restoration)
5. Server-Side Pagination (users, organizations, audit logs, notifications)
"""
import sys
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["TESTING"] = "1"
os.environ["MOCK_EMAIL"] = "true"

import unittest
import json
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import database
import auth
from main import app
from time_utils import utc_now
from core.rbac import PlatformRole, get_dashboard_url, get_role_display_name
from core.maintenance import is_maintenance_mode, invalidate_maintenance_cache
from modules.admin.service import AdminService
from modules.notifications.service import NotificationService

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestRoleNavigationAndSettings(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["MOCK_EMAIL"] = "true"
        models.Base.metadata.create_all(bind=test_engine)
        app.dependency_overrides[database.get_db] = override_get_db
        cls._orig_session_local = database.SessionLocal
        database.SessionLocal = TestSessionLocal
        cls.client = TestClient(app, follow_redirects=False)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        database.SessionLocal = cls._orig_session_local
        models.Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        self.db = TestSessionLocal()
        # Clean up database tables for clean test state
        for tbl in reversed(models.Base.metadata.sorted_tables):
            self.db.execute(tbl.delete())
        self.db.commit()
        invalidate_maintenance_cache()

        # Create default test organization
        self.org = models.Organization(
            name="Test University",
            slug="test-univ",
            description="Test Org",
            is_active=True,
            is_suspended=False
        )
        self.db.add(self.org)
        self.db.commit()
        self.db.refresh(self.org)

        # Create users for all roles
        self.super_admin = models.User(
            email="superadmin@test.com",
            name="Super Administrator",
            password_hash=auth.get_password_hash("AdminPass123!"),
            role="super_admin",
            is_active=True,
            is_suspended=False,
            organization_id=None
        )
        self.org_admin = models.User(
            email="orgadmin@test.com",
            name="Org Admin User",
            password_hash=auth.get_password_hash("AdminPass123!"),
            role="org_admin",
            is_active=True,
            is_suspended=False,
            organization_id=self.org.id
        )
        self.examiner = models.User(
            email="examiner@test.com",
            name="Prof. Examiner",
            password_hash=auth.get_password_hash("AdminPass123!"),
            role="examiner",
            is_active=True,
            is_suspended=False,
            organization_id=self.org.id
        )
        self.candidate = models.User(
            email="candidate@test.com",
            name="Candidate Student",
            password_hash=auth.get_password_hash("AdminPass123!"),
            role="candidate",
            is_active=True,
            is_suspended=False,
            organization_id=self.org.id
        )
        self.db.add_all([self.super_admin, self.org_admin, self.examiner, self.candidate])
        self.db.commit()
        for u in (self.super_admin, self.org_admin, self.examiner, self.candidate):
            self.db.refresh(u)

    def tearDown(self):
        self.db.close()
        invalidate_maintenance_cache()

    def _get_auth_client(self, user: models.User) -> TestClient:
        token = auth.create_access_token(data={"sub": user.email, "role": user.role})
        client = TestClient(app, follow_redirects=False)
        client.cookies.set("access_token", token)
        return client

    def _post_settings(self, client: TestClient, data: dict):
        res = client.get("/settings")
        marker = 'name="csrf_token" value="'
        csrf_token = ""
        idx = res.text.find(marker)
        if idx != -1:
            start = idx + len(marker)
            csrf_token = res.text[start:res.text.find('"', start)]
        form_data = dict(data)
        form_data["csrf_token"] = csrf_token
        return client.post("/settings", data=form_data)

    # =========================================================================
    # 1. ROLE IDENTITY & PROFILE BADGES
    # =========================================================================

    def test_super_admin_profile_role_identity(self):
        """Super Admin profile displays Super Admin badge and not Student."""
        client = self._get_auth_client(self.super_admin)
        res = client.get("/profile")
        self.assertEqual(res.status_code, 200)
        content = res.text
        # Must show Super Admin role badge
        self.assertIn("Super Administrator", content)
        # Must NOT show Student badge for Super Admin
        self.assertNotIn("🎓 Student", content)
        # Must have Return to Dashboard pointing to /dashboard
        self.assertIn('href="/dashboard"', content)

    def test_examiner_and_candidate_profile_identity(self):
        """Examiner shows Examiner badge and Candidate shows Student badge."""
        client_ex = self._get_auth_client(self.examiner)
        res_ex = client_ex.get("/profile")
        self.assertEqual(res_ex.status_code, 200)
        self.assertIn("Examiner", res_ex.text)

        client_cand = self._get_auth_client(self.candidate)
        res_cand = client_cand.get("/profile")
        self.assertEqual(res_cand.status_code, 200)
        self.assertIn("Student", res_cand.text)

    # =========================================================================
    # 2. DASHBOARD REDIRECTION (/dashboard)
    # =========================================================================

    def test_dashboard_redirects_by_role(self):
        """Verify centralized /dashboard correctly routes each role."""
        # Super Admin -> /admin/dashboard
        client_sa = self._get_auth_client(self.super_admin)
        res_sa = client_sa.get("/dashboard")
        self.assertEqual(res_sa.status_code, 302)
        self.assertEqual(res_sa.headers.get("location"), "/admin/dashboard")

        # Org Admin -> /admin/organizations
        client_oa = self._get_auth_client(self.org_admin)
        res_oa = client_oa.get("/dashboard")
        self.assertEqual(res_oa.status_code, 302)
        self.assertEqual(res_oa.headers.get("location"), "/admin/organizations")

        # Examiner -> /teacher/dashboard
        client_ex = self._get_auth_client(self.examiner)
        res_ex = client_ex.get("/dashboard")
        self.assertEqual(res_ex.status_code, 302)
        self.assertEqual(res_ex.headers.get("location"), "/teacher/dashboard")

        # Candidate -> /student/dashboard
        client_ca = self._get_auth_client(self.candidate)
        res_ca = client_ca.get("/dashboard")
        self.assertEqual(res_ca.status_code, 302)
        self.assertEqual(res_ca.headers.get("location"), "/student/dashboard")

    # =========================================================================
    # 3. SETTINGS & PROFILE SECURITY
    # =========================================================================

    def test_settings_page_cancel_link(self):
        """Settings page Cancel button must route to /dashboard."""
        client = self._get_auth_client(self.super_admin)
        res = client.get("/settings")
        self.assertEqual(res.status_code, 200)
        self.assertIn('href="/dashboard"', res.text)
        self.assertIn('name="confirm_password"', res.text)

    def test_settings_password_confirmation_mismatch(self):
        """Updating password with mismatched confirmation is rejected with 400."""
        client = self._get_auth_client(self.super_admin)
        res = self._post_settings(
            client,
            {
                "name": "Super Administrator",
                "current_password": "AdminPass123!",
                "password": "NewSecretPass888!",
                "confirm_password": "DifferentPass999!"
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("do not match", res.text)

    def test_settings_password_short_length(self):
        """Updating password with < 8 chars is rejected with 400."""
        client = self._get_auth_client(self.super_admin)
        res = self._post_settings(
            client,
            {
                "name": "Super Administrator",
                "current_password": "AdminPass123!",
                "password": "short",
                "confirm_password": "short"
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 8 characters", res.text)

    def test_settings_wrong_current_password(self):
        """Updating password with incorrect current password is rejected with 400."""
        client = self._get_auth_client(self.super_admin)
        res = self._post_settings(
            client,
            {
                "name": "Super Administrator",
                "current_password": "WrongPassword123!",
                "password": "NewSecretPass888!",
                "confirm_password": "NewSecretPass888!"
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Current password is incorrect", res.text)

    def test_settings_successful_password_update_and_audit(self):
        """Updating password with correct credentials succeeds and creates audit log."""
        client = self._get_auth_client(self.super_admin)
        res = self._post_settings(
            client,
            {
                "name": "Super Administrator Updated",
                "current_password": "AdminPass123!",
                "password": "BrandNewPassword123!",
                "confirm_password": "BrandNewPassword123!"
            }
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/settings", res.headers.get("location"))

        # Verify password changed in DB
        db = TestSessionLocal()
        u = db.query(models.User).filter(models.User.id == self.super_admin.id).first()
        self.assertTrue(auth.verify_password("BrandNewPassword123!", u.password_hash))
        self.assertEqual(u.name, "Super Administrator Updated")

        # Verify audit log entry
        audit = db.query(models.AuditLog).filter(
            models.AuditLog.actor_id == self.super_admin.id,
            models.AuditLog.action == "auth.password_update"
        ).first()
        self.assertIsNotNone(audit)
        db.close()

    def test_settings_name_update_without_password(self):
        """Name update alone succeeds without needing current or new password."""
        client = self._get_auth_client(self.candidate)
        res = self._post_settings(
            client,
            {
                "name": "Jane Candidate Updated",
                "current_password": "",
                "password": "",
                "confirm_password": ""
            }
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/settings", res.headers.get("location"))

        db = TestSessionLocal()
        u = db.query(models.User).filter(models.User.id == self.candidate.id).first()
        self.assertEqual(u.name, "Jane Candidate Updated")
        db.close()

    # =========================================================================
    # 4. MAINTENANCE MODE ENFORCEMENT & BYPASS
    # =========================================================================

    def test_maintenance_mode_candidate_blocked_super_admin_bypasses(self):
        """When maintenance mode is active, candidate gets 503 while Super Admin bypasses."""
        # 1. Enable maintenance mode in DB
        AdminService.set_platform_config(
            db=self.db,
            key="maintenance_mode",
            value=True,
            value_type="bool",
            current_user=self.super_admin
        )
        invalidate_maintenance_cache()
        self.assertTrue(is_maintenance_mode())

        # 2. Candidate attempts to access student dashboard
        client_cand = self._get_auth_client(self.candidate)
        res_cand = client_cand.get("/student/dashboard")
        self.assertEqual(res_cand.status_code, 503)
        self.assertIn("System Maintenance", res_cand.text)

        # 3. Super Admin accesses admin dashboard (should NOT be blocked)
        client_sa = self._get_auth_client(self.super_admin)
        res_sa = client_sa.get("/admin/dashboard")
        self.assertEqual(res_sa.status_code, 200)

        # 4. Exempt paths (/login, /health) remain available
        res_login = self.client.get("/login")
        self.assertEqual(res_login.status_code, 200)
        res_health = self.client.get("/health")
        self.assertEqual(res_health.status_code, 200)

        # 5. Disable maintenance mode
        AdminService.set_platform_config(
            db=self.db,
            key="maintenance_mode",
            value=False,
            value_type="bool",
            current_user=self.super_admin
        )
        invalidate_maintenance_cache()
        self.assertFalse(is_maintenance_mode())

        # 6. Candidate access is immediately restored
        res_cand_restored = client_cand.get("/student/dashboard")
        self.assertEqual(res_cand_restored.status_code, 200)

    # =========================================================================
    # 5. SERVER-SIDE PAGINATION
    # =========================================================================

    def test_users_pagination(self):
        """Verify list_users_paginated calculates pages and limits correctly."""
        # Add 25 dummy users
        for i in range(25):
            u = models.User(
                email=f"dummy{i}@test.com",
                name=f"Dummy User {i:02d}",
                password_hash=auth.get_password_hash("Pass123!"),
                role="candidate",
                organization_id=self.org.id
            )
            self.db.add(u)
        self.db.commit()

        # Page 1 with page_size=10
        users_p1, total_count, total_pages = AdminService.list_users_paginated(
            db=self.db,
            current_user=self.super_admin,
            page=1,
            page_size=10
        )
        # 4 initial users + 25 dummy users = 29 total
        self.assertEqual(total_count, 29)
        self.assertEqual(total_pages, 3)
        self.assertEqual(len(users_p1), 10)

        # Page 3 with page_size=10
        users_p3, _, _ = AdminService.list_users_paginated(
            db=self.db,
            current_user=self.super_admin,
            page=3,
            page_size=10
        )
        self.assertEqual(len(users_p3), 9)

        # Verify UI renders pagination controls
        client = self._get_auth_client(self.super_admin)
        res = client.get("/admin/users?page=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Page", res.text)
        self.assertIn("Next", res.text)

    def test_organizations_pagination(self):
        """Verify list_organizations_paginated works as expected."""
        for i in range(15):
            o = models.Organization(
                name=f"Org {i:02d}",
                slug=f"org-{i:02d}",
                is_active=True,
                is_suspended=False
            )
            self.db.add(o)
        self.db.commit()

        orgs_p1, total_count, total_pages = AdminService.list_organizations_paginated(
            db=self.db,
            current_user=self.super_admin,
            page=1,
            page_size=5
        )
        # 1 initial + 15 = 16
        self.assertEqual(total_count, 16)
        self.assertEqual(total_pages, 4)
        self.assertEqual(len(orgs_p1), 5)

        client = self._get_auth_client(self.super_admin)
        res = client.get("/admin/organizations?page=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Showing Page", res.text)

    def test_audit_logs_pagination(self):
        """Verify get_audit_logs_paginated works as expected."""
        for i in range(35):
            AdminService.log_audit(
                db=self.db,
                action="test.action",
                entity_type="test_entity",
                entity_id=str(i),
                actor_id=self.super_admin.id
            )

        logs_p1, total_count, total_pages = AdminService.get_audit_logs_paginated(
            db=self.db,
            current_user=self.super_admin,
            page=1,
            page_size=10
        )
        self.assertGreaterEqual(total_count, 35)
        self.assertEqual(len(logs_p1), 10)

        client = self._get_auth_client(self.super_admin)
        res = client.get("/admin/audit-logs?page=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Showing Page", res.text)

    def test_notifications_pagination(self):
        """Verify notification center pagination."""
        for i in range(25):
            n = models.Notification(
                user_id=self.candidate.id,
                title=f"Notification {i}",
                message=f"Test message {i}",
                category="reminder",
                event_type="exam.reminder",
                is_read=False,
                is_dismissed=False
            )
            self.db.add(n)
        self.db.commit()

        client = self._get_auth_client(self.candidate)
        res = client.get("/notifications?page=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Showing Page", res.text)
        self.assertIn("← Back to Dashboard", res.text)


if __name__ == "__main__":
    unittest.main()
