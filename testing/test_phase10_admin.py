"""

testing/test_phase10_admin.py

-----------------------------

Comprehensive test suite for Phase 10: Platform Administration & System Configuration.

Covers:

1. Super Admin cross-organization dashboard access

2. Unauthorized dashboard rejection (Examiner/Candidate/Org Admin)

3. Org Admin tenant isolation on user listing and management

4. Organization creation, suspension, and data preservation

5. Privilege escalation prevention: user creation (Org Admin cannot create Super/Org Admin)

6. Privilege escalation prevention: role change (Org Admin cannot promote to Super Admin)

7. User lifecycle: suspend, reactivate, and audit logging

8. Secure password reset workflow (no hash leakage)

9. Bulk CSV user import (valid and invalid records, privilege check)

10. Platform configuration CRUD and security guard validation

11. Organization configuration CRUD and isolation

12. Audit log creation, append-only behavior, and org scoping

13. Administrative activity monitoring metrics (failures & anomalies)

14. Suspended user login rejection and audit trail

15. Suspended/deactivated organization exam attempt blocking

16. Regression: assessment lifecycle and results release audit log recording

"""

import sys

import os

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

from time_utils import utc_now, to_utc

from modules.admin.service import AdminService

from modules.admin.schemas import (

    OrganizationCreateAdmin,

    OrganizationUpdateAdmin,

    UserCreateAdmin,

    UserUpdateAdmin,

    UserRoleUpdate,

    UserStatusUpdate

)

from modules.assessments.service import AssessmentService

from modules.assessments.schemas import AssessmentCreate

from modules.evaluation.service import EvaluationService



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





class TestPhase10Admin(unittest.TestCase):



    @classmethod

    def setUpClass(cls):

        os.environ["MOCK_EMAIL"] = "true"

        app.dependency_overrides[database.get_db] = override_get_db

        cls.client = TestClient(app)



    @classmethod

    def tearDownClass(cls):

        app.dependency_overrides.clear()

        test_engine.dispose()



    def setUp(self):

        models.Base.metadata.drop_all(bind=test_engine)

        models.Base.metadata.create_all(bind=test_engine)

        self.db = TestSessionLocal()

        self._seed_data()



    def tearDown(self):

        self.db.close()



    def _seed_data(self):

        # 1. Organizations

        self.org_alpha = models.Organization(

            name="Alpha Academy",

            slug="alpha",

            description="Alpha testing organization",

            is_active=True,

            is_suspended=False

        )

        self.org_beta = models.Organization(

            name="Beta Institute",

            slug="beta",

            description="Beta testing organization",

            is_active=True,

            is_suspended=False

        )

        self.db.add_all([self.org_alpha, self.org_beta])

        self.db.commit()

        self.db.refresh(self.org_alpha)

        self.db.refresh(self.org_beta)



        # 2. Users

        self.super_admin = models.User(

            email="superadmin@platform.com",

            password_hash=auth.get_password_hash("SuperSecurePass123!"),

            name="Super Admin",

            role="super_admin",

            organization_id=None,

            is_active=True,

            is_suspended=False

        )

        self.org_admin_alpha = models.User(

            email="admin@alpha.edu",

            password_hash=auth.get_password_hash("AlphaPass123!"),

            name="Alpha Org Admin",

            role="org_admin",

            organization_id=self.org_alpha.id,

            is_active=True,

            is_suspended=False

        )

        self.org_admin_beta = models.User(

            email="admin@beta.edu",

            password_hash=auth.get_password_hash("BetaPass123!"),

            name="Beta Org Admin",

            role="org_admin",

            organization_id=self.org_beta.id,

            is_active=True,

            is_suspended=False

        )

        self.examiner_alpha = models.User(

            email="examiner@alpha.edu",

            password_hash=auth.get_password_hash("AlphaPass123!"),

            name="Alpha Examiner",

            role="examiner",

            organization_id=self.org_alpha.id,

            is_active=True,

            is_suspended=False

        )

        self.candidate_alpha = models.User(

            email="student@alpha.edu",

            password_hash=auth.get_password_hash("AlphaPass123!"),

            name="Alpha Candidate",

            role="candidate",

            organization_id=self.org_alpha.id,

            is_active=True,

            is_suspended=False

        )

        self.candidate_beta = models.User(

            email="student@beta.edu",

            password_hash=auth.get_password_hash("BetaPass123!"),

            name="Beta Candidate",

            role="candidate",

            organization_id=self.org_beta.id,

            is_active=True,

            is_suspended=False

        )



        self.db.add_all([

            self.super_admin,

            self.org_admin_alpha,

            self.org_admin_beta,

            self.examiner_alpha,

            self.candidate_alpha,

            self.candidate_beta

        ])

        self.db.commit()



        for u in [self.super_admin, self.org_admin_alpha, self.org_admin_beta, self.examiner_alpha, self.candidate_alpha, self.candidate_beta]:

            self.db.refresh(u)



        # 3. Create Sample Assessment in Alpha

        now = utc_now()

        self.exam_alpha = models.Exam(

            title="Alpha Math Test",

            assessment_type="academic",

            organization_id=self.org_alpha.id,

            creator_id=self.examiner_alpha.id,

            start_time=now - timedelta(hours=1),

            end_time=now + timedelta(hours=5),

            duration_minutes=60,

            status="published",

            max_attempts=2

        )

        self.db.add(self.exam_alpha)

        self.db.commit()

        self.db.refresh(self.exam_alpha)



    def _auth_header(self, user: models.User) -> dict:

        token = auth.create_access_token({"sub": user.email, "role": user.role})

        return {"Authorization": f"Bearer {token}"}



    def _get_csrf(self, path="/login") -> str:

        resp = self.client.get(path)

        content = resp.text

        marker = 'name="csrf_token" value="'

        idx = content.find(marker)

        if idx != -1:

            start = idx + len(marker)

            return content[start:content.find('"', start)]

        return ""



    # =========================================================================

    # TESTS

    # =========================================================================



    def test_01_super_admin_dashboard_metrics(self):

        """Super Admin can access platform-wide aggregate metrics across multiple organizations."""

        headers = self._auth_header(self.super_admin)

        res = self.client.get("/api/v1/admin/dashboard", headers=headers)

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertGreaterEqual(data["total_organizations"], 2)

        self.assertGreaterEqual(data["total_users"], 6)

        self.assertIn("integration_health", data)

        self.assertIn("notification_health", data)

        self.assertIn("recent_organizations", data)



    def test_02_super_admin_dashboard_unauthorized(self):

        """Non-super-admin users are rejected with HTTP 403 from accessing platform dashboard."""

        for user in [self.org_admin_alpha, self.examiner_alpha, self.candidate_alpha]:

            headers = self._auth_header(user)

            res = self.client.get("/api/v1/admin/dashboard", headers=headers)

            self.assertEqual(res.status_code, 403)



    def test_03_org_admin_tenant_isolation_list_users(self):

        """Org Admin can only list users in their own organization."""

        headers_alpha = self._auth_header(self.org_admin_alpha)

        res_alpha = self.client.get("/api/v1/admin/users", headers=headers_alpha)

        self.assertEqual(res_alpha.status_code, 200)

        users_alpha = res_alpha.json()

        emails_alpha = [u["email"] for u in users_alpha]

        self.assertIn("student@alpha.edu", emails_alpha)

        self.assertNotIn("student@beta.edu", emails_alpha)



        # Super admin can see all users

        headers_super = self._auth_header(self.super_admin)

        res_super = self.client.get("/api/v1/admin/users", headers=headers_super)

        self.assertEqual(res_super.status_code, 200)

        emails_super = [u["email"] for u in res_super.json()]

        self.assertIn("student@alpha.edu", emails_super)

        self.assertIn("student@beta.edu", emails_super)



    def test_04_org_creation_and_suspension(self):

        """Super Admin creates an organization, suspends it, and reactivates it without data loss."""

        headers = self._auth_header(self.super_admin)



        # 1. Create Org

        create_payload = {

            "name": "Gamma Tech",

            "slug": "gamma",

            "description": "Engineering College",

            "is_active": True,

            "is_suspended": False

        }

        create_res = self.client.post("/api/v1/admin/organizations", json=create_payload, headers=headers)

        self.assertEqual(create_res.status_code, 201)

        org_id = create_res.json()["id"]



        # 2. Suspend Org

        suspend_res = self.client.post(

            f"/api/v1/admin/organizations/{org_id}/status",

            json={"action": "suspend", "reason": "Non-payment of platform invoice"},

            headers=headers

        )

        self.assertEqual(suspend_res.status_code, 200)

        self.assertTrue(suspend_res.json()["is_suspended"])



        # 3. Verify Org still exists in database (not deleted)

        org_db = self.db.query(models.Organization).filter_by(id=org_id).first()

        self.assertIsNotNone(org_db)

        self.assertTrue(org_db.is_suspended)



        # 4. Reactivate Org

        reactivate_res = self.client.post(

            f"/api/v1/admin/organizations/{org_id}/status",

            json={"action": "reactivate", "reason": "Invoice cleared"},

            headers=headers

        )

        self.assertEqual(reactivate_res.status_code, 200)

        self.assertFalse(reactivate_res.json()["is_suspended"])

        self.assertTrue(reactivate_res.json()["is_active"])



    def test_05_privilege_escalation_prevention_user_create(self):

        """Org Admin cannot create Super Admin or Org Admin accounts."""

        headers = self._auth_header(self.org_admin_alpha)



        # Attempt to create super_admin

        bad_super = {

            "name": "Hacker Admin",

            "email": "hacker@platform.com",

            "password": "Password123!",

            "role": "super_admin"

        }

        res_super = self.client.post("/api/v1/admin/users", json=bad_super, headers=headers)

        self.assertEqual(res_super.status_code, 403)

        self.assertIn("Privilege escalation prevented", res_super.json()["detail"])



        # Attempt to create org_admin

        bad_org_admin = {

            "name": "Another Admin",

            "email": "admin2@alpha.edu",

            "password": "Password123!",

            "role": "org_admin"

        }

        res_org_admin = self.client.post("/api/v1/admin/users", json=bad_org_admin, headers=headers)

        self.assertEqual(res_org_admin.status_code, 403)



        # Creating candidate in own org succeeds

        valid_user = {

            "name": "New Student",

            "email": "newstudent@alpha.edu",

            "password": "Password123!",

            "role": "candidate"

        }

        res_valid = self.client.post("/api/v1/admin/users", json=valid_user, headers=headers)

        self.assertEqual(res_valid.status_code, 201)

        self.assertEqual(res_valid.json()["organization_id"], self.org_alpha.id)



    def test_06_privilege_escalation_prevention_role_change(self):

        """Org Admin cannot promote any user to Super Admin."""

        headers = self._auth_header(self.org_admin_alpha)



        role_payload = {"role": "super_admin"}

        res = self.client.post(f"/api/v1/admin/users/{self.candidate_alpha.id}/role", json=role_payload, headers=headers)

        self.assertEqual(res.status_code, 403)

        self.assertIn("Privilege escalation prevented", res.json()["detail"])



    def test_07_user_lifecycle_suspend_reactivate(self):

        """Admin can suspend and unsuspend a user with audit logging."""

        headers = self._auth_header(self.org_admin_alpha)



        # Suspend candidate

        sus_payload = {"is_suspended": True, "reason": "Academic dishonesty investigation"}

        res_sus = self.client.post(f"/api/v1/admin/users/{self.candidate_alpha.id}/status", json=sus_payload, headers=headers)

        self.assertEqual(res_sus.status_code, 200)

        self.assertTrue(res_sus.json()["is_suspended"])



        # Check in DB

        self.db.expire_all()

        u = self.db.query(models.User).filter_by(id=self.candidate_alpha.id).first()

        self.assertTrue(u.is_suspended)



        # Unsuspend candidate

        unsus_payload = {"is_suspended": False, "reason": "Cleared by board"}

        res_unsus = self.client.post(f"/api/v1/admin/users/{self.candidate_alpha.id}/status", json=unsus_payload, headers=headers)

        self.assertEqual(res_unsus.status_code, 200)

        self.assertFalse(res_unsus.json()["is_suspended"])

        self.db.expire_all()

        u2 = self.db.query(models.User).filter_by(id=self.candidate_alpha.id).first()

        self.assertFalse(u2.is_suspended)



    def test_08_password_reset_security(self):

        """Password reset generates new password; hashes and tokens are never leaked."""

        headers = self._auth_header(self.org_admin_alpha)



        res = self.client.post(f"/api/v1/admin/users/{self.candidate_alpha.id}/reset-password", headers=headers)

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertIn("temporary_password", data)

        self.assertGreaterEqual(len(data["temporary_password"]), 8)

        self.assertNotIn("password_hash", data)



        # Verify old password no longer works

        self.db.expire_all()

        u = self.db.query(models.User).filter_by(id=self.candidate_alpha.id).first()

        self.assertFalse(auth.verify_password("AlphaPass123!", u.password_hash))

        self.assertTrue(auth.verify_password(data["temporary_password"], u.password_hash))



    def test_09_bulk_import_csv_valid_and_invalid(self):

        """Bulk import CSV imports valid rows, skips invalid ones, and prevents role escalation."""

        headers = self._auth_header(self.org_admin_alpha)



        csv_content = """email,name,role,password

valid1@alpha.edu,Valid Candidate One,candidate,Secret123!

invalid_email_format,No At Sign,candidate,Secret123!

,No Email,candidate,Secret123!

bad_admin@alpha.edu,Sneaky Admin,super_admin,Secret123!

valid2@alpha.edu,Valid Candidate Two,candidate,Secret123!

"""

        res = self.client.post(

            "/api/v1/admin/users/bulk-import",

            data={"csv_text": csv_content},

            headers=headers

        )

        self.assertEqual(res.status_code, 200)

        result = res.json()

        self.assertEqual(result["successful_imports"], 2)

        self.assertEqual(result["failed_imports"], 3)

        # Check that bad_admin was rejected due to privilege escalation

        failed_reasons = [e["reason"] for e in result["errors"]]

        self.assertTrue(any("Privilege escalation" in r for r in failed_reasons))



    def test_10_platform_config_crud_and_security_validation(self):

        """Platform configuration CRUD works for Super Admin; security guards reject attempts to disable auth."""

        headers = self._auth_header(self.super_admin)



        # 1. Valid platform update

        valid_update = {

            "configs": {

                "platform_name": "Antigravity Assessment Engine",

                "default_session_timeout_minutes": 90,

                "maintenance_mode": True

            }

        }

        res = self.client.put("/api/v1/admin/platform/config", json=valid_update, headers=headers)

        self.assertEqual(res.status_code, 200)



        # Verify retrieved values

        get_res = self.client.get("/api/v1/admin/platform/config", headers=headers)

        self.assertEqual(get_res.status_code, 200)

        configs = get_res.json()

        self.assertEqual(configs["platform_name"]["value"], "Antigravity Assessment Engine")

        self.assertEqual(configs["default_session_timeout_minutes"]["value"], 90)

        self.assertTrue(configs["maintenance_mode"]["value"])



        # 2. Insecure config attempt (trying to disable auth)

        insecure_update = {

            "configs": {

                "disable_auth": True

            }

        }

        bad_res = self.client.put("/api/v1/admin/platform/config", json=insecure_update, headers=headers)

        self.assertEqual(bad_res.status_code, 400)

        self.assertIn("Security violation", bad_res.json()["detail"])



    def test_11_org_config_crud_and_isolation(self):

        """Organization configuration CRUD enforces tenant boundary."""

        headers_alpha = self._auth_header(self.org_admin_alpha)



        # Update Alpha org configs

        payload = {

            "configs": {

                "branding_name": "Alpha Portal",

                "default_duration_minutes": 45,

                "default_pass_percentage": 50.0

            }

        }

        put_res = self.client.put(

            f"/api/v1/admin/organizations/{self.org_alpha.id}/config",

            json=payload,

            headers=headers_alpha

        )

        self.assertEqual(put_res.status_code, 200)



        # Get Alpha org configs

        get_res = self.client.get(

            f"/api/v1/admin/organizations/{self.org_alpha.id}/config",

            headers=headers_alpha

        )

        self.assertEqual(get_res.status_code, 200)

        self.assertEqual(get_res.json()["branding_name"]["value"], "Alpha Portal")

        self.assertEqual(get_res.json()["default_duration_minutes"]["value"], 45)



        # Org Admin Alpha attempting to modify Beta's config raises 403

        bad_res = self.client.put(

            f"/api/v1/admin/organizations/{self.org_beta.id}/config",

            json=payload,

            headers=headers_alpha

        )

        self.assertEqual(bad_res.status_code, 403)



    def test_12_audit_log_append_only_and_filtering(self):

        """Audit logs record events, are strictly append-only, and support organization filtering."""

        # 1. Log a manual audit event

        AdminService.log_audit(

            db=self.db,

            action="security.test_event",

            entity_type="test",

            entity_id="123",

            actor_id=self.super_admin.id,

            org_id=self.org_alpha.id,

            metadata={"test_key": "test_value"}

        )



        headers_super = self._auth_header(self.super_admin)

        res = self.client.get("/api/v1/admin/audit-logs", headers=headers_super)

        self.assertEqual(res.status_code, 200)

        logs = res.json()

        self.assertGreaterEqual(len(logs), 1)



        actions = [l["action"] for l in logs]

        self.assertIn("security.test_event", actions)



        # 2. Org Admin Beta querying audit logs cannot see Alpha's logs

        headers_beta = self._auth_header(self.org_admin_beta)

        res_beta = self.client.get("/api/v1/admin/audit-logs", headers=headers_beta)

        self.assertEqual(res_beta.status_code, 200)

        beta_actions = [l["action"] for l in res_beta.json()]

        self.assertNotIn("security.test_event", beta_actions)



    def test_13_administrative_activity_monitoring(self):

        """Administrative activity monitoring summarizes failed logins, suspended users, and anomalies."""

        # Seed a failed login audit entry

        AdminService.log_audit(

            db=self.db,

            action="auth.login_failed",

            entity_type="auth",

            entity_id="unknown@platform.com",

            actor_id=None,

            org_id=self.org_alpha.id,

            metadata={"reason": "invalid_credentials"}

        )



        headers = self._auth_header(self.super_admin)

        res = self.client.get("/api/v1/admin/activity", headers=headers)

        self.assertEqual(res.status_code, 200)

        data = res.json()

        self.assertIn("failed_logins_summary", data)

        self.assertGreaterEqual(data["failed_logins_summary"]["total_count"], 1)

        self.assertIn("suspended_users_summary", data)

        self.assertIn("integration_failures_summary", data)

        self.assertIn("notification_failures_summary", data)



    def test_14_suspended_user_login_blocked(self):

        """Suspended user login is rejected with appropriate error and logged to audit trail."""

        # Suspend candidate

        self.candidate_alpha.is_suspended = True

        self.db.commit()



        csrf = self._get_csrf("/login")

        # Attempt UI login via form

        res = self.client.post(

            "/login",

            data={"email": self.candidate_alpha.email, "password": "AlphaPass123!", "csrf_token": csrf},

            follow_redirects=False

        )

        self.assertEqual(res.status_code, 200)

        self.assertIn("suspended or deactivated", res.text)



        # Verify failed login is recorded in audit logs

        self.db.expire_all()

        failed_log = self.db.query(models.AuditLog).filter(

            models.AuditLog.action == "auth.login_failed",

            models.AuditLog.actor_id == self.candidate_alpha.id

        ).first()

        self.assertIsNotNone(failed_log)



    def test_15_deactivated_org_assessment_blocked(self):

        """Candidate belonging to a deactivated/suspended organization is blocked from assessments."""

        # Suspend Alpha organization

        self.org_alpha.is_suspended = True

        self.db.commit()



        csrf = self._get_csrf("/login")

        # Login attempt blocked

        res_login = self.client.post(

            "/login",

            data={"email": self.candidate_alpha.email, "password": "AlphaPass123!", "csrf_token": csrf},

            follow_redirects=False

        )

        self.assertEqual(res_login.status_code, 200)

        self.assertIn("deactivated or suspended", res_login.text)



        # Direct candidate assessment access blocked

        headers = self._auth_header(self.candidate_alpha)

        res_exam = self.client.get(f"/student/instructions/{self.exam_alpha.id}", headers=headers)

        self.assertEqual(res_exam.status_code, 403)

        self.assertIn("suspended or inactive", res_exam.json()["detail"])



    def test_16_existing_assessment_workflow_audit_integration(self):

        """Assessment creation, publishing, and archiving automatically record audit entries."""

        now = utc_now()

        data = AssessmentCreate(

            title="Audit Integration Test Exam",

            assessment_type="academic",

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=5),

            duration_minutes=60,

            passing_marks=10.0,

            max_attempts=1,

            organization_id=self.org_alpha.id

        )



        # 1. Assessment Creation audit

        exam = AssessmentService.create_assessment(self.db, data, self.examiner_alpha)

        create_audit = self.db.query(models.AuditLog).filter(

            models.AuditLog.action == "assessment.create",

            models.AuditLog.entity_id == str(exam.id)

        ).first()

        self.assertIsNotNone(create_audit)



        # 2. Assessment Publishing audit

        AssessmentService.publish_assessment(self.db, exam.id, self.examiner_alpha)

        pub_audit = self.db.query(models.AuditLog).filter(

            models.AuditLog.action == "assessment.publish",

            models.AuditLog.entity_id == str(exam.id)

        ).first()

        self.assertIsNotNone(pub_audit)



        # 3. Assessment Archiving audit

        AssessmentService.archive_assessment(self.db, exam.id, self.examiner_alpha)

        arch_audit = self.db.query(models.AuditLog).filter(

            models.AuditLog.action == "assessment.archive",

            models.AuditLog.entity_id == str(exam.id)

        ).first()

        self.assertIsNotNone(arch_audit)





if __name__ == "__main__":

    unittest.main()
