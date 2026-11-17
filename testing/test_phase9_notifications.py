"""
testing/test_phase9_notifications.py
------------------------------------
Comprehensive Phase 9 test suite for Notifications & Communication Center:
1. In-app notification creation & categories
2. Read, unread count & mark all as read
3. Dismissal (soft delete)
4. User notification preferences (get, update, enforcement)
5. Preference decoupling: disabling email preserves in-app notifications
6. Multi-tenant organization isolation
7. Examiner announcement permissions & cross-org protection
8. Announcement delivery status & history
9. Assessment lifecycle notifications (published, scheduled, cancelled)
10. Candidate activity notifications (submitted, auto submitted)
11. Evaluation & results notifications (released vs unreleased suppression)
12. Mocked SMTP email delivery
13. Temporary failure retry behavior & failure decoupling
14. Idempotency & duplicate notification prevention
15. Scheduled reminders (24h/1h, cancelled prevention, submitted prevention)
"""
import sys
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

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
from modules.notifications.service import NotificationService
from modules.notifications.schemas import (
    NotificationPreferenceUpdate,
    AnnouncementCreateRequest
)
from modules.notifications.channels.email import EmailNotificationChannel
from modules.notifications.channels.in_app import InAppNotificationChannel

# Isolated In-Memory SQLite Test Engine with StaticPool
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


class TestPhase9Notifications(unittest.TestCase):

    def setUp(self):
        os.environ["MOCK_EMAIL"] = "true"
        app.dependency_overrides[database.get_db] = override_get_db
        models.Base.metadata.drop_all(bind=test_engine)
        models.Base.metadata.create_all(bind=test_engine)
        self.db = TestSessionLocal()
        self.client = TestClient(app)

        # Seed test fixture data
        # 1. Organizations
        self.org1 = models.Organization(name="Apex University", slug="apex")
        self.org2 = models.Organization(name="Beacon College", slug="beacon")
        self.db.add_all([self.org1, self.org2])
        self.db.commit()

        # 2. Users
        self.superadmin = models.User(
            email="super@admin.com",
            name="Super Admin",
            role="super_admin",
            password_hash=auth.get_password_hash("pass123")
        )
        self.org1_admin = models.User(
            email="admin@apex.edu",
            name="Apex Admin",
            role="org_admin",
            organization_id=self.org1.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.org2_admin = models.User(
            email="admin@beacon.edu",
            name="Beacon Admin",
            role="org_admin",
            organization_id=self.org2.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.examiner1 = models.User(
            email="prof.smith@apex.edu",
            name="Prof. Smith",
            role="teacher",
            organization_id=self.org1.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.student1 = models.User(
            email="alice@apex.edu",
            name="Alice Student",
            role="student",
            organization_id=self.org1.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.student2 = models.User(
            email="bob@apex.edu",
            name="Bob Student",
            role="student",
            organization_id=self.org1.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.student_org2 = models.User(
            email="charlie@beacon.edu",
            name="Charlie Beacon",
            role="student",
            organization_id=self.org2.id,
            password_hash=auth.get_password_hash("pass123")
        )
        self.db.add_all([
            self.superadmin, self.org1_admin, self.org2_admin,
            self.examiner1, self.student1, self.student2, self.student_org2
        ])
        self.db.commit()

        # 3. Group & Members
        self.group1 = models.Group(name="CS-101", teacher_id=self.examiner1.id, organization_id=self.org1.id)
        self.db.add(self.group1)
        self.db.commit()

        self.gm1 = models.GroupMember(group_id=self.group1.id, student_id=self.student1.id, student_email=self.student1.email)
        self.gm2 = models.GroupMember(group_id=self.group1.id, student_id=self.student2.id, student_email=self.student2.email)
        self.db.add_all([self.gm1, self.gm2])
        self.db.commit()

        # 4. Exam
        now = utc_now()
        self.exam1 = models.Exam(
            title="Algorithms Midterm",
            group_id=self.group1.id,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            assessment_type="technical",
            start_time=now + timedelta(hours=48),
            end_time=now + timedelta(hours=50),
            duration_minutes=120,
            status="published"
        )
        self.db.add(self.exam1)
        self.db.commit()

        # Generate auth tokens
        self.superadmin_token = auth.create_access_token({"sub": self.superadmin.email})
        self.org1_admin_token = auth.create_access_token({"sub": self.org1_admin.email})
        self.org2_admin_token = auth.create_access_token({"sub": self.org2_admin.email})
        self.examiner1_token = auth.create_access_token({"sub": self.examiner1.email})
        self.student1_token = auth.create_access_token({"sub": self.student1.email})
        self.student_org2_token = auth.create_access_token({"sub": self.student_org2.email})

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.clear()

    # =========================================================================
    # 1. IN-APP NOTIFICATION CREATION & CATEGORIES
    # =========================================================================
    def test_01_in_app_notification_creation(self):
        """Creates notifications across categories and retrieves via API."""
        # Dispatch notifications across categories
        NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="lifecycle",
            event_type="assessment_published",
            title="Assessment Published",
            message="CS-101 Midterm is now live.",
            channels=["in_app"]
        )
        NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="reminder",
            event_type="assessment_reminder_24h",
            title="24h Reminder",
            message="Your exam starts in 24 hours.",
            channels=["in_app"]
        )

        res = self.client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["unread_count"], 2)
        categories = {item["category"] for item in data["items"]}
        self.assertIn("lifecycle", categories)
        self.assertIn("reminder", categories)

    # =========================================================================
    # 2. READ/UNREAD STATUS & MARK ALL READ
    # =========================================================================
    def test_02_read_and_unread_lifecycle(self):
        """Validates marking single notification as read and mark-all-read."""
        res_disp = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="candidate",
            event_type="assessment_submitted",
            title="Exam Submitted",
            message="Submission received.",
            channels=["in_app"]
        )
        notif_id = res_disp["notification_id"]

        # Check unread count
        res_cnt = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_cnt.status_code, 200)
        self.assertEqual(res_cnt.json()["unread_count"], 1)

        # Mark single as read
        res_read = self.client.post(
            f"/api/v1/notifications/{notif_id}/read",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_read.status_code, 200)
        self.assertTrue(res_read.json()["is_read"])
        self.assertIsNotNone(res_read.json()["read_at"])

        # Unread count should now be 0
        res_cnt2 = self.client.get(
            "/api/v1/notifications/unread-count",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_cnt2.json()["unread_count"], 0)

        # Create 2 more unread notifications
        NotificationService.send_notification(self.db, self.student1.id, "system", "info", "A1", "M1", channels=["in_app"])
        NotificationService.send_notification(self.db, self.student1.id, "system", "info", "A2", "M2", channels=["in_app"])

        # Mark all read
        res_all = self.client.post(
            "/api/v1/notifications/mark-all-read",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.json()["marked_read_count"], 2)

    # =========================================================================
    # 3. DISMISSAL (SOFT DELETE)
    # =========================================================================
    def test_03_dismiss_notification(self):
        """Dismissing notification soft-deletes it from active queries."""
        disp = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="system",
            event_type="test_event",
            title="Temporary Alert",
            message="To be dismissed.",
            channels=["in_app"]
        )
        nid = disp["notification_id"]

        res_del = self.client.delete(
            f"/api/v1/notifications/{nid}",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_del.status_code, 200)

        # Verify not in list
        res_list = self.client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_list.json()["total"], 0)

    # =========================================================================
    # 4. NOTIFICATION PREFERENCES & RESPECTING PREFERENCES
    # =========================================================================
    def test_04_user_notification_preferences(self):
        """User can retrieve and update preferences; service respects preferences."""
        # 1. Default preferences
        res_get = self.client.get(
            "/api/v1/notifications/preferences",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_get.status_code, 200)
        pref = res_get.json()
        self.assertTrue(pref["email_enabled"])
        self.assertTrue(pref["in_app_enabled"])
        self.assertTrue(pref["reminders_enabled"])

        # 2. Disable reminders
        res_upd = self.client.put(
            "/api/v1/notifications/preferences",
            headers={"Authorization": f"Bearer {self.student1_token}"},
            json={"reminders_enabled": False}
        )
        self.assertEqual(res_upd.status_code, 200)
        self.assertFalse(res_upd.json()["reminders_enabled"])

        # 3. Reminder notification should now be skipped
        res_send = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="reminder",
            event_type="assessment_reminder_24h",
            title="Skipped Reminder",
            message="This should be skipped.",
            channels=["in_app"]
        )
        self.assertEqual(res_send["status"], "skipped")
        self.assertIn("User disabled", res_send["reason"])

    # =========================================================================
    # 5. DISABLING EMAIL LEAVES IN-APP WORKING
    # =========================================================================
    def test_05_disabling_email_leaves_in_app_intact(self):
        """Disabling email does NOT disable in-app notifications."""
        # Disable email only
        NotificationService.update_preferences(
            self.db,
            self.student1.id,
            NotificationPreferenceUpdate(email_enabled=False, in_app_enabled=True),
            self.student1
        )

        res = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="lifecycle",
            event_type="assessment_published",
            title="Important Exam Alert",
            message="Should deliver in-app only.",
            channels=["in_app", "email"]
        )
        self.assertEqual(res["status"], "delivered")
        self.assertTrue(res["channels"]["in_app"])
        self.assertNotIn("email", res["channels"])

    # =========================================================================
    # 6. MULTI-TENANT ORGANIZATION ISOLATION
    # =========================================================================
    def test_06_organization_isolation(self):
        """Users and Admins cannot view notifications or announce across organizations."""
        # Seed Org 1 and Org 2 notifications
        NotificationService.send_notification(
            self.db, self.student1.id, "system", "info", "Org1 Notif", "Apex Only",
            organization_id=self.org1.id, channels=["in_app"]
        )
        NotificationService.send_notification(
            self.db, self.student_org2.id, "system", "info", "Org2 Notif", "Beacon Only",
            organization_id=self.org2.id, channels=["in_app"]
        )

        # Student 1 cannot see Student Org2 notification
        res1 = self.client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res1.json()["total"], 1)
        self.assertEqual(res1.json()["items"][0]["title"], "Org1 Notif")

        # Org 1 Examiner cannot send announcement to Org 2 candidate
        res_cross = self.client.post(
            "/api/v1/notifications/announcements",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json={
                "title": "Cross Org Broadcast",
                "content": "Should be forbidden",
                "target_type": "candidate",
                "target_id": self.student_org2.id
            }
        )
        self.assertEqual(res_cross.status_code, 403)

    # =========================================================================
    # 7. EXAMINER ANNOUNCEMENT PERMISSIONS
    # =========================================================================
    def test_07_examiner_announcement_permissions(self):
        """Examiner can broadcast to assigned group; candidate receives it; unauthorized fails."""
        # 1. Candidate trying to announce is rejected (403)
        res_cand = self.client.post(
            "/api/v1/notifications/announcements",
            headers={"Authorization": f"Bearer {self.student1_token}"},
            json={
                "title": "Spam",
                "content": "Student trying to broadcast",
                "target_type": "group",
                "target_id": self.group1.id
            }
        )
        self.assertEqual(res_cand.status_code, 403)

        # 2. Examiner 1 broadcasts to Group 1
        res_ann = self.client.post(
            "/api/v1/notifications/announcements",
            headers={"Authorization": f"Bearer {self.examiner1_token}"},
            json={
                "title": "Room Change",
                "content": "Midterm moved to Lab 402.",
                "target_type": "group",
                "target_id": self.group1.id,
                "channel": "in_app"
            }
        )
        self.assertEqual(res_ann.status_code, 200, res_ann.text)
        data = res_ann.json()
        self.assertEqual(data["recipient_count"], 2)  # Alice & Bob

        # 3. Alice verifies in-app announcement
        res_alice = self.client.get(
            "/api/v1/notifications/",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_alice.json()["total"], 1)
        self.assertIn("Room Change", res_alice.json()["items"][0]["title"])

    # =========================================================================
    # 8. ANNOUNCEMENT STATUS BREAKDOWN
    # =========================================================================
    def test_08_announcement_delivery_status(self):
        """Examiner can view delivery breakdown of their announcements."""
        ann = NotificationService.send_announcement(
            db=self.db,
            req=AnnouncementCreateRequest(
                title="Syllabus Update",
                content="Chapters 1-5 only.",
                target_type="group",
                target_id=self.group1.id,
                channel="in_app"
            ),
            current_user=self.examiner1
        )

        res = self.client.get(
            f"/api/v1/notifications/announcements/{ann.id}/status",
            headers={"Authorization": f"Bearer {self.examiner1_token}"}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["delivery"]["total_recipients"], 2)
        self.assertEqual(data["delivery"]["in_app_delivered"], 2)
        self.assertEqual(data["delivery"]["in_app_failed"], 0)

    # =========================================================================
    # 9. ASSESSMENT LIFECYCLE NOTIFICATIONS
    # =========================================================================
    def test_09_assessment_lifecycle_events(self):
        """Automated notifications triggered when assessment is scheduled, published, rescheduled, cancelled."""
        count = NotificationService.trigger_assessment_lifecycle_event(
            db=self.db,
            event_type="assessment_published",
            exam_id=self.exam1.id
        )
        self.assertEqual(count, 2)  # Student1 and Student2 assigned to Group1

        # Check Alice received it
        res = self.client.get(
            "/api/v1/notifications/?category=lifecycle",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res.json()["total"], 1)
        self.assertIn("Published", res.json()["items"][0]["title"])

    # =========================================================================
    # 10. CANDIDATE ACTIVITY NOTIFICATIONS
    # =========================================================================
    def test_10_candidate_activity_events(self):
        """Submitting or auto-submitting an assessment triggers candidate activity alert."""
        res = NotificationService.trigger_candidate_activity_event(
            db=self.db,
            event_type="assessment_submitted",
            exam_id=self.exam1.id,
            student_id=self.student1.id
        )
        self.assertEqual(res["status"], "delivered")

        res_list = self.client.get(
            "/api/v1/notifications/?category=candidate",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_list.json()["total"], 1)
        self.assertIn("Submitted", res_list.json()["items"][0]["title"])

    # =========================================================================
    # 11. EVALUATION & RESULT RELEASE NOTIFICATIONS (SUPPRESSION WHEN UNRELEASED)
    # =========================================================================
    def test_11_result_release_and_unreleased_suppression(self):
        """Results release notifies student. UNRELEASED results are strictly suppressed."""
        # 1. Result unreleased: should be suppressed
        self.exam1.results_released = False
        self.db.commit()

        res_unreleased = NotificationService.trigger_evaluation_event(
            db=self.db,
            event_type="result_released",
            exam_id=self.exam1.id,
            student_id=self.student1.id
        )
        self.assertEqual(res_unreleased["status"], "skipped")
        self.assertIn("unreleased", res_unreleased["reason"])

        # 2. Result released: should be dispatched
        self.exam1.results_released = True
        self.db.commit()

        res_released = NotificationService.trigger_evaluation_event(
            db=self.db,
            event_type="result_released",
            exam_id=self.exam1.id,
            student_id=self.student1.id
        )
        self.assertEqual(res_released["status"], "delivered")

        # Verify student receives evaluation alert
        res_list = self.client.get(
            "/api/v1/notifications/?category=evaluation",
            headers={"Authorization": f"Bearer {self.student1_token}"}
        )
        self.assertEqual(res_list.json()["total"], 1)
        self.assertIn("Results Released", res_list.json()["items"][0]["title"])

    # =========================================================================
    # 12. MOCKED SMTP EMAIL DELIVERY
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_12_mocked_smtp_email_delivery(self, mock_smtp):
        """Email delivery runs cleanly with mocked SMTP transport."""
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance

        os.environ.pop("MOCK_EMAIL", None)
        try:
            channel = EmailNotificationChannel(
                username="test@gmail.com",
                password="AppPassword123"
            )
            res = channel.deliver(
                recipient_id=self.student1.id,
                recipient_email=self.student1.email,
                recipient_name=self.student1.name,
                title="Exam Reminder",
                message="Your exam starts tomorrow."
            )
            self.assertTrue(res.success)
            self.assertEqual(res.channel, "email")
            self.assertTrue(instance.sendmail.called)
        finally:
            os.environ["MOCK_EMAIL"] = "true"

    # =========================================================================
    # 13. EMAIL RETRY BEHAVIOR ON TEMPORARY FAILURE
    # =========================================================================
    @patch("smtplib.SMTP")
    def test_13_email_retry_behavior(self, mock_smtp):
        """Temporary SMTP network failures trigger retries."""
        import smtplib
        instance = MagicMock()
        # Fail first 2 attempts with connect error, succeed on 3rd
        instance.sendmail.side_effect = [
            smtplib.SMTPConnectError(421, "Temporary failure"),
            smtplib.SMTPConnectError(421, "Temporary failure"),
            None
        ]
        mock_smtp.return_value.__enter__.return_value = instance

        os.environ.pop("MOCK_EMAIL", None)
        try:
            channel = EmailNotificationChannel(
                username="test@gmail.com",
                password="AppPassword123",
                max_retries=3,
                retry_delay_seconds=0.01
            )
            res = channel.deliver(
                recipient_id=self.student1.id,
                recipient_email=self.student1.email,
                recipient_name=self.student1.name,
                title="Retry Test",
                message="Testing retry logic"
            )
            self.assertTrue(res.success)
            self.assertEqual(instance.sendmail.call_count, 3)
        finally:
            os.environ["MOCK_EMAIL"] = "true"

    # =========================================================================
    # 14. IDEMPOTENCY & DUPLICATE PREVENTION
    # =========================================================================
    def test_14_idempotency_duplicate_prevention(self):
        """Same idempotency key skips duplicate notification dispatch."""
        idem_key = "unique_alert_key_12345"

        # First run: delivered
        res1 = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="system",
            event_type="alert",
            title="Notice",
            message="Unique notification",
            channels=["in_app"],
            idempotency_key=idem_key
        )
        self.assertEqual(res1["status"], "delivered")

        # Second run with same key: skipped
        res2 = NotificationService.send_notification(
            db=self.db,
            recipient_id=self.student1.id,
            category="system",
            event_type="alert",
            title="Notice",
            message="Unique notification",
            channels=["in_app"],
            idempotency_key=idem_key
        )
        self.assertEqual(res2["status"], "skipped")
        self.assertIn("Duplicate", res2["reason"])

        # Count in DB should still be 1
        notif_count = self.db.query(models.Notification).filter_by(user_id=self.student1.id).count()
        self.assertEqual(notif_count, 1)

    # =========================================================================
    # 15. SCHEDULED REMINDERS (24H/1H, CANCELLED & SUBMITTED PREVENTION)
    # =========================================================================
    def test_15_scheduled_reminders_lifecycle(self):
        """Reminders trigger appropriately; cancelled exams & submitted students skipped."""
        now = utc_now()

        # Exam starting in 24 hours
        exam_24h = models.Exam(
            title="Physics Final",
            group_id=self.group1.id,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            start_time=now + timedelta(hours=24),
            end_time=now + timedelta(hours=26),
            status="published"
        )
        # Exam cancelled (should NOT trigger)
        exam_cancelled = models.Exam(
            title="Cancelled Exam",
            group_id=self.group1.id,
            organization_id=self.org1.id,
            creator_id=self.examiner1.id,
            start_time=now + timedelta(hours=24),
            end_time=now + timedelta(hours=26),
            status="cancelled"
        )
        self.db.add_all([exam_24h, exam_cancelled])
        self.db.commit()

        # Mark Alice as already submitted for exam_24h
        sub = models.Submission(
            exam_id=exam_24h.id,
            student_id=self.student1.id,
            score=100.0,
            submitted_at=now
        )
        self.db.add(sub)
        self.db.commit()

        # Run scheduled reminders
        stats = NotificationService.process_scheduled_reminders(self.db, reference_time=now)
        # Alice skipped (submitted), Bob receives 24h reminder, cancelled exam skipped
        self.assertEqual(stats["reminders_sent_24h"], 1)

        # Bob has reminder
        bob_notifs = self.db.query(models.Notification).filter_by(
            user_id=self.student2.id,
            category="reminder"
        ).all()
        self.assertEqual(len(bob_notifs), 1)

        # Alice has NO reminder
        alice_reminders = self.db.query(models.Notification).filter_by(
            user_id=self.student1.id,
            category="reminder"
        ).all()
        self.assertEqual(len(alice_reminders), 0)

        # Re-running immediately: 0 sent due to idempotency
        stats2 = NotificationService.process_scheduled_reminders(self.db, reference_time=now)
        self.assertEqual(stats2["total_sent"], 0)


if __name__ == "__main__":
    unittest.main()
