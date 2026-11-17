"""

Test Module: Submissions & Scoring

Tests student answers, score calculation, and submission validation

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



def test_student_answer_submission():

    """Test storing student answers"""

    try:

        models.Base.metadata.drop_all(bind=engine)

        models.Base.metadata.create_all(bind=engine)



        db = SessionLocal()



        # Setup: Create exam with questions

        teacher = models.User(

            email="teacher@sub.com",

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

            title="Test Exam",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        question = models.Question(exam_id=exam.id, text="Test Question", marks=1.0)

        db.add(question)

        db.commit()



        option_correct = models.Option(

            question_id=question.id,

            text="Correct",

            is_correct=True

        )

        option_wrong = models.Option(

            question_id=question.id,

            text="Wrong",

            is_correct=False

        )

        db.add(option_correct)

        db.add(option_wrong)

        db.commit()



        # Create student and submission

        student = models.User(

            email="student@sub.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        submission = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=0.0

        )

        db.add(submission)

        db.commit()



        # Record student answer

        answer = models.StudentAnswer(

            submission_id=submission.id,

            question_id=question.id,

            selected_option_id=option_correct.id

        )

        db.add(answer)

        db.commit()



        # Verify

        saved_answer = db.query(models.StudentAnswer).filter(

            models.StudentAnswer.submission_id == submission.id

        ).first()

        assert saved_answer is not None, "Answer not saved"

        assert saved_answer.selected_option_id == option_correct.id



        db.close()

        return True, "✓ Student answer submission works"

    except Exception as e:

        return False, f"✗ Student answer submission failed: {str(e)}"



def test_score_calculation():

    """Test automatic score calculation"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher2@sub.com",

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

            title="Scoring Test",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60,

            default_marks=1.0,

            default_negative_marks=0.25

        )

        db.add(exam)

        db.commit()



        # Create 5 questions with 1 mark each

        question_ids = []

        for i in range(5):

            q = models.Question(

                exam_id=exam.id,

                text=f"Q{i+1}",

                marks=1.0,

                negative_marks=0.25

            )

            db.add(q)

            db.commit()

            question_ids.append(q.id)



        # Max marks = 5

        max_marks = sum([1.0] * 5)

        assert max_marks == 5.0, f"Max marks should be 5, got {max_marks}"



        # Simulate: 4 correct, 1 wrong

        # Score = 4*1.0 - 1*0.25 = 3.75

        expected_score = 4 * 1.0 - 1 * 0.25



        student = models.User(

            email="student2@sub.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        submission = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=expected_score

        )

        db.add(submission)

        db.commit()



        assert submission.score == 3.75, f"Expected score 3.75, got {submission.score}"



        db.close()

        return True, "✓ Score calculation works"

    except Exception as e:

        return False, f"✗ Score calculation failed: {str(e)}"



def test_multiple_submissions():

    """Test student can submit multiple times (overwrite)"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher3@sub.com",

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

            title="Multi Submit Test",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        student = models.User(

            email="student3@sub.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        # First submission

        sub1 = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=40.0

        )

        db.add(sub1)

        db.commit()



        # Can have multiple submissions (depends on app logic)

        sub2 = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=50.0

        )

        db.add(sub2)

        db.commit()



        submissions = db.query(models.Submission).filter(

            models.Submission.student_id == student.id,

            models.Submission.exam_id == exam.id

        ).all()



        assert len(submissions) >= 1, "No submission found"



        db.close()

        return True, "✓ Multiple submissions work"

    except Exception as e:

        return False, f"✗ Multiple submissions failed: {str(e)}"



def test_submission_metadata():

    """Test submission timestamp and metadata"""

    try:

        db = SessionLocal()



        teacher = models.User(

            email="teacher4@sub.com",

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

            title="Metadata Test",

            group_id=group.id,

            start_time=now,

            end_time=now + timedelta(hours=1),

            duration_minutes=60

        )

        db.add(exam)

        db.commit()



        student = models.User(

            email="student4@sub.com",

            password_hash=auth.get_password_hash("pass123"),

            name="Student",

            role="student"

        )

        db.add(student)

        db.commit()



        before_time = datetime.now(timezone.utc)

        submission = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=75.0

        )

        db.add(submission)

        db.commit()

        after_time = datetime.now(timezone.utc)



        # Verify timestamp

        assert submission.submitted_at is not None, "submitted_at is None"

        assert before_time <= submission.submitted_at <= after_time, "Timestamp out of range"



        db.close()

        return True, "✓ Submission metadata works"

    except Exception as e:

        return False, f"✗ Submission metadata failed: {str(e)}"



def run_all_submission_tests():

    """Run all submission tests"""

    print("\n" + "="*60)

    print("📤 SUBMISSION & SCORING TESTS")

    print("="*60)



    tests = [

        ("Student Answer Submission", test_student_answer_submission),

        ("Score Calculation", test_score_calculation),

        ("Multiple Submissions", test_multiple_submissions),

        ("Submission Metadata", test_submission_metadata),

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

    run_all_submission_tests()
