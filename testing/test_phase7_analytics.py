"""
testing/test_phase7_analytics.py
---------------------------------
Comprehensive Unit & Integration Test Suite for Phase 7:
1. Examiner Dashboard Analytics & Metrics with multi-criteria filters
2. Candidate Performance Analytics, Trend Detection & Topic Taxonomy
3. Candidate Privacy Enforcement (Unreleased results hidden, cross-student view forbidden)
4. Assessment Deep-Dive Analytics & Participation Funnels
5. Proctoring Separation (Integrity metrics strictly separated from academic scoring)
6. Question Bank Item Analytics & Zero-Division Safety (frequently incorrect flags)
7. Organization-Scoped Admin Dashboard & Multi-Tenant Boundary Enforcement
8. Super Admin Cross-Organization View
9. Downloadable CSV Reports (Assessment results, candidate history, question analytics)
10. Candidate Privacy in CSV Downloads
11. Topic & Subject Taxonomy Performance Tracking
"""
import unittest
import json
import io
import csv
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import database
import auth
from main import app
from time_utils import utc_now
from modules.analytics.service import AnalyticsService

# Isolated In-Memory SQLite Test Engine
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


class TestPhase7Analytics(unittest.TestCase):

    def setUp(self):
        app.dependency_overrides[database.get_db] = override_get_db
        models.Base.metadata.drop_all(bind=test_engine)
        models.Base.metadata.create_all(bind=test_engine)
        self.db = TestSessionLocal()
        self.client = TestClient(app)

        now = utc_now()

        # 1. Organizations
        self.org1 = models.Organization(name="Analytics Org Alpha", slug="org-alpha", is_active=True)
        self.org2 = models.Organization(name="Analytics Org Beta", slug="org-beta", is_active=True)
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 2. Users
        # Super Admin
        self.super_admin = models.User(
            email="super@test.com",
            name="Super Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="super_admin"
        )
        # Org 1 Admin & Examiner
        self.org1_admin = models.User(
            email="admin1@test.com",
            name="Org1 Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="org_admin",
            organization_id=self.org1.id
        )
        self.examiner1 = models.User(
            email="examiner1@test.com",
            name="Examiner One",
            password_hash=auth.get_password_hash("pass123"),
            role="examiner",
            organization_id=self.org1.id
        )
        # Org 2 Admin & Examiner
        self.org2_admin = models.User(
            email="admin2@test.com",
            name="Org2 Admin",
            password_hash=auth.get_password_hash("pass123"),
            role="org_admin",
            organization_id=self.org2.id
        )
        self.examiner2 = models.User(
            email="examiner2@test.com",
            name="Examiner Two",
            password_hash=auth.get_password_hash("pass123"),
            role="examiner",
            organization_id=self.org2.id
        )
        # Candidates
        self.student1 = models.User(
            email="student1@test.com",
            name="Student One",
            password_hash=auth.get_password_hash("pass123"),
            role="student",
            organization_id=self.org1.id
        )
        self.student2 = models.User(
            email="student2@test.com",
            name="Student Two",
            password_hash=auth.get_password_hash("pass123"),
            role="student",
            organization_id=self.org1.id
        )
        self.student3 = models.User(
            email="student3@test.com",
            name="Student Three",
            password_hash=auth.get_password_hash("pass123"),
            role="student",
            organization_id=self.org2.id
        )
        self.db.add_all([
            self.super_admin, self.org1_admin, self.examiner1,
            self.org2_admin, self.examiner2,
            self.student1, self.student2, self.student3
        ])
        self.db.commit()

        # 3. Groups
        self.group1 = models.Group(name="Class CS-101", teacher_id=self.examiner1.id, organization_id=self.org1.id)
        self.db.add(self.group1)
        self.db.commit()
        self.db.add_all([
            models.GroupMember(group_id=self.group1.id, student_id=self.student1.id),
            models.GroupMember(group_id=self.group1.id, student_id=self.student2.id)
        ])
        self.db.commit()

        # 4. Assessments
        # Exam 1: Academic (published, completed)
        self.exam1 = models.Exam(
            title="Data Structures Midterm",
            creator_id=self.examiner1.id,
            organization_id=self.org1.id,
            group_id=self.group1.id,
            assessment_type="academic",
            start_time=now - timedelta(days=2),
            end_time=now - timedelta(days=1),
            duration_minutes=60,
            default_marks=5.0,
            passing_marks=10.0,
            passing_percentage=50.0,
            status="completed",
            results_released=True
        )
        # Exam 2: Placement (active)
        self.exam2 = models.Exam(
            title="Campus Placement Coding Test",
            creator_id=self.examiner1.id,
            organization_id=self.org1.id,
            group_id=self.group1.id,
            assessment_type="placement",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            duration_minutes=90,
            default_marks=10.0,
            passing_marks=50.0,
            passing_percentage=60.0,
            status="active",
            results_released=False
        )
        # Exam 3: Org 2 Technical Exam
        self.exam3 = models.Exam(
            title="Backend Systems Architecture",
            creator_id=self.examiner2.id,
            organization_id=self.org2.id,
            assessment_type="technical",
            start_time=now - timedelta(days=5),
            end_time=now - timedelta(days=4),
            duration_minutes=120,
            default_marks=10.0,
            status="completed",
            results_released=True
        )
        self.db.add_all([self.exam1, self.exam2, self.exam3])
        self.db.commit()

        # 5. Questions for Exam 1
        # Q1: Hard question (most candidates get wrong -> frequently incorrect test)
        self.q1 = models.Question(
            exam_id=self.exam1.id,
            text="What is the worst-case time complexity of quicksort?",
            question_type="single_choice",
            marks=5.0,
            explanation="Algorithms / Complexity",
            order_index=1
        )
        # Q2: Easy question (most candidates get right)
        self.q2 = models.Question(
            exam_id=self.exam1.id,
            text="Is an array a contiguous block of memory?",
            question_type="true_false",
            marks=5.0,
            explanation="Data Structures / Arrays",
            order_index=2
        )
        # Q3: Unattempted question (for zero-division safety test)
        self.q3 = models.Question(
            exam_id=self.exam1.id,
            text="Explain AVL tree rebalancing in detail.",
            question_type="descriptive",
            marks=10.0,
            explanation="Data Structures / Trees",
            order_index=3
        )
        self.db.add_all([self.q1, self.q2, self.q3])
        self.db.commit()

        # Options for Q1 and Q2
        self.opt1_corr = models.Option(question_id=self.q1.id, text="O(n^2)", is_correct=True)
        self.opt1_inc = models.Option(question_id=self.q1.id, text="O(n log n)", is_correct=False)
        self.opt2_corr = models.Option(question_id=self.q2.id, text="True", is_correct=True)
        self.opt2_inc = models.Option(question_id=self.q2.id, text="False", is_correct=False)
        self.db.add_all([self.opt1_corr, self.opt1_inc, self.opt2_corr, self.opt2_inc])
        self.db.commit()

        # 6. Sessions & Submissions for Exam 1
        # Student 1: 5 / 10 marks (50%, PASS)
        self.sess1 = models.ExamSession(
            exam_id=self.exam1.id,
            student_id=self.student1.id,
            attempt_number=1,
            status="submitted",
            submitted_at=now - timedelta(days=1),
            integrity_score=95.0,
            risk_level="low"
        )
        self.db.add(self.sess1)
        self.db.commit()
        # Answers for Student 1: Q1 wrong, Q2 correct
        self.ans1_q1 = models.StudentAnswer(
            exam_session_id=self.sess1.id,
            question_id=self.q1.id,
            selected_option_id=self.opt1_inc.id,
            is_correct=False,
            marks_awarded=0.0,
            evaluation_status="evaluated"
        )
        self.ans1_q2 = models.StudentAnswer(
            exam_session_id=self.sess1.id,
            question_id=self.q2.id,
            selected_option_id=self.opt2_corr.id,
            is_correct=True,
            marks_awarded=5.0,
            evaluation_status="evaluated"
        )
        self.res1 = models.ExamResult(
            exam_id=self.exam1.id,
            student_id=self.student1.id,
            exam_session_id=self.sess1.id,
            attempt_number=1,
            marks_obtained=5.0,
            total_marks=10.0,
            percentage=50.0,
            pass_fail_status="PASS",
            correct_count=1,
            incorrect_count=1,
            unanswered_count=1,
            is_released=True,
            submission_timestamp=now - timedelta(days=1)
        )
        self.db.add_all([self.ans1_q1, self.ans1_q2, self.res1])

        # Student 2: 0 / 10 marks (0%, FAIL)
        self.sess2 = models.ExamSession(
            exam_id=self.exam1.id,
            student_id=self.student2.id,
            attempt_number=1,
            status="submitted",
            submitted_at=now - timedelta(days=1),
            integrity_score=70.0,
            risk_level="medium"
        )
        self.db.add(self.sess2)
        self.db.commit()
        # Answers for Student 2: Q1 wrong, Q2 wrong
        self.ans2_q1 = models.StudentAnswer(
            exam_session_id=self.sess2.id,
            question_id=self.q1.id,
            selected_option_id=self.opt1_inc.id,
            is_correct=False,
            marks_awarded=0.0,
            evaluation_status="evaluated"
        )
        self.ans2_q2 = models.StudentAnswer(
            exam_session_id=self.sess2.id,
            question_id=self.q2.id,
            selected_option_id=self.opt2_inc.id,
            is_correct=False,
            marks_awarded=0.0,
            evaluation_status="evaluated"
        )
        self.res2 = models.ExamResult(
            exam_id=self.exam1.id,
            student_id=self.student2.id,
            exam_session_id=self.sess2.id,
            attempt_number=1,
            marks_obtained=0.0,
            total_marks=10.0,
            percentage=0.0,
            pass_fail_status="FAIL",
            correct_count=0,
            incorrect_count=2,
            unanswered_count=1,
            is_released=True,
            submission_timestamp=now - timedelta(days=1)
        )
        self.db.add_all([self.ans2_q1, self.ans2_q2, self.res2])

        # Add a cheat flag for proctoring separation test
        self.flag1 = models.CheatFlag(
            exam_id=self.exam1.id,
            student_id=self.student2.id,
            exam_session_id=self.sess2.id,
            event_type="multiple_faces",
            severity="medium",
            description="Multiple faces detected in frame"
        )
        self.db.add(self.flag1)

        # 7. Student 1 Attempt 2 on Exam 2 (Unreleased result, score: 80%)
        # This gives Student 1 two attempts total (Attempt 1 = 50%, Attempt 2 = 80% -> improvement!)
        self.sess1_att2 = models.ExamSession(
            exam_id=self.exam2.id,
            student_id=self.student1.id,
            attempt_number=1,
            status="submitted",
            submitted_at=now - timedelta(hours=1),
            integrity_score=100.0,
            risk_level="low"
        )
        self.db.add(self.sess1_att2)
        self.db.commit()
        self.res1_att2 = models.ExamResult(
            exam_id=self.exam2.id,
            student_id=self.student1.id,
            exam_session_id=self.sess1_att2.id,
            attempt_number=1,
            marks_obtained=80.0,
            total_marks=100.0,
            percentage=80.0,
            pass_fail_status="PASS",
            correct_count=8,
            incorrect_count=2,
            unanswered_count=0,
            is_released=False,  # UNRELEASED!
            submission_timestamp=now - timedelta(hours=1)
        )
        self.db.add(self.res1_att2)
        self.db.commit()

        # Auth Tokens
        self.super_token = auth.create_access_token({"sub": self.super_admin.email, "role": "super_admin"})
        self.org1_admin_token = auth.create_access_token({"sub": self.org1_admin.email, "role": "org_admin"})
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.org2_admin_token = auth.create_access_token({"sub": self.org2_admin.email, "role": "org_admin"})
        self.examiner2_token = auth.create_access_token({"sub": self.examiner2.email, "role": "examiner"})
        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "student"})
        self.student2_token = auth.create_access_token({"sub": self.student2.email, "role": "student"})

    def tearDown(self):
        self.db.close()
        models.Base.metadata.drop_all(bind=test_engine)

    # =========================================================================
    # 1. EXAMINER DASHBOARD METRICS
    # =========================================================================
    def test_01_examiner_dashboard_summary(self):
        """Examiner dashboard aggregates total assessments, attempts, scores, and pass rates."""
        res = self.client.get(
            "/api/v1/analytics/examiner/summary",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["total_assessments"], 2)
        self.assertEqual(data["status_counts"]["completed"], 1)
        self.assertEqual(data["status_counts"]["active"], 1)
        self.assertEqual(data["total_candidates_assigned"], 2)
        # Total attempts on Exam1 (2) + Exam2 (1) = 3
        self.assertEqual(data["total_attempts"], 3)
        self.assertGreater(data["average_percentage"], 0.0)
        self.assertIn("pass_rate", data)
        self.assertIn("fail_rate", data)
        self.assertEqual(data["awaiting_release_count"], 1)  # Exam2 is unreleased

    # =========================================================================
    # 2. EXAMINER FILTERS (TYPE, STATUS, DATE, ASSESSMENT ID)
    # =========================================================================
    def test_02_examiner_dashboard_filters(self):
        """Filters by assessment type and status correctly scope analytics."""
        # Filter by assessment_type=placement
        res = self.client.get(
            "/api/v1/analytics/examiner/summary?assessment_type=placement",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_assessments"], 1)
        self.assertEqual(data["total_attempts"], 1)

        # Filter by status=completed
        res_comp = self.client.get(
            "/api/v1/analytics/examiner/summary?status=completed",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_comp.status_code, 200)
        data_comp = res_comp.json()
        self.assertEqual(data_comp["total_assessments"], 1)
        self.assertEqual(data_comp["total_attempts"], 2)

        # Filter by specific assessment_id
        res_id = self.client.get(
            f"/api/v1/analytics/examiner/summary?assessment_id={self.exam1.id}",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_id.status_code, 200)
        self.assertEqual(res_id.json()["total_assessments"], 1)

    # =========================================================================
    # 3. CANDIDATE PERFORMANCE & PRIVACY (UNRELEASED RESULTS HIDDEN)
    # =========================================================================
    def test_03_candidate_performance_privacy_and_trend(self):
        """
        Student requesting their own performance only sees released results.
        Unreleased result (80%) must be hidden from student view, but counted in pending_count.
        Examiner view can see all results and compute improvement trends.
        """
        # Student 1 view (Self-view)
        res_stud = self.client.get(
            "/api/v1/analytics/candidate/performance",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_stud.status_code, 200)
        stud_data = res_stud.json()
        self.assertEqual(stud_data["candidate_id"], self.student1.id)
        # Should only have 1 visible attempt (Exam 1, 50%) because Exam 2 is unreleased
        self.assertEqual(len(stud_data["attempts_history"]), 1)
        self.assertEqual(stud_data["attempts_history"][0]["score"], 5.0)
        self.assertEqual(stud_data["average_percentage"], 50.0)
        self.assertEqual(stud_data["pending_count"], 1)  # Exam 2 unreleased

        # Examiner 1 view on Student 1 (can see unreleased attempts and trend)
        res_exam = self.client.get(
            f"/api/v1/analytics/candidate/performance?candidate_id={self.student1.id}",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_exam.status_code, 200)
        exam_data = res_exam.json()
        self.assertEqual(len(exam_data["attempts_history"]), 2)
        # Attempt 1: 50%, Attempt 2: 80% -> Improvement trend!
        self.assertEqual(exam_data["improvement_trend"], "improving")
        self.assertEqual(exam_data["best_percentage"], 80.0)

    # =========================================================================
    # 4. CANDIDATE PRIVACY: PREVENT CROSS-STUDENT ACCESS
    # =========================================================================
    def test_04_student_cannot_view_other_candidate(self):
        """A student cannot view another candidate's performance analytics (403 Forbidden)."""
        res = self.client.get(
            f"/api/v1/analytics/candidate/performance?candidate_id={self.student2.id}",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("not authorized", res.json()["detail"].lower())

    # =========================================================================
    # 5. ASSESSMENT DEEP-DIVE ANALYTICS & PARTICIPATION FUNNEL
    # =========================================================================
    def test_05_assessment_deep_dive_analytics(self):
        """Assessment analytics reports participation funnels, score distributions and status."""
        res = self.client.get(
            f"/api/v1/analytics/assessments/{self.exam1.id}",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["assessment_id"], self.exam1.id)
        self.assertEqual(data["total_assigned"], 2)
        self.assertEqual(data["completed_count"], 2)
        self.assertEqual(data["total_attempts"], 2)
        self.assertEqual(data["average_score"], 2.5)  # (5 + 0) / 2 = 2.5
        self.assertEqual(data["highest_score"], 5.0)
        self.assertEqual(data["lowest_score"], 0.0)
        self.assertEqual(data["pass_percentage"], 50.0)  # 1 pass out of 2 = 50%

    # =========================================================================
    # 6. PROCTORING SEPARATION IN ASSESSMENT ANALYTICS
    # =========================================================================
    def test_06_proctoring_separation(self):
        """Proctoring integrity summary is reported separately and never alters academic marks."""
        res = self.client.get(
            f"/api/v1/analytics/assessments/{self.exam1.id}",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("proctoring_summary", data)
        proc = data["proctoring_summary"]
        self.assertIsNotNone(proc)
        self.assertEqual(proc["total_violations"], 1)
        self.assertEqual(proc["risk_distribution"]["high"], 0)
        self.assertEqual(proc["risk_distribution"]["medium"], 1)
        # Academic marks are completely untouched by proctoring
        self.assertEqual(data["highest_score"], 5.0)

    # =========================================================================
    # 7. QUESTION BANK ANALYTICS & ZERO-DIVISION SAFETY
    # =========================================================================
    def test_07_question_analytics_and_zero_division_safety(self):
        """
        Question analytics calculates correct/incorrect percentages.
        - Q1: 0 correct out of 2 attempts -> accuracy 0.0%, frequently_incorrect = True
        - Q2: 1 correct out of 2 attempts -> accuracy 50.0%, frequently_incorrect = False
        - Q3: 0 attempts -> safe against ZeroDivisionError (returns 0.0)
        """
        res = self.client.get(
            f"/api/v1/analytics/assessments/{self.exam1.id}/questions",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        items = res.json()
        self.assertEqual(len(items), 3)

        q1_metric = next(i for i in items if i["question_id"] == self.q1.id)
        self.assertEqual(q1_metric["total_attempts"], 2)
        self.assertEqual(q1_metric["correct_count"], 0)
        self.assertEqual(q1_metric["correct_percentage"], 0.0)

        # Direct Service call to verify frequently_incorrect flag logic
        service_analytics = AnalyticsService.get_question_bank_analytics(
            self.db, self.exam1.id, self.examiner1
        )
        q1_svc = next(i for i in service_analytics if i["question_id"] == self.q1.id)
        self.assertTrue(q1_svc["frequently_incorrect"])

        # Q3 zero-attempt division safety check
        q3_metric = next(i for i in items if i["question_id"] == self.q3.id)
        self.assertEqual(q3_metric["total_attempts"], 0)
        self.assertEqual(q3_metric["correct_percentage"], 0.0)
        self.assertEqual(q3_metric["average_marks_obtained"], 0.0)

    # =========================================================================
    # 8. ORGANIZATION ADMIN DASHBOARD & MULTI-TENANT ISOLATION
    # =========================================================================
    def test_08_organization_dashboard_metrics_and_isolation(self):
        """Org Admin only sees metrics for their organization. Accessing another org is forbidden."""
        # Org 1 Admin accessing Org 1
        res1 = self.client.get(
            "/api/v1/analytics/organization/summary",
            headers={"Authorization": f"Bearer {self.org1_admin_token}"}
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["organization_id"], self.org1.id)
        self.assertEqual(data1["total_assessments"], 2)
        self.assertEqual(data1["total_candidates"], 2)
        self.assertGreaterEqual(len(data1["group_performance"]), 1)

        # Org 2 Admin attempting to access Org 1 data -> 403 Forbidden
        res_cross = self.client.get(
            f"/api/v1/analytics/organization/summary?org_id={self.org1.id}",
            headers={"Authorization": f"Bearer {self.org2_admin_token}"}
        )
        self.assertEqual(res_cross.status_code, 403)

    # =========================================================================
    # 9. SUPER ADMIN CROSS-ORGANIZATION ACCESS
    # =========================================================================
    def test_09_super_admin_cross_organization_access(self):
        """Super Admin can access any organization's metrics and summary."""
        res_super = self.client.get(
            f"/api/v1/analytics/organization/summary?org_id={self.org1.id}",
            headers={"Authorization": f"Bearer {self.super_token}"}
        )
        self.assertEqual(res_super.status_code, 200)
        self.assertEqual(res_super.json()["organization_id"], self.org1.id)

    # =========================================================================
    # 10. DOWNLOADABLE CSV REPORTS (ASSESSMENT, CANDIDATE, QUESTION)
    # =========================================================================
    def test_10_csv_reports_download(self):
        """CSV download endpoints return valid text/csv data matching database records."""
        # 1. Assessment Results CSV
        res_results = self.client.get(
            f"/api/v1/analytics/reports/assessments/{self.exam1.id}/results.csv",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_results.status_code, 200)
        self.assertIn("text/csv", res_results.headers["content-type"])
        reader = csv.reader(io.StringIO(res_results.text))
        rows = list(reader)
        self.assertGreaterEqual(len(rows), 3)  # Header + 2 candidate rows
        self.assertIn("Marks Obtained", rows[0])

        # 2. Candidate Performance CSV (Examiner downloading candidate history)
        res_cand = self.client.get(
            f"/api/v1/analytics/reports/candidates/{self.student1.id}/performance.csv",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_cand.status_code, 200)
        self.assertIn("text/csv", res_cand.headers["content-type"])
        cand_rows = list(csv.reader(io.StringIO(res_cand.text)))
        self.assertGreaterEqual(len(cand_rows), 2)  # Header + rows

        # 3. Question Analytics CSV
        res_q = self.client.get(
            f"/api/v1/analytics/reports/assessments/{self.exam1.id}/questions.csv",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_q.status_code, 200)
        self.assertIn("text/csv", res_q.headers["content-type"])
        q_rows = list(csv.reader(io.StringIO(res_q.text)))
        self.assertEqual(len(q_rows), 4)  # Header + 3 questions

    # =========================================================================
    # 11. CANDIDATE PRIVACY IN CSV DOWNLOAD
    # =========================================================================
    def test_11_candidate_privacy_in_csv_download(self):
        """Student downloading CSV report only receives released results and cannot download for others."""
        # Student 1 downloading their own CSV: only Exam 1 should appear (Exam 2 is unreleased)
        res_stud = self.client.get(
            f"/api/v1/analytics/reports/candidates/{self.student1.id}/performance.csv",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_stud.status_code, 200)
        rows = list(csv.reader(io.StringIO(res_stud.text)))
        self.assertEqual(len(rows), 2)  # Header + 1 released attempt
        self.assertIn("Data Structures Midterm", rows[1][1])

        # Student 1 trying to download Student 2's CSV -> 403 Forbidden
        res_forbidden = self.client.get(
            f"/api/v1/analytics/reports/candidates/{self.student2.id}/performance.csv",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_forbidden.status_code, 403)


if __name__ == "__main__":
    unittest.main()
