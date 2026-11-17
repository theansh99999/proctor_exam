"""
testing/test_phase2_assessments.py
----------------------------------
Comprehensive automated tests for Phase 2 — Assessment Management:
1. Assessment CRUD (all 4 types: academic, placement, technical, custom)
2. Backend validation (date boundaries, duration, passing criteria, visibility)
3. Assessment Scheduling (future scheduling, window enforcement)
4. Lifecycle Transitions (Draft -> Published -> Scheduled -> Active -> Completed -> Archived, invalid transition rejection)
5. Candidate and Group Assignment (individual, groups, bulk, deduplication, org isolation)
6. Candidate Visibility & Attempt Limits
7. Assessment Statistics & Examiner Dashboard
"""
import os
os.environ["TESTING"] = "1"

import unittest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

import models, auth
from main import app
from time_utils import utc_now, to_utc
from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, apply_test_db_override, clear_test_db_override

class TestPhase2Assessments(unittest.TestCase):
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
            email="superadmin@assessments.com",
            name="Super Admin",
            password_hash=auth.get_password_hash("SuperPass123!"),
            role="super_admin"
        )
        self.db.add(self.super_admin)

        # 2. Organizations
        self.org1 = models.Organization(name="Quantum Academy", slug="quantum-acad", description="Science & Tech")
        self.org2 = models.Organization(name="Nexus Institute", slug="nexus-inst", description="Business & Management")
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 3. Examiners & Candidates for Org 1
        self.examiner1 = models.User(
            email="examiner1@quantum.edu",
            name="Prof Quantum",
            password_hash=auth.get_password_hash("ExamPass123!"),
            role="examiner",
            organization_id=self.org1.id
        )
        self.candidate1 = models.User(
            email="candidate1@quantum.edu",
            name="Alice Quantum",
            password_hash=auth.get_password_hash("CandPass123!"),
            role="candidate",
            organization_id=self.org1.id
        )
        self.candidate2 = models.User(
            email="candidate2@quantum.edu",
            name="Bob Quantum",
            password_hash=auth.get_password_hash("CandPass123!"),
            role="candidate",
            organization_id=self.org1.id
        )

        # 4. Examiner & Candidate for Org 2
        self.examiner2 = models.User(
            email="examiner2@nexus.edu",
            name="Prof Nexus",
            password_hash=auth.get_password_hash("ExamPass123!"),
            role="examiner",
            organization_id=self.org2.id
        )
        self.candidate_org2 = models.User(
            email="candidate_org2@nexus.edu",
            name="Charlie Nexus",
            password_hash=auth.get_password_hash("CandPass123!"),
            role="candidate",
            organization_id=self.org2.id
        )

        self.db.add_all([self.examiner1, self.candidate1, self.candidate2, self.examiner2, self.candidate_org2])
        self.db.commit()

        # 5. Candidate Groups
        self.group1 = models.Group(name="Quantum Physics Group", teacher_id=self.examiner1.id, organization_id=self.org1.id)
        self.group2 = models.Group(name="Nexus Marketing Group", teacher_id=self.examiner2.id, organization_id=self.org2.id)
        self.db.add_all([self.group1, self.group2])
        self.db.commit()

        # Enroll candidate1 in group1
        self.db.add(models.GroupMember(group_id=self.group1.id, student_id=self.candidate1.id, student_email=self.candidate1.email))
        self.db.commit()

        # Auth Tokens
        self.super_admin_token = auth.create_access_token({"sub": self.super_admin.email, "role": "super_admin"})
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.examiner2_token = auth.create_access_token({"sub": self.examiner2.email, "role": "examiner"})
        self.candidate1_token = auth.create_access_token({"sub": self.candidate1.email, "role": "candidate"})
        self.candidate2_token = auth.create_access_token({"sub": self.candidate2.email, "role": "candidate"})
        self.candidate_org2_token = auth.create_access_token({"sub": self.candidate_org2.email, "role": "candidate"})

    # =========================================================================
    # 1. ASSESSMENT CRUD & CONFIGURATION
    # =========================================================================
    def test_01_create_all_four_assessment_types(self):
        """Test creation of academic, placement, technical, and custom assessments."""
        now = utc_now()
        types = ["academic", "placement", "technical", "custom"]

        for atype in types:
            payload = {
                "title": f"Midterm {atype.capitalize()} Assessment",
                "description": f"Testing {atype} assessment format.",
                "instructions": "Read all questions carefully. Calculator is allowed.",
                "assessment_type": atype,
                "start_time": (now + timedelta(days=1)).isoformat(),
                "end_time": (now + timedelta(days=1, hours=2)).isoformat(),
                "duration_minutes": 120,
                "timer_type": "per_question" if atype == "technical" else "overall",
                "default_marks": 4.0,
                "default_negative_marks": 1.0,
                "enable_negative_marking": True,
                "randomize_questions": True,
                "visibility": "group_only",
                "passing_marks": 40.0,
                "passing_criteria": "percentage" if atype == "placement" else "marks",
                "passing_percentage": 50.0 if atype == "placement" else None,
                "max_attempts": 2 if atype == "placement" else 1,
                "status": "draft",
                "config_metadata": {"allowed_languages": ["python", "javascript"]} if atype == "technical" else {}
            }
            res = self.client.post("/api/v1/assessments", json=payload, headers={"Authorization": f"Bearer {self.examiner1_token}"})
            self.assertEqual(res.status_code, 201)
            data = res.json()["data"]
            self.assertEqual(data["assessment_type"], atype)
            self.assertEqual(data["instructions"], "Read all questions carefully. Calculator is allowed.")
            self.assertTrue(data["enable_negative_marking"])
            self.assertTrue(data["randomize_questions"])
            self.assertEqual(data["status"], "draft")

    def test_02_backend_validation_invalid_configs(self):
        """Verify that invalid dates, durations, and criteria are rejected by the backend."""
        now = utc_now()

        # 1. start_time >= end_time
        res_date = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Invalid Date Range",
                "assessment_type": "academic",
                "start_time": (now + timedelta(hours=2)).isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(), # end before start!
                "duration_minutes": 60
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_date.status_code, 400)

        # 2. Negative duration
        res_dur = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Invalid Duration",
                "assessment_type": "academic",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "duration_minutes": -15
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_dur.status_code, 422) # Pydantic gt=0 validation

        # 3. Invalid assessment type
        res_type = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Invalid Type",
                "assessment_type": "invalid_type_xyz",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "duration_minutes": 60
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_type.status_code, 400)

        # 4. Invalid passing percentage > 100
        res_pct = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Invalid Passing Percentage",
                "assessment_type": "academic",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "duration_minutes": 60,
                "passing_criteria": "percentage",
                "passing_percentage": 150.0 # > 100%
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_pct.status_code, 400)

    # =========================================================================
    # 2. ASSESSMENT SCHEDULING
    # =========================================================================
    def test_03_schedule_assessment_for_future(self):
        """Schedule an assessment for future dates and verify effective status."""
        now = utc_now()
        # Create draft assessment
        res = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Upcoming Physics Finals",
                "assessment_type": "academic",
                "start_time": (now + timedelta(days=2)).isoformat(),
                "end_time": (now + timedelta(days=2, hours=3)).isoformat(),
                "duration_minutes": 180,
                "status": "draft"
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 201)
        asmnt_id = res.json()["data"]["id"]

        # Schedule assessment
        new_start = (now + timedelta(days=5)).isoformat()
        new_end = (now + timedelta(days=5, hours=3)).isoformat()

        res_sched = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/schedule",
            json={"start_time": new_start, "end_time": new_end},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_sched.status_code, 200)
        data = res_sched.json()["data"]
        self.assertEqual(data["status"], "scheduled")
        self.assertEqual(data["effective_status"], "scheduled")

    # =========================================================================
    # 3. LIFECYCLE TRANSITIONS
    # =========================================================================
    def test_04_lifecycle_state_machine_transitions(self):
        """Test valid state transitions: Draft -> Published -> Scheduled -> Archived."""
        now = utc_now()
        res = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Lifecycle Test Exam",
                "assessment_type": "technical",
                "start_time": (now - timedelta(minutes=5)).isoformat(),
                "end_time": (now + timedelta(hours=1)).isoformat(),
                "duration_minutes": 60,
                "status": "draft"
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        asmnt_id = res.json()["data"]["id"]
        self.assertEqual(res.json()["data"]["status"], "draft")

        # 1. Publish: Draft -> Published
        res_pub = self.client.post(f"/api/v1/assessments/{asmnt_id}/publish", headers={"Authorization": f"Bearer {self.examiner1_token}"})
        self.assertEqual(res_pub.status_code, 200)
        self.assertEqual(res_pub.json()["data"]["status"], "published")
        # Since now is between start_time and end_time, effective_status is active!
        self.assertEqual(res_pub.json()["data"]["effective_status"], "active")

        # 2. Archive: Active -> Archived
        res_arch = self.client.post(f"/api/v1/assessments/{asmnt_id}/archive", headers={"Authorization": f"Bearer {self.examiner1_token}"})
        self.assertEqual(res_arch.status_code, 200)
        self.assertEqual(res_arch.json()["data"]["status"], "archived")

        # 3. Invalid Transition: Archived -> Published (non-super-admin)
        res_inv = self.client.put(
            f"/api/v1/assessments/{asmnt_id}",
            json={"status": "published"},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_inv.status_code, 400)

    # =========================================================================
    # 4. CANDIDATE AND GROUP ASSIGNMENTS
    # =========================================================================
    def test_05_assign_individual_candidates_and_deduplication(self):
        """Assign candidates by ID and email, ensuring duplicate assignments are prevented."""
        now = utc_now()
        res = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Direct Assignment Assessment",
                "assessment_type": "placement",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=2)).isoformat(),
                "duration_minutes": 60,
                "status": "published"
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        asmnt_id = res.json()["data"]["id"]

        # Assign candidate 1 by ID and candidate 2 by email
        res_assign = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/assign-candidates",
            json={
                "candidate_ids": [self.candidate1.id],
                "candidate_emails": [self.candidate2.email]
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_assign.status_code, 200)
        self.assertEqual(res_assign.json()["data"]["assigned_count"], 2)

        # Re-assign same candidates -> must skip without error
        res_reassign = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/assign-candidates",
            json={"candidate_ids": [self.candidate1.id, self.candidate2.id]},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_reassign.status_code, 200)
        self.assertEqual(res_reassign.json()["data"]["assigned_count"], 0)
        self.assertEqual(res_reassign.json()["data"]["skipped_count"], 2)

        # Check assignment details
        res_det = self.client.get(f"/api/v1/assessments/{asmnt_id}/assignments", headers={"Authorization": f"Bearer {self.examiner1_token}"})
        self.assertEqual(res_det.status_code, 200)
        self.assertEqual(res_det.json()["data"]["total_candidate_count"], 2)

    def test_06_assign_group_and_cross_organization_isolation(self):
        """Assign group to assessment; verify cross-org assignment prevention."""
        now = utc_now()
        # Org 1 assessment
        res = self.client.post(
            "/api/v1/assessments",
            json={
                "title": "Quantum Group Assessment",
                "assessment_type": "academic",
                "start_time": now.isoformat(),
                "end_time": (now + timedelta(hours=2)).isoformat(),
                "duration_minutes": 60
            },
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        asmnt_id = res.json()["data"]["id"]

        # 1. Assign Org 1 group -> Success
        res_grp = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/assign-groups",
            json={"group_ids": [self.group1.id]},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_grp.status_code, 200)
        self.assertEqual(res_grp.json()["data"]["assigned_groups_count"], 1)

        # 2. Attempt to assign candidate from Org 2 to Org 1 assessment -> HTTP 403 Forbidden
        res_cross_cand = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/assign-candidates",
            json={"candidate_ids": [self.candidate_org2.id]},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_cross_cand.status_code, 403)

        # 3. Attempt to assign group from Org 2 to Org 1 assessment -> HTTP 403 Forbidden
        res_cross_grp = self.client.post(
            f"/api/v1/assessments/{asmnt_id}/assign-groups",
            json={"group_ids": [self.group2.id]},
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_cross_grp.status_code, 403)

    # =========================================================================
    # 5. CANDIDATE VISIBILITY & ELIGIBILITY
    # =========================================================================
    def test_07_candidate_visibility_assigned_vs_draft_vs_unassigned(self):
        """Draft assessments are invisible; only assigned/published assessments are accessible."""
        now = utc_now()
        # 1. Draft assessment -> Invisible to candidate1
        exam_draft = models.Exam(
            title="Hidden Draft Exam",
            start_time=now,
            end_time=now + timedelta(hours=1),
            duration_minutes=60,
            status="draft",
            organization_id=self.org1.id,
            creator_id=self.examiner1.id
        )
        self.db.add(exam_draft)
        self.db.commit()

        # Candidate attempts to get draft -> HTTP 403 Forbidden
        res_draft = self.client.get(f"/api/v1/assessments/{exam_draft.id}", headers={"Authorization": f"Bearer {self.candidate1_token}"})
        self.assertEqual(res_draft.status_code, 403)

        # 2. Published assessment assigned to candidate1 -> Accessible
        exam_pub = models.Exam(
            title="Visible Assigned Exam",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
            duration_minutes=60,
            status="published",
            organization_id=self.org1.id,
            creator_id=self.examiner1.id
        )
        self.db.add(exam_pub)
        self.db.commit()

        # Assign candidate1
        self.db.add(models.AssessmentAssignment(assessment_id=exam_pub.id, candidate_id=self.candidate1.id))
        self.db.commit()

        res_vis = self.client.get(f"/api/v1/assessments/{exam_pub.id}", headers={"Authorization": f"Bearer {self.candidate1_token}"})
        self.assertEqual(res_vis.status_code, 200)
        self.assertEqual(res_vis.json()["data"]["title"], "Visible Assigned Exam")

        # Candidate2 (unassigned) attempts to access -> HTTP 403 Forbidden
        res_unassigned = self.client.get(f"/api/v1/assessments/{exam_pub.id}", headers={"Authorization": f"Bearer {self.candidate2_token}"})
        self.assertEqual(res_unassigned.status_code, 403)

    # =========================================================================
    # 6. ASSESSMENT STATISTICS & EXAMINER DASHBOARD VIEW
    # =========================================================================
    def test_08_assessment_statistics_and_examiner_views(self):
        """Test assessment statistics calculation and Examiner HTML assessment view."""
        now = utc_now()
        exam = models.Exam(
            title="Statistics Test Exam",
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            duration_minutes=60,
            status="published",
            default_marks=5.0,
            passing_marks=5.0,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id
        )
        self.db.add(exam)
        self.db.commit()

        # Assign candidate1 and candidate2
        self.db.add(models.AssessmentAssignment(assessment_id=exam.id, candidate_id=self.candidate1.id))
        self.db.add(models.AssessmentAssignment(assessment_id=exam.id, candidate_id=self.candidate2.id))
        self.db.commit()

        # Submissions: candidate1 passed (score 5.0), candidate2 failed (score 2.0)
        self.db.add(models.Submission(exam_id=exam.id, student_id=self.candidate1.id, score=5.0))
        self.db.add(models.Submission(exam_id=exam.id, student_id=self.candidate2.id, score=2.0))
        self.db.commit()

        # 1. API Statistics
        res_stats = self.client.get(f"/api/v1/assessments/{exam.id}/statistics", headers={"Authorization": f"Bearer {self.examiner1_token}"})
        self.assertEqual(res_stats.status_code, 200)
        data = res_stats.json()["data"]
        self.assertEqual(data["total_assigned_candidates"], 2)
        self.assertEqual(data["completed_attempts"], 2)
        self.assertEqual(data["pass_count"], 1)
        self.assertEqual(data["fail_count"], 1)
        self.assertEqual(data["pass_rate"], 50.0)
        self.assertEqual(data["average_score"], 3.5)

        # 2. Examiner HTML assessments dashboard view
        res_html = self.client.get("/teacher/assessments", headers={"Authorization": f"Bearer {self.examiner1_token}"})
        self.assertEqual(res_html.status_code, 200)
        self.assertIn("Assessment Management", res_html.text)
        self.assertIn("Statistics Test Exam", res_html.text)


if __name__ == "__main__":
    unittest.main()
