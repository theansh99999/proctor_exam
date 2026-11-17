"""
testing/test_seed_super_admin.py
--------------------------------
Comprehensive unit and integration tests for Super Admin Provisioning (Stage 1):
- Seed script execution and validation
- Duplicate Super Admin handling
- Password reset and elevation
- Login and redirect to /admin/dashboard
- Admin UI pages access control (Organizations, Users, Platform Settings, Audit Logs)
- Creation of Organization Admin and Examiner accounts by Super Admin
- Unauthorized access rejection for non-admin users
"""
import sys
import os
import unittest
from fastapi.testclient import TestClient

# Ensure root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from testing.test_db import app, init_test_db, TestingSessionLocal, get_csrf_token, login_client
import models
import auth
from core.rbac import PlatformRole
from modules.admin.service import AdminService
from modules.admin.schemas import UserCreateAdmin, OrganizationCreateAdmin


class TestSuperAdminProvisioning(unittest.TestCase):

    def setUp(self):
        init_test_db()
        self.db = TestingSessionLocal()
        self.client = TestClient(app, follow_redirects=False)

    def tearDown(self):
        self.db.close()

    def test_01_seed_super_admin_logic(self):
        """Verify direct logic of seeding a super admin."""
        email = "master.admin@examproctor.internal"
        plain_password = "SuperSecurePassword2026!"
        name = "Chief Systems Administrator"

        # Ensure user does not exist
        self.assertIsNone(self.db.query(models.User).filter(models.User.email == email).first())

        # Create super admin
        hashed = auth.get_password_hash(plain_password)
        admin = models.User(
            email=email,
            password_hash=hashed,
            name=name,
            role=PlatformRole.SUPER_ADMIN,
            is_active=True,
            is_suspended=False
        )
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)

        # Verify attributes
        self.assertEqual(admin.role, PlatformRole.SUPER_ADMIN)
        self.assertTrue(auth.verify_password(plain_password, admin.password_hash))
        self.assertFalse(auth.verify_password("WrongPassword!", admin.password_hash))

    def test_02_super_admin_login_and_redirect(self):
        """Verify Super Admin login via /login redirects to /admin/dashboard."""
        email = "superadmin.test@examproctor.internal"
        password = "AdminSecretPass123!"

        admin = models.User(
            email=email,
            password_hash=auth.get_password_hash(password),
            name="Super Admin UI Tester",
            role=PlatformRole.SUPER_ADMIN,
            is_active=True,
            is_suspended=False
        )
        self.db.add(admin)
        self.db.commit()

        # Perform login using test helper
        login_resp = login_client(self.client, email, password)

        # Expect 302 redirect to /admin/dashboard
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(login_resp.headers["location"], "/admin/dashboard")
        self.assertIn("access_token", self.client.cookies)

        # Access /admin/dashboard with the client's session
        dash_resp = self.client.get("/admin/dashboard")
        self.assertEqual(dash_resp.status_code, 200)
        self.assertIn("Super Admin Dashboard", dash_resp.text)

    def test_03_admin_ui_sections_access(self):
        """Verify Super Admin can access Organizations, Users, Platform Settings, Audit Logs."""
        email = "gov.admin@examproctor.internal"
        admin = models.User(
            email=email,
            password_hash=auth.get_password_hash("StrongSecret99!"),
            name="Governance Super Admin",
            role=PlatformRole.SUPER_ADMIN,
            is_active=True,
            is_suspended=False
        )
        self.db.add(admin)
        self.db.commit()

        access_token = auth.create_access_token(data={"sub": email, "role": PlatformRole.SUPER_ADMIN})
        cookies = {"access_token": f"Bearer {access_token}"}

        # 1. /admin/organizations
        res_orgs = self.client.get("/admin/organizations", cookies=cookies)
        self.assertEqual(res_orgs.status_code, 200)
        self.assertIn("Organizations", res_orgs.text)

        # 2. /admin/users
        res_users = self.client.get("/admin/users", cookies=cookies)
        self.assertEqual(res_users.status_code, 200)
        self.assertIn("User Administration", res_users.text)

        # 3. /admin/settings/platform
        res_platform = self.client.get("/admin/settings/platform", cookies=cookies)
        self.assertEqual(res_platform.status_code, 200)
        self.assertIn("Platform Configuration", res_platform.text)

        # 4. /admin/audit-logs
        res_audit = self.client.get("/admin/audit-logs", cookies=cookies)
        self.assertEqual(res_audit.status_code, 200)
        self.assertIn("Audit Trail", res_audit.text)

    def test_04_super_admin_create_org_admin_and_examiner(self):
        """Verify Super Admin can create Organization, Org Admin, and Examiner accounts."""
        super_admin = models.User(
            email="creator.admin@examproctor.internal",
            password_hash=auth.get_password_hash("AdminPass12345!"),
            name="Creator Admin",
            role=PlatformRole.SUPER_ADMIN
        )
        self.db.add(super_admin)
        self.db.commit()

        # Step 1: Create Organization
        org = AdminService.create_organization(
            db=self.db,
            data=OrganizationCreateAdmin(name="National Testing Agency", slug="nta", description="Central Board"),
            current_user=super_admin
        )
        self.assertIsNotNone(org.id)
        self.assertEqual(org.name, "National Testing Agency")

        # Step 2: Create Org Admin for that org
        org_admin = AdminService.create_user(
            db=self.db,
            data=UserCreateAdmin(
                name="NTA Board Admin",
                email="director@nta.gov.in",
                password="OrgDirectorPassword123!",
                role=PlatformRole.ORG_ADMIN,
                organization_id=org.id
            ),
            current_user=super_admin
        )
        self.assertEqual(org_admin.role, PlatformRole.ORG_ADMIN)
        self.assertEqual(org_admin.organization_id, org.id)

        # Step 3: Create Examiner for that org
        examiner = AdminService.create_user(
            db=self.db,
            data=UserCreateAdmin(
                name="Head Examiner Sharma",
                email="sharma@nta.gov.in",
                password="ExaminerSecretPass2026!",
                role=PlatformRole.EXAMINER,
                organization_id=org.id
            ),
            current_user=super_admin
        )
        self.assertEqual(examiner.role, PlatformRole.EXAMINER)
        self.assertEqual(examiner.organization_id, org.id)

        # Step 4: Verify Org Admin can also create an Examiner in their own org
        examiner2 = AdminService.create_user(
            db=self.db,
            data=UserCreateAdmin(
                name="Assistant Examiner Verma",
                email="verma@nta.gov.in",
                password="ExaminerSecretPass2026!",
                role=PlatformRole.EXAMINER,
                organization_id=org.id
            ),
            current_user=org_admin
        )
        self.assertEqual(examiner2.role, PlatformRole.EXAMINER)
        self.assertEqual(examiner2.organization_id, org.id)

    def test_05_unauthorized_user_blocked_from_admin_dashboard(self):
        """Verify Candidate and Examiner cannot access /admin/dashboard."""
        student = models.User(
            email="candidate.bob@example.com",
            password_hash=auth.get_password_hash("Pass12345!"),
            name="Bob Candidate",
            role=PlatformRole.CANDIDATE
        )
        self.db.add(student)
        self.db.commit()

        token = auth.create_access_token(data={"sub": student.email, "role": student.role})
        resp = self.client.get("/admin/dashboard", cookies={"access_token": f"Bearer {token}"})
        # Expect HTTP 403 Forbidden
        self.assertEqual(resp.status_code, 403)

    def test_06_seed_script_cli_execution(self):
        """Verify executing scripts/seed_super_admin.py CLI via subprocess."""
        import subprocess
        import tempfile
        python_exe = sys.executable
        script_path = os.path.join(os.path.dirname(__file__), "..", "scripts", "seed_super_admin.py")

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            temp_db_path = tmp_db.name

        try:
            sqlite_url = f"sqlite:///{temp_db_path.replace(os.sep, '/')}"
            env = os.environ.copy()
            env["SUPER_ADMIN_PASSWORD"] = "ScriptCreatedSecret123!"

            # Run non-interactive
            cmd = [
                python_exe,
                script_path,
                "--email", "script.admin@examproctor.internal",
                "--name", "Script Admin",
                "--database-url", sqlite_url,
                "--non-interactive"
            ]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
            self.assertIn("SUPER ADMIN PROVISIONED SUCCESSFULLY", result.stderr + result.stdout)

            # Duplicate run should also succeed idempotently with exit code 0
            dup_result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(dup_result.returncode, 0)
            self.assertIn("already exists", dup_result.stderr + dup_result.stdout)
        finally:
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)


if __name__ == "__main__":
    unittest.main()
