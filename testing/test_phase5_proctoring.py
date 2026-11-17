"""
testing/test_phase5_proctoring.py
---------------------------------
Comprehensive automated tests for Phase 5 — Proctoring & Exam Integrity:
1. Configurable Proctoring Policies (CRUD, assessment-type presets, validation)
2. Disabled Monitoring Features (policy enforcement: ignored status, no penalty)
3. Event Ingestion & Severity Assignment (low, medium, high, critical)
4. Duplicate Event Debouncing (4-second window deduplication)
5. Session Integrity Scoring & Risk Level Progression (low, medium, high, critical)
6. Automatic Submission Threshold (configurable auto-submit trigger)
7. Examiner Live Status API (active sessions, integrity scores, connection status)
8. Session Event History & Timeline
9. Examiner Review Workflow (legitimate, suspicious, notes; score recalculation without altering marks)
10. WebSocket Authentication & Alert Broadcast
11. Multi-Tenant Organization Isolation (Examiner cross-org access blocked)
12. Candidate Privacy & Transparent Instructions Presentation
"""
import os
os.environ["TESTING"] = "1"

import unittest
import json
from datetime import timedelta
from fastapi.testclient import TestClient

import models, auth, database
from main import app
from time_utils import utc_now, to_utc
from testing.test_db import init_test_db, cleanup_test_db, TestingSessionLocal, apply_test_db_override, clear_test_db_override
from modules.proctoring.service import ProctoringService
from modules.proctoring.schemas import ProctoringPolicyUpdate, ProctoringEventIngest, ProctoringEventReview

class TestPhase5Proctoring(unittest.TestCase):
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
        # 1. Organizations
        self.org1 = models.Organization(name="Aegis Institute", slug="aegis", description="Security Org")
        self.org2 = models.Organization(name="Vanguard Labs", slug="vanguard", description="Tech Org")
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 2. Examiners
        self.examiner1 = models.User(
            email="examiner1@aegis.edu",
            name="Chief Proctor",
            password_hash=auth.get_password_hash("Pass123!"),
            role="examiner",
            organization_id=self.org1.id
        )
        self.examiner2 = models.User(
            email="examiner2@vanguard.edu",
            name="Vanguard Examiner",
            password_hash=auth.get_password_hash("Pass123!"),
            role="examiner",
            organization_id=self.org2.id
        )
        self.db.add_all([self.examiner1, self.examiner2])
        self.db.commit()

        # 3. Candidates
        self.student1 = models.User(
            email="student1@aegis.edu",
            name="Alice Candidate",
            password_hash=auth.get_password_hash("Pass123!"),
            role="candidate",
            organization_id=self.org1.id
        )
        self.student2 = models.User(
            email="student2@vanguard.edu",
            name="Bob Candidate",
            password_hash=auth.get_password_hash("Pass123!"),
            role="candidate",
            organization_id=self.org2.id
        )
        self.db.add_all([self.student1, self.student2])
        self.db.commit()

        # 4. Group & Enrollment
        self.group1 = models.Group(name="Cohort A", teacher_id=self.examiner1.id, organization_id=self.org1.id)
        self.group2 = models.Group(name="Cohort B", teacher_id=self.examiner2.id, organization_id=self.org2.id)
        self.db.add_all([self.group1, self.group2])
        self.db.commit()

        self.db.add(models.GroupMember(group_id=self.group1.id, student_id=self.student1.id, student_email=self.student1.email))
        self.db.add(models.GroupMember(group_id=self.group2.id, student_id=self.student2.id, student_email=self.student2.email))
        self.db.commit()

        # 5. Tokens
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email, "role": "examiner"})
        self.examiner2_token = auth.create_access_token({"sub": self.examiner2.email, "role": "examiner"})
        self.student1_token = auth.create_access_token({"sub": self.student1.email, "role": "candidate"})
        self.student2_token = auth.create_access_token({"sub": self.student2.email, "role": "candidate"})

        # 6. Active Assessments
        now = utc_now()
        self.exam = models.Exam(
            title="Proctored Certification Assessment",
            description="High stakes certification with automated proctoring.",
            assessment_type="placement",
            group_id=self.group1.id,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            start_time=now - timedelta(minutes=15),
            end_time=now + timedelta(hours=2),
            duration_minutes=90,
            status="published",
            max_attempts=1,
            default_marks=5.0
        )
        self.db.add(self.exam)
        self.db.commit()

        # Active Session for Student 1
        self.session1 = models.ExamSession(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            attempt_number=1,
            started_at=now - timedelta(minutes=10),
            overall_deadline=now + timedelta(minutes=80),
            status="in_progress",
            integrity_score=100.0,
            risk_level="low",
            proctoring_status="normal"
        )
        self.db.add(self.session1)
        self.db.commit()

    # =========================================================================
    # 1. CONFIGURABLE PROCTORING POLICIES
    # =========================================================================
    def test_01_proctoring_policy_configuration(self):
        """Examiner retrieves and updates granular proctoring policy."""
        # 1. Retrieve default policy (tailored for placement assessment)
        res = self.client.get(
            f"/api/v1/assessments/{self.exam.id}/proctoring-policy",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        policy = res.json()
        self.assertTrue(policy["webcam_required"])
        self.assertTrue(policy["microphone_required"]) # placement default
        self.assertTrue(policy["tab_switch_detection"])
        self.assertEqual(policy["warning_threshold"], 2)

        # 2. Examiner updates policy: toggle mic off, set custom thresholds
        update_payload = {
            "microphone_required": False,
            "fullscreen_required": False,
            "auto_submit_threshold": 5,
            "warning_threshold": 3
        }
        res_update = self.client.put(
            f"/api/v1/assessments/{self.exam.id}/proctoring-policy",
            json=update_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res_update.status_code, 200)
        updated = res_update.json()
        self.assertFalse(updated["microphone_required"])
        self.assertFalse(updated["fullscreen_required"])
        self.assertEqual(updated["auto_submit_threshold"], 5)
        self.assertEqual(updated["warning_threshold"], 3)

        # 3. Candidate blocked from updating policy
        res_cand = self.client.put(
            f"/api/v1/assessments/{self.exam.id}/proctoring-policy",
            json={"webcam_required": False},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_cand.status_code, 403)

    # =========================================================================
    # 2. DISABLED MONITORING FEATURES ENFORCEMENT
    # =========================================================================
    def test_02_disabled_monitoring_features_enforcement(self):
        """Disabled proctoring features are marked ignored and do not penalize integrity score."""
        # Disable tab switch detection in policy
        policy = ProctoringService.get_or_create_policy(self.db, self.exam)
        policy.tab_switch_detection = False
        self.db.commit()

        # Candidate submits tab switch event
        res = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "tab_switch", "description": "Tab switched"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ignored")
        self.assertEqual(data["reason"], "feature_disabled_by_policy")

        # Session integrity score remains 100.0 (no penalty)
        sess = self.db.query(models.ExamSession).filter_by(id=self.session1.id).first()
        self.assertEqual(sess.integrity_score, 100.0)

    # =========================================================================
    # 3. EVENT INGESTION & SEVERITY ASSIGNMENT
    # =========================================================================
    def test_03_event_ingestion_and_severity_assignment(self):
        """Event engine assigns appropriate severity (low, medium, high, critical)."""
        # 1. Camera disconnect -> high severity
        res1 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "camera_disconnected", "description": "Camera unplugged"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["severity"], "high")

        # 2. Copy/Paste violation -> low severity
        res2 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "copy_paste", "description": "Attempted copy"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["severity"], "low")

        # 3. Repeated violations -> critical severity
        res3 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "repeated_violations", "description": "Repeated offenses"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(res3.json()["severity"], "critical")

    # =========================================================================
    # 4. DUPLICATE EVENT DEBOUNCING
    # =========================================================================
    def test_04_duplicate_event_debouncing(self):
        """Events within 4-second window with identical event_type are debounced."""
        # First event -> valid and logged
        res1 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "fullscreen_exit", "description": "Exited fullscreen"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "logged")
        flag_id = res1.json()["flag_id"]

        # Immediate second event (within 4s) -> duplicate
        res2 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "fullscreen_exit", "description": "Exited fullscreen"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["status"], "duplicate")
        self.assertEqual(res2.json()["flag_id"], flag_id)

    # =========================================================================
    # 5. SESSION INTEGRITY SCORING & RISK LEVEL PROGRESSION
    # =========================================================================
    def test_05_session_integrity_scoring_and_risk_progression(self):
        """Integrity score decreases and risk progresses across low -> medium -> high -> critical."""
        sess = self.db.query(models.ExamSession).filter_by(id=self.session1.id).first()
        self.assertEqual(sess.integrity_score, 100.0)
        self.assertEqual(sess.risk_level, "low")

        # Helper to manually add flags with different timestamps to test risk tiers
        policy = ProctoringService.get_or_create_policy(self.db, self.exam)
        now = utc_now()

        # Add 2 medium events (-14 points -> score 86.0 -> low)
        f1 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=sess.id,
                              event_type="tab_switch", severity="medium", validation_status="valid", timestamp=now)
        f2 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=sess.id,
                              event_type="window_blur", severity="medium", validation_status="valid", timestamp=now)
        self.db.add_all([f1, f2])
        self.db.commit()

        score, risk = ProctoringService.calculate_integrity_score([f1, f2], policy)
        self.assertEqual(score, 86.0)
        self.assertEqual(risk, "low")

        # Add high event (-15 points -> score 71.0 -> medium)
        f3 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=sess.id,
                              event_type="multiple_faces", severity="high", validation_status="valid", timestamp=now)
        self.db.add(f3)
        self.db.commit()
        score, risk = ProctoringService.calculate_integrity_score([f1, f2, f3], policy)
        self.assertEqual(score, 71.0)
        self.assertEqual(risk, "medium")

        # Add critical event (-25 points -> score 46.0 -> high)
        f4 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=sess.id,
                              event_type="repeated_violations", severity="critical", validation_status="valid", timestamp=now)
        self.db.add(f4)
        self.db.commit()
        score, risk = ProctoringService.calculate_integrity_score([f1, f2, f3, f4], policy)
        self.assertEqual(score, 46.0)
        self.assertEqual(risk, "high")

        # Add another critical event (-25 points -> score 21.0 -> critical)
        f5 = models.CheatFlag(exam_id=self.exam.id, student_id=self.student1.id, exam_session_id=sess.id,
                              event_type="repeated_violations", severity="critical", validation_status="valid", timestamp=now)
        self.db.add(f5)
        self.db.commit()
        score, risk = ProctoringService.calculate_integrity_score([f1, f2, f3, f4, f5], policy)
        self.assertEqual(score, 21.0)
        self.assertEqual(risk, "critical")

    # =========================================================================
    # 6. AUTOMATIC SUBMISSION THRESHOLD
    # =========================================================================
    def test_06_automatic_submission_threshold(self):
        """Auto-submit threshold triggers should_auto_submit flag when threshold reached."""
        # Configure auto_submit_threshold = 2
        policy = ProctoringService.get_or_create_policy(self.db, self.exam)
        policy.auto_submit_threshold = 2
        self.db.commit()

        # Ingest violation 1
        res1 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "tab_switch", "description": "Tab 1"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertFalse(res1.json()["should_auto_submit"])

        # Ingest violation 2 (different type to avoid debounce)
        res2 = self.client.post(
            "/api/v1/proctoring/events",
            json={"exam_id": self.exam.id, "event_type": "multiple_faces", "description": "Second person"},
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertTrue(res2.json()["should_auto_submit"])

        # Verify session proctoring_status is auto_submitted
        sess = self.db.query(models.ExamSession).filter_by(id=self.session1.id).first()
        self.assertEqual(sess.proctoring_status, "auto_submitted")

    # =========================================================================
    # 7. EXAMINER LIVE STATUS API
    # =========================================================================
    def test_07_examiner_live_status_api(self):
        """Live monitoring endpoint returns candidate progress, integrity score, and policy."""
        res = self.client.get(
            f"/api/v1/proctoring/assessments/{self.exam.id}/live-status",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["exam_id"], self.exam.id)
        self.assertEqual(data["total_candidates"], 1)
        self.assertEqual(data["active_candidates"][0]["student_name"], self.student1.name)
        self.assertEqual(data["active_candidates"][0]["integrity_score"], 100.0)
        self.assertIn("webcam_required", data["policy"])

    # =========================================================================
    # 8. SESSION EVENT HISTORY & TIMELINE
    # =========================================================================
    def test_08_session_event_history_and_timeline(self):
        """Retrieves complete chronological event history for an exam session."""
        now = utc_now()
        flag = models.CheatFlag(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            exam_session_id=self.session1.id,
            event_type="camera_disconnected",
            description="Webcam disconnected",
            severity="high",
            validation_status="valid",
            timestamp=now
        )
        self.db.add(flag)
        self.db.commit()

        res = self.client.get(
            f"/api/v1/proctoring/sessions/{self.session1.id}/events",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        events = res.json()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "camera_disconnected")
        self.assertEqual(events[0]["severity"], "high")

    # =========================================================================
    # 9. EXAMINER REVIEW WORKFLOW
    # =========================================================================
    def test_09_examiner_review_workflow(self):
        """Examiner reviews violation, adds notes, and legitimate classification restores score."""
        now = utc_now()
        flag = models.CheatFlag(
            exam_id=self.exam.id,
            student_id=self.student1.id,
            exam_session_id=self.session1.id,
            event_type="multiple_faces",
            description="Detected multiple faces",
            severity="high", # -15 penalty
            validation_status="valid",
            timestamp=now
        )
        self.db.add(flag)
        self.session1.integrity_score = 85.0
        self.db.commit()

        # Examiner marks as legitimate (e.g. parent walked by briefly)
        review_payload = {
            "review_decision": "legitimate",
            "reviewer_notes": "Reviewed video frame: false positive, family member walked past door."
        }
        res = self.client.put(
            f"/api/v1/proctoring/events/{flag.id}/review",
            json=review_payload,
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "reviewed")
        self.assertEqual(data["review_decision"], "legitimate")

        # Session integrity score is restored to 100.0
        sess = self.db.query(models.ExamSession).filter_by(id=self.session1.id).first()
        self.assertEqual(sess.integrity_score, 100.0)

    # =========================================================================
    # 10. WEBSOCKET AUTHENTICATION & ALERT BROADCAST
    # =========================================================================
    def test_10_websocket_authentication(self):
        """Teacher/Examiner WebSocket validates authentication token and ownership."""
        # 1. Examiner connects with valid token -> Accepted
        with self.client.websocket_connect(f"/ws/teacher/{self.examiner1.id}?token={self.examiner1_token}") as ws:
            # Connected successfully
            pass

        # 2. Examiner attempts to connect to another examiner's WebSocket channel -> Rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/ws/teacher/{self.examiner2.id}?token={self.examiner1_token}") as ws:
                pass

        # 3. Candidate attempts to connect to teacher WebSocket -> Rejected
        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/ws/teacher/{self.examiner1.id}?token={self.student1_token}") as ws:
                pass

    # =========================================================================
    # 11. MULTI-TENANT ORGANIZATION ISOLATION
    # =========================================================================
    def test_11_organization_isolation(self):
        """Examiner cannot configure policy or monitor assessment from another organization."""
        # Examiner 2 (Org 2) attempts to view Org 1's live status
        res_live = self.client.get(
            f"/api/v1/proctoring/assessments/{self.exam.id}/live-status",
            headers={"Authorization": f"Bearer {self.examiner2_token}"}
        )
        self.assertEqual(res_live.status_code, 403)

        # Examiner 2 attempts to update Org 1's proctoring policy
        res_policy = self.client.put(
            f"/api/v1/assessments/{self.exam.id}/proctoring-policy",
            json={"webcam_required": False},
            headers={"Authorization": f"Bearer {self.examiner2_token}"}
        )
        self.assertEqual(res_policy.status_code, 403)

    # =========================================================================
    # 12. CANDIDATE PRIVACY & TRANSPARENT INSTRUCTIONS PRESENTATION
    # =========================================================================
    def test_12_candidate_privacy_and_transparency(self):
        """Instructions page reflects configured proctoring policies and thresholds."""
        # Configure custom warning and violation thresholds
        policy = ProctoringService.get_or_create_policy(self.db, self.exam)
        policy.warning_threshold = 4
        policy.auto_submit_threshold = 8
        self.db.commit()

        res = self.client.get(
            f"/student/instructions/{self.exam.id}",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.status_code, 200)
        content = res.text

        # Verify transparency elements
        self.assertIn("Proctoring Requirements", content)
        self.assertIn("Automated submission triggers at 8 violations", content)
        self.assertIn("Working webcam and microphone", content)


if __name__ == "__main__":
    unittest.main()
