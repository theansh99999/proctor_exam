"""

Test Module: Dashboards

Tests teacher and student dashboard data retrieval and statistics

"""



import sys

sys.path.insert(0, '..')



from fastapi.testclient import TestClient

from main import app

import models

from database import engine, SessionLocal

import auth

from datetime import datetime, timezone, timedelta



client = TestClient(app)



def test_teacher_dashboard_groups():

    """Test teacher dashboard loads groups"""

    try:

        models.Base.metadata.drop_all(bind=engine)

        models.Base.metadata.create_all(bind=engine)



        db = SessionLocal()



        teacher = models.User(

            email="teacher@dash.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        # Create 3 groups

        for i in range(3):

            group = models.Group(name=f"Class {i+1}", teacher_id=teacher.id)

            db.add(group)

        db.commit()



        # Retrieve

        groups = db.query(models.Group).filter(models.Group.teacher_id == teacher.id).all()

        assert len(groups) == 3, f"Expected 3 groups, got {len(groups)}"



        db.close()

        return True, "✓ Teacher dashboard groups loading"

    except Exception as e:

        return False, f"✗ Teacher dashboard groups failed: {str(e)}"



def test_teacher_dashboard_exams():

    """Test teacher dashboard loads exams"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher2@dash.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        now = datetime.now(timezone.utc)



        # Create exams with different states

        for i in range(2):

            exam = models.Exam(

                title=f"Exam {i+1}",

                group_id=group.id,

                start_time=now + timedelta(hours=i),

                end_time=now + timedelta(hours=i+1),

                duration_minutes=60

            )

            db.add(exam)

        db.commit()



        # Retrieve exams

        group_ids = [group.id]

        exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all()

        assert len(exams) == 2, f"Expected 2 exams, got {len(exams)}"



        db.close()

        return True, "✓ Teacher dashboard exams loading"

    except Exception as e:

        return False, f"✗ Teacher dashboard exams failed: {str(e)}"



def test_teacher_dashboard_statistics():

    """Test teacher dashboard statistics calculation"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher3@dash.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        now = datetime.now(timezone.utc)



        # Create exam

        exam = models.Exam(

            title="Stats Test",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60,

            default_marks=1.0

        )

        db.add(exam)

        db.commit()



        # Create questions

        for i in range(5):

            q = models.Question(exam_id=exam.id, text=f"Q{i+1}", marks=1.0)

            db.add(q)

        db.commit()



        # Create students and submissions

        students = []

        for i in range(3):

            student = models.User(

                email=f"student{i}@dash.com",

                password_hash=auth.get_password_hash("pass123"),

                name=f"Student {i}",

                role="student"

            )

            db.add(student)

            students.append(student)

        db.commit()



        # Add students to group

        for student in students:

            member = models.GroupMember(group_id=group.id, student_email=student.email)

            db.add(member)

        db.commit()



        # Create submissions with varying scores

        scores = [3.0, 4.0, 5.0]  # out of 5

        for student, score in zip(students, scores):

            submission = models.Submission(

                exam_id=exam.id,

                student_id=student.id,

                score=score

            )

            db.add(submission)

        db.commit()



        # Calculate stats

        questions = db.query(models.Question).filter(models.Question.exam_id == exam.id).all()

        max_marks = sum(q.marks if q.marks else 1.0 for q in questions)



        submissions = db.query(models.Submission).filter(models.Submission.exam_id == exam.id).all()



        avg_percentage = sum(s.score / max_marks * 100 for s in submissions) / len(submissions)

        assert 60 < avg_percentage < 90, f"Average should be 70-80%, got {avg_percentage}"



        db.close()

        return True, "✓ Teacher dashboard statistics"

    except Exception as e:

        return False, f"✗ Teacher dashboard statistics failed: {str(e)}"



def test_student_dashboard_assigned_exams():

    """Test student dashboard shows assigned exams"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student@dash.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher4@dash.com",

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



        # Create exams

        for i in range(2):

            exam = models.Exam(

                title=f"Exam {i+1}",

                group_id=group.id,

                start_time=now + timedelta(hours=i),

                end_time=now + timedelta(hours=i+1),

                duration_minutes=60

            )

            db.add(exam)

        db.commit()



        # Retrieve exams for student

        group_memberships = db.query(models.GroupMember).filter(

            models.GroupMember.student_email == student.email

        ).all()

        group_ids = [gm.group_id for gm in group_memberships]



        exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all()

        assert len(exams) == 2, f"Expected 2 exams, got {len(exams)}"



        db.close()

        return True, "✓ Student dashboard assigned exams"

    except Exception as e:

        return False, f"✗ Student dashboard exams failed: {str(e)}"



def test_student_dashboard_categorize_exams():

    """Test student dashboard categorizes exams (past, active, upcoming)"""

    try:

        db = SessionLocal()



        student = models.User(

            email="student2@dash.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        teacher = models.User(

            email="teacher5@dash.com",

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



        # Past exam

        past_exam = models.Exam(

            title="Past Exam",

            group_id=group.id,

            start_time=now - timedelta(hours=2),

            end_time=now - timedelta(hours=1),

            duration_minutes=60

        )

        db.add(past_exam)



        # Active exam

        active_exam = models.Exam(

            title="Active Exam",

            group_id=group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60

        )

        db.add(active_exam)



        # Upcoming exam

        upcoming_exam = models.Exam(

            title="Upcoming Exam",

            group_id=group.id,

            start_time=now + timedelta(hours=2),

            end_time=now + timedelta(hours=3),

            duration_minutes=60

        )

        db.add(upcoming_exam)

        db.commit()



        # Categorize

        exams = [past_exam, active_exam, upcoming_exam]



        past = [e for e in exams if e.end_time <= now]

        active = [e for e in exams if e.start_time <= now <= e.end_time]

        upcoming = [e for e in exams if e.start_time > now]



        assert len(past) == 1, f"Should have 1 past exam"

        assert len(active) == 1, f"Should have 1 active exam"

        assert len(upcoming) == 1, f"Should have 1 upcoming exam"



        db.close()

        return True, "✓ Student dashboard exam categorization"

    except Exception as e:

        return False, f"✗ Student dashboard categorization failed: {str(e)}"



def run_all_dashboard_tests():

    """Run all dashboard tests"""

    print("\n" + "="*60)

    print("📊 DASHBOARD TESTS")

    print("="*60)



    tests = [

        ("Teacher - Groups Loading", test_teacher_dashboard_groups),

        ("Teacher - Exams Loading", test_teacher_dashboard_exams),

        ("Teacher - Statistics", test_teacher_dashboard_statistics),

        ("Student - Assigned Exams", test_student_dashboard_assigned_exams),

        ("Student - Exam Categorization", test_student_dashboard_categorize_exams),

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

    run_all_dashboard_tests()
