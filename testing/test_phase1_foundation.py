"""
testing/test_phase1_foundation.py
---------------------------------
Comprehensive Test Suite for Phase 1 Architecture & Foundation:
1. Platform Roles & RBAC (Super Admin, Org Admin, Examiner, Candidate, legacy Teacher/Student)
2. Organization-Level Isolation & Multi-Tenancy enforcement
3. User Management with Org scoping
4. Multi-Purpose Assessment Foundation (academic, placement, technical, custom)
5. Backward Compatibility for existing Teacher/Student workflows
6. Integration Boundaries & Schema Contracts (Question Generator, Proctoring Engine, ServiceNow)
"""
import os
os.environ["TESTING"] = "1"

import unittest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models, auth
from main import app
from database import get_db, Base
from time_utils import utc_now
from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, engine, apply_test_db_override, clear_test_db_override
from core.rbac import (
    PlatformRole,
    normalize_role,
    is_super_admin,
    is_org_admin,
    is_examiner_or_admin,
    is_candidate,
    has_permission,
    Permission,
    verify_org_access
)

class TestPhase1Foundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apply_test_db_override()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        clear_test_db_override()

    def setUp(self):
        init_test_db()
        self.db = TestingSessionLocal()
        self._seed_data()

    def tearDown(self):
        self.db.close()
        cleanup_test_db()

    def _seed_data(self):
        # 1. Super Admin
        self.super_admin = models.User(
            email="superadmin@platform.com",
            name="Super Admin",
            password_hash=auth.get_password_hash("SuperSecret123!"),
            role="super_admin"
        )
        self.db.add(self.super_admin)
        self.db.commit()

        # 2. Organizations
        self.org1 = models.Organization(name="Apex University", slug="apex-univ", description="Main campus")
        self.org2 = models.Organization(name="Beta Tech Institute", slug="beta-tech", description="Tech institute")
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 3. Org Admins
        self.org1_admin = models.User(
            email="admin@apex.edu",
            name="Apex Admin",
            password_hash=auth.get_password_hash("AdminSecret123!"),
            role="org_admin",
            organization_id=self.org1.id
        )
        self.org2_admin = models.User(
            email="admin@betatech.edu",
            name="Beta Admin",
            password_hash=auth.get_password_hash("AdminSecret123!"),
            role="org_admin",
            organization_id=self.org2.id
        )
        self.db.add_all([self.org1_admin, self.org2_admin])
        self.db.commit()

        # 4. Examiners & Candidates
        self.examiner1 = models.User(
            email="prof1@apex.edu",
            name="Apex Examiner",
            password_hash=auth.get_password_hash("ProfPass123!"),
            role="examiner",
            organization_id=self.org1.id
        )
        self.candidate1 = models.User(
            email="cand1@apex.edu",
            name="Apex Candidate",
            password_hash=auth.get_password_hash("CandPass123!"),
            role="candidate",
            organization_id=self.org1.id
        )

        # Legacy Teacher & Student (unaffiliated with org)
        self.legacy_teacher = models.User(
            email="legacy_prof@school.org",
            name="Legacy Teacher",
            password_hash=auth.get_password_hash("TeacherPass123!"),
            role="teacher"  # legacy role
        )
        self.legacy_student = models.User(
            email="legacy_stud@school.org",
            name="Legacy Student",
            password_hash=auth.get_password_hash("StudentPass123!"),
            role="student"  # legacy role
        )
        self.db.add_all([self.examiner1, self.candidate1, self.legacy_teacher, self.legacy_student])
        self.db.commit()

        # Tokens
        self.super_admin_token = auth.create_access_token({"sub": self.super_admin.email, "role": "super_admin"})
        self.org1_admin_token = auth.create_access_token({"sub": self.org1_admin.email, "role": "org_admin"})
        self.org2_admin_token = auth.create_access_token({"sub": self.org2_admin.email, "role": "org_admin"})
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.candidate1_token = auth.create_access_token({"sub": self.candidate1.email, "role": "candidate"})
        self.legacy_teacher_token = auth.create_access_token({"sub": self.legacy_teacher.email, "role": "teacher"})
        self.legacy_student_token = auth.create_access_token({"sub": self.legacy_student.email, "role": "student"})

    # =========================================================================
    # 1. ROLE MAPPING & RBAC PERMISSIONS FOUNDATION
    # =========================================================================
    def test_01_role_mapping_normalization(self):
        """Test normalization and backward compatibility of roles."""
        self.assertEqual(normalize_role("teacher"), PlatformRole.EXAMINER)
        self.assertEqual(normalize_role("examiner"), PlatformRole.EXAMINER)
        self.assertEqual(normalize_role("student"), PlatformRole.CANDIDATE)
        self.assertEqual(normalize_role("candidate"), PlatformRole.CANDIDATE)
        self.assertEqual(normalize_role("org_admin"), PlatformRole.ORG_ADMIN)
        self.assertEqual(normalize_role("super_admin"), PlatformRole.SUPER_ADMIN)

        # Helper checks
        self.assertTrue(is_super_admin(self.super_admin))
        self.assertFalse(is_super_admin(self.org1_admin))

        self.assertTrue(is_org_admin(self.org1_admin))
        self.assertTrue(is_org_admin(self.super_admin)) # super_admin has admin rights
        self.assertFalse(is_org_admin(self.examiner1))

        self.assertTrue(is_examiner_or_admin(self.legacy_teacher)) # legacy teacher recognized as examiner
        self.assertTrue(is_examiner_or_admin(self.examiner1))
        self.assertFalse(is_examiner_or_admin(self.candidate1))

        self.assertTrue(is_candidate(self.legacy_student)) # legacy student recognized as candidate
        self.assertTrue(is_candidate(self.candidate1))
        self.assertFalse(is_candidate(self.examiner1))

    def test_02_rbac_permissions_matrix(self):
        """Verify role permissions according to security matrix."""
        self.assertTrue(has_permission(self.super_admin, Permission.ORG_CREATE))
        self.assertTrue(has_permission(self.super_admin, Permission.USER_CREATE))
        self.assertTrue(has_permission(self.super_admin, Permission.ASSESSMENT_DELETE))

        # Org Admin cannot create other orgs
        self.assertFalse(has_permission(self.org1_admin, Permission.ORG_CREATE))
        self.assertTrue(has_permission(self.org1_admin, Permission.USER_CREATE))
        self.assertTrue(has_permission(self.org1_admin, Permission.ASSESSMENT_CREATE))

        # Examiner cannot create users or delete orgs
        self.assertFalse(has_permission(self.examiner1, Permission.USER_CREATE))
        self.assertFalse(has_permission(self.examiner1, Permission.ORG_DELETE))
        self.assertTrue(has_permission(self.examiner1, Permission.ASSESSMENT_CREATE))

        # Candidate can only take/read assessments and results
        self.assertFalse(has_permission(self.candidate1, Permission.ASSESSMENT_CREATE))
        self.assertTrue(has_permission(self.candidate1, Permission.ATTEMPT_START))
        self.assertTrue(has_permission(self.candidate1, Permission.RESULT_READ_OWN))

    # =========================================================================
    # 2. ORGANIZATION ISOLATION & ACCESS CONTROL
    # =========================================================================
    def test_03_super_admin_create_and_list_organizations(self):
        """Super Admin can create new organizations and list all organizations."""
        res = self.client.post(
            "/api/v1/organizations",
            json={"name": "Delta Research Labs", "slug": "delta-labs", "description": "AI Lab"},
            headers={"Authorization": f"Bearer {self.super_admin_token}"}
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["data"]["name"], "Delta Research Labs")

        # List all
        res_list = self.client.get(
            "/api/v1/organizations",
            headers={"Authorization": f"Bearer {self.super_admin_token}"}
        )
        self.assertEqual(res_list.status_code, 200)
        self.assertGreaterEqual(len(res_list.json()["data"]), 3)

    def test_04_org_admin_cross_organization_isolation(self):
        """Org Admin 1 cannot access, view, or modify Org 2."""
        # Org 1 admin can access Org 1
        res1 = self.client.get(
            f"/api/v1/organizations/{self.org1.id}",
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res1.status_code, 200)

        # Org 1 admin attempts to view Org 2 -> HTTP 403 Forbidden
        res2 = self.client.get(
            f"/api/v1/organizations/{self.org2.id}",
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res2.status_code, 403)

        # Org 1 admin attempts to update Org 2 -> HTTP 403 Forbidden
        res_up = self.client.put(
            f"/api/v1/organizations/{self.org2.id}",
            json={"name": "Hacked Name"},
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res_up.status_code, 403)

    def test_05_unauthorized_user_cannot_create_organization(self):
        """Examiners and Candidates cannot create organizations."""
        for token in [self.examiner1_token, self.candidate1_token, self.org1_admin_token]:
            res = self.client.post(
                "/api/v1/organizations",
                json={"name": "Forbidden Org", "slug": "forbidden-org"},
                headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(res.status_code, 403)

    # =========================================================================
    # 3. USER MANAGEMENT & ORG SCOPING
    # =========================================================================
    def test_06_org_admin_create_user_scoped_to_own_org(self):
        """Org Admin creates candidates and examiners strictly in their own org."""
        res = self.client.post(
            "/api/v1/users",
            json={
                "email": "new_student_apex@apex.edu",
                "password": "Password123!",
                "name": "Apex New Student",
                "role": "candidate"
            },
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertEqual(data["organization_id"], self.org1.id)

    def test_07_org_admin_cannot_create_admin_or_cross_org_user(self):
        """Org Admin cannot create super admin, org admin, or assign to other orgs."""
        # Attempt to create super admin
        res = self.client.post(
            "/api/v1/users",
            json={"email": "hacker@apex.edu", "password": "Password123!", "name": "Fake Admin", "role": "super_admin"},
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res.status_code, 403)

        # Attempt to create user in Org 2
        res2 = self.client.post(
            "/api/v1/users",
            json={"email": "intruder@beta.edu", "password": "Password123!", "name": "Intruder", "role": "candidate", "organization_id": self.org2.id},
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        # Should be forced to own org or rejected
        if res2.status_code == 201:
            self.assertEqual(res2.json()["data"]["organization_id"], self.org1.id)

    # =========================================================================
    # 4. ASSESSMENT FOUNDATION (CONFIGURABLE MULTI-PURPOSE ASSESSMENTS)
    # =========================================================================
    def test_08_create_configurable_assessment_types(self):
        """Verify creation of placement, technical, academic, and custom assessments with config_metadata."""
        now = utc_now()
        assessment_types = ["academic", "placement", "technical", "custom"]

        for atype in assessment_types:
            payload = {
                "title": f"Apex {atype.capitalize()} Assessment",
                "description": f"Comprehensive {atype} assessment test.",
                "assessment_type": atype,
                "start_time": (now - timedelta(minutes=10)).isoformat(),
                "end_time": (now + timedelta(hours=2)).isoformat(),
                "duration_minutes": 90,
                "timer_type": "per_question" if atype == "technical" else "overall",
                "default_marks": 5.0,
                "passing_marks": 25.0,
                "passing_criteria": "marks",
                "max_attempts": 2 if atype == "placement" else 1,
                "status": "published",
                "config_metadata": {
                    "proctoring_enabled": True,
                    "webcam_required": True,
                    "programming_languages": ["python", "cpp"] if atype == "technical" else []
                }
            }

            res = self.client.post(
                "/api/v1/assessments",
                json=payload,
                headers={"Authorization": f"Bearer {self.examiner1_token}"}
            )
            self.assertEqual(res.status_code, 201)
            data = res.json()["data"]
            self.assertEqual(data["assessment_type"], atype)
            self.assertEqual(data["organization_id"], self.org1.id)
            self.assertEqual(data["creator_id"], self.examiner1.id)
            self.assertEqual(data["config_metadata"]["proctoring_enabled"], True)

    def test_09_cross_organization_assessment_isolation(self):
        """Org 2 admin or examiners cannot view or modify assessments created in Org 1."""
        now = utc_now()
        # Create assessment in Org 1
        res_create = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Org 1 Confidential Test",
                "assessment_type": "placement",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "duration_minutes": 60
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_create.status_code, 201)
        asmnt_id = res_create.json()["data"]["id"]

        # Org 2 Admin attempts to read Org 1 assessment -> HTTP 403 Forbidden
        res_read = self.client.get(
            f"/api/v1/assessments/{asmnt_id}",
            headers={"Authorization": f"Bearer {self.org2_admin_token}"}
        )
        self.assertEqual(res_read.status_code, 403)

        # Org 2 Admin attempts to update Org 1 assessment -> HTTP 403 Forbidden
        res_up = self.client.put(
            f"/api/v1/assessments/{asmnt_id}",
            json={"title": "Unauthorized Tamper"},
            headers={"Authorization": f"Bearer {self.org2_admin_token}"}
        )
        self.assertEqual(res_up.status_code, 403)

    # =========================================================================
    # 5. BACKWARD COMPATIBILITY & LEGACY TEACHER/STUDENT WORKFLOWS
    # =========================================================================
    def test_10_legacy_teacher_and_student_compatibility(self):
        """Ensure legacy Teacher and Student can access their respective dashboards and APIs without disruption."""
        # 1. Legacy Teacher accesses /teacher/dashboard
        res_teach = self.client.get(
            "/teacher/dashboard",
            headers={"Authorization": f"Bearer {self.legacy_teacher_token}"}
        )
        self.assertEqual(res_teach.status_code, 200)

        # 2. Legacy Student accesses /student/dashboard
        res_stud = self.client.get(
            "/student/dashboard",
            headers={"Authorization": f"Bearer {self.legacy_student_token}"}
        )
        self.assertEqual(res_stud.status_code, 200)

        # 3. New Examiner accesses /teacher/dashboard
        res_exam = self.client.get(
            "/teacher/dashboard",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_exam.status_code, 200)

        # 4. New Candidate accesses /student/dashboard
        res_cand = self.client.get(
            "/student/dashboard",
            headers={"Authorization": f"Bearer {self.candidate1_token}"}
        )
        self.assertEqual(res_cand.status_code, 200)

    # =========================================================================
    # 6. INTEGRATION BOUNDARY CONTRACTS & SCHEMAS
    # =========================================================================
    def test_11_question_generator_boundary_contract(self):
        """Test Question Generator payload validation boundary."""
        now = utc_now()
        # Create an assessment to link questions
        exam = models.Exam(
            title="QG Target Assessment",
            start_time=now,
            end_time=now + timedelta(hours=1),
            duration_minutes=60,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id
        )
        self.db.add(exam)
        self.db.commit()

        payload = {
            "assessment_id": exam.id,
            "source_model": "gemini-2.5-pro",
            "batch_id": "batch-101",
            "questions": [
                {
                    "text": "What is the time complexity of QuickSort in the average case?",
                    "marks": 2.0,
                    "negative_marks": 0.5,
                    "difficulty": "medium",
                    "topic": "Algorithms",
                    "options": [
                        {"text": "O(N log N)", "is_correct": True, "explanation": "Divide and conquer"},
                        {"text": "O(N^2)", "is_correct": False},
                        {"text": "O(N)", "is_correct": False}
                    ]
                }
            ]
        }
        res = self.client.post(
            "/api/v1/integrations/question-generator/validate",
            json=payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["data"]["valid"])
        self.assertEqual(res.json()["data"]["question_count"], 1)

    def test_12_proctoring_and_servicenow_boundary_contracts(self):
        """Test External AI Proctoring and ServiceNow contract boundaries."""
        # Proctoring telemetry
        proctor_payload = {
            "session_id": "session-xyz-123",
            "events": [
                {
                    "exam_id": 1,
                    "student_id": self.candidate1.id,
                    "event_type": "multiple_faces",
                    "confidence_score": 0.94,
                    "timestamp": utc_now().isoformat(),
                    "metadata": {"faces_detected": 2}
                }
            ]
        }
        res_proc = self.client.post(
            "/api/v1/integrations/exam-proctor/validate-event",
            json=proctor_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_proc.status_code, 200)
        self.assertTrue(res_proc.json()["data"]["valid"])

        # ServiceNow sync contract
        exam = models.Exam(
            title="ServiceNow Target Exam",
            start_time=utc_now(),
            end_time=utc_now() + timedelta(hours=1),
            duration_minutes=60
        )
        self.db.add(exam)
        self.db.commit()

        snow_payload = {
            "assessment_id": exam.id,
            "servicenow_course_sys_id": "sys_id_abc_456",
            "auto_sync_grades": True
        }
        res_snow = self.client.post(
            "/api/v1/integrations/servicenow/validate-sync",
            json=snow_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_snow.status_code, 200)
        self.assertTrue(res_snow.json()["data"]["valid"])


if __name__ == "__main__":
    unittest.main()
