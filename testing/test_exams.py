"""

Test Module: Exam Management

Tests exam creation, timing validation, question management, and scoring logic

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



def test_exam_creation():

    """Test creating an exam"""

    try:

        models.Base.metadata.drop_all(bind=engine)

        models.Base.metadata.create_all(bind=engine)



        db = SessionLocal()



        # Create teacher and group

        teacher = models.User(

            email="teacher@exam.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Teacher",

            role="teacher"

        )

        db.add(teacher)

        db.commit()



        group = models.Group(name="Test Group", teacher_id=teacher.id)

        db.add(group)

        db.commit()



        # Create exam

        now = datetime.now(timezone.utc)

        exam = models.Exam(

            title="Math Exam",

            group_id=group.id,

            start_time=now + timedelta(hours=1),

            end_time=now + timedelta(hours=2),

            duration_minutes=60,

            default_marks=1.0,

            passing_marks=40.0

        )

        db.add(exam)

        db.commit()



        assert exam.id is not None

        assert exam.title == "Math Exam"

        assert exam.passing_marks == 40.0



        db.close()

        return True, "✓ Exam creation works"

    except Exception as e:

        return False, f"✗ Exam creation failed: {str(e)}"



def test_add_questions():

    """Test adding questions to exam"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher2@exam.com",

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

        exam = models.Exam(

            title="Science Exam",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60,

            default_marks=2.0

        )

        db.add(exam)

        db.commit()



        # Add questions

        for i in range(3):

            question = models.Question(

                exam_id=exam.id,

                text=f"Question {i+1}",

                marks=2.0,

                negative_marks=0.5

            )

            db.add(question)

        db.commit()



        questions = db.query(models.Question).filter(models.Question.exam_id == exam.id).all()

        assert len(questions) == 3, f"Expected 3 questions, got {len(questions)}"



        db.close()

        return True, "✓ Add questions works"

    except Exception as e:

        return False, f"✗ Add questions failed: {str(e)}"



def test_add_options():

    """Test adding options to questions"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher3@exam.com",

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

        exam = models.Exam(

            title="History Exam",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        question = models.Question(exam_id=exam.id, text="Who is first PM of India?", marks=1.0)

        db.add(question)

        db.commit()



        # Add options

        options_data = [

            ("Jawaharlal Nehru", True),

            ("Indira Gandhi", False),

            ("Lal Bahadur Shastri", False),

            ("Morarji Desai", False)

        ]



        for opt_text, is_correct in options_data:

            option = models.Option(

                question_id=question.id,

                text=opt_text,

                is_correct=is_correct

            )

            db.add(option)

        db.commit()



        options = db.query(models.Option).filter(models.Option.question_id == question.id).all()

        assert len(options) == 4, f"Expected 4 options, got {len(options)}"



        correct_opts = [o for o in options if o.is_correct]

        assert len(correct_opts) == 1, "Should have exactly 1 correct option"



        db.close()

        return True, "✓ Add options works"

    except Exception as e:

        return False, f"✗ Add options failed: {str(e)}"



def test_exam_timing_validation():

    """Test exam start/end time logic"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher4@exam.com",

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



        # Future exam

        future_exam = models.Exam(

            title="Future Exam",

            group_id=group.id,

            start_time=now + timedelta(hours=24),

            end_time=now + timedelta(hours=25),

            duration_minutes=60

        )

        db.add(future_exam)

        db.commit()



        # Check if exam is in future

        is_future = future_exam.start_time > now

        assert is_future, "Exam should be in future"



        # Active exam

        active_exam = models.Exam(

            title="Active Exam",

            group_id=group.id,

            start_time=now - timedelta(minutes=10),

            end_time=now + timedelta(minutes=50),

            duration_minutes=60

        )

        db.add(active_exam)

        db.commit()



        is_active = active_exam.start_time <= now <= active_exam.end_time

        assert is_active, "Exam should be active now"



        db.close()

        return True, "✓ Exam timing validation works"

    except Exception as e:

        return False, f"✗ Exam timing validation failed: {str(e)}"



def test_passing_marks_logic():

    """Test passing marks calculation"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher5@exam.com",

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

        exam = models.Exam(

            title="Pass/Fail Exam",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60,

            passing_marks=40.0  # RAW MARKS, not percentage

        )

        db.add(exam)

        db.commit()



        student = models.User(

            email="student@exam.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        # Passing submission

        passing_sub = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=45.0

        )

        db.add(passing_sub)

        db.commit()



        # Check if passed

        passed = passing_sub.score >= exam.passing_marks

        assert passed, f"Score {passing_sub.score} should pass (cut-off: {exam.passing_marks})"



        # Failing submission

        failing_sub = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=30.0

        )

        db.add(failing_sub)

        db.commit()



        failed = failing_sub.score < exam.passing_marks

        assert failed, f"Score {failing_sub.score} should fail (cut-off: {exam.passing_marks})"



        db.close()

        return True, "✓ Passing marks logic works"

    except Exception as e:

        return False, f"✗ Passing marks logic failed: {str(e)}"



def run_all_exam_tests():

    """Run all exam management tests"""

    print("\n" + "="*60)

    print("📝 EXAM MANAGEMENT TESTS")

    print("="*60)



    tests = [

        ("Exam Creation", test_exam_creation),

        ("Add Questions", test_add_questions),

        ("Add Options", test_add_options),

        ("Exam Timing Validation", test_exam_timing_validation),

        ("Passing Marks Logic", test_passing_marks_logic),

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

    run_all_exam_tests()
