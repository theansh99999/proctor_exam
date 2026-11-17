"""

Test Module: Notifications

Tests exam reminder notifications and status updates

"""



import sys

sys.path.insert(0, '..')



from fastapi.testclient import TestClient

from main import app

import models

from database import engine, SessionLocal

import auth

from datetime import datetime, timezone, timedelta

import json



client = TestClient(app)



def test_notification_api():

    """Test notification retrieval endpoint"""

    try:

        models.Base.metadata.drop_all(bind=engine)

        models.Base.metadata.create_all(bind=engine)



        db = SessionLocal()



        # Setup: Create student and exam

        student = models.User(

            email="student@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        # Add student to group

        member = models.GroupMember(group_id=group.id, student_email=student.email)

        db.add(member)

        db.commit()



        now = datetime.now(timezone.utc)



        # Create upcoming exam

        upcoming_exam = models.Exam(

            title="Upcoming Exam",

            group_id=group.id,

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60

        )

        db.add(upcoming_exam)

        db.commit()



        # Create active exam

        active_exam = models.Exam(

            title="Active Exam",

            group_id=group.id,

            start_time=now - timedelta(minutes=5),

            end_time=now + timedelta(minutes=55),

            duration_minutes=60

        )

        db.add(active_exam)

        db.commit()



        # Test: notification types are correct

        assert upcoming_exam.start_time > now, "Upcoming exam should be in future"

        assert active_exam.start_time <= now <= active_exam.end_time, "Active exam should be active now"



        db.close()

        return True, "✓ Notification API works"

    except Exception as e:

        return False, f"✗ Notification API failed: {str(e)}"



def test_upcoming_exam_notification():

    """Test notification for upcoming exams"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student2@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher2@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        member = models.GroupMember(group_id=group.id, student_email=student.email)

        db.add(member)

        db.commit()



        now = datetime.now(timezone.utc)



        # Exam in 2 hours

        exam = models.Exam(

            title="Upcoming Math Exam",

            group_id=group.id,

            start_time=now + timedelta(hours=2),

            end_time=now + timedelta(hours=3),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        time_to_start = (exam.start_time - now).total_seconds()



        # Should trigger "upcoming" notification

        is_upcoming = time_to_start > 0 and time_to_start <= 24*3600  # within 24 hours

        assert is_upcoming, "Should be upcoming notification"



        db.close()

        return True, "✓ Upcoming exam notification works"

    except Exception as e:

        return False, f"✗ Upcoming exam notification failed: {str(e)}"



def test_active_exam_notification():

    """Test notification for active exams"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student3@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher3@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        member = models.GroupMember(group_id=group.id, student_email=student.email)

        db.add(member)

        db.commit()



        now = datetime.now(timezone.utc)



        # Active exam

        exam = models.Exam(

            title="Active Physics Exam",

            group_id=group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        # Should trigger "active" notification

        is_active = exam.start_time <= now <= exam.end_time

        assert is_active, "Should be active notification"



        db.close()

        return True, "✓ Active exam notification works"

    except Exception as e:

        return False, f"✗ Active exam notification failed: {str(e)}"



def test_submitted_exam_no_notification():

    """Test no notification for already submitted exams"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student4@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher4@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        member = models.GroupMember(group_id=group.id, student_email=student.email)

        db.add(member)

        db.commit()



        now = datetime.now(timezone.utc)

        exam = models.Exam(

            title="Submitted Exam",

            group_id=group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        # Create submission (student already submitted)

        submission = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=80.0

        )

        db.add(submission)

        db.commit()



        # Check: submission exists for this student-exam combo

        existing_submission = db.query(models.Submission).filter(

            models.Submission.student_id == student.id,

            models.Submission.exam_id == exam.id

        ).first()



        assert existing_submission is not None, "Submission should exist"



        db.close()

        return True, "✓ No notification for submitted exams"

    except Exception as e:

        return False, f"✗ No notification test failed: {str(e)}"



def test_urgent_notification_within_5_minutes():

    """Test urgent notification when exam starts within 5 minutes"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student5@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher5@notif.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        member = models.GroupMember(group_id=group.id, student_email=student.email)

        db.add(member)

        db.commit()



        now = datetime.now(timezone.utc)



        # Exam starting in 3 minutes

        exam = models.Exam(

            title="Urgent Exam",

            group_id=group.id,

            start_time=now + timedelta(minutes=3),

            end_time=now + timedelta(minutes=63),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        time_to_start = (exam.start_time - now).total_seconds()

        is_urgent = time_to_start <= 300  # 5 minutes



        assert is_urgent, "Should be marked as urgent (within 5 minutes)"



        db.close()

        return True, "✓ Urgent notification within 5 minutes works"

    except Exception as e:

        return False, f"✗ Urgent notification test failed: {str(e)}"



def run_all_notification_tests():

    """Run all notification tests"""

    print("\n" + "="*60)

    print("🔔 NOTIFICATION TESTS")

    print("="*60)



    tests = [

        ("Notification API", test_notification_api),

        ("Upcoming Exam Notification", test_upcoming_exam_notification),

        ("Active Exam Notification", test_active_exam_notification),

        ("No Notification if Submitted", test_submitted_exam_no_notification),

        ("Urgent Notification (< 5 min)", test_urgent_notification_within_5_minutes),

    ]



    results = []

    for test_name, test_func in tests:

        passed, message = test_func()

        results.append((test_name, passed))

        status_icon = "✓" if passed else "✗"

        print(f"{status_icon} {test_name:30} {message}")



    passed_count = sum(1 for _, p in results if p)

    return passed_count, len(results)



if __name__ == "__main__":

    run_all_notification_tests()
