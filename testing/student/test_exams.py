"""

Student Tests: Exams

"""

import sys

import os

import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))



from testing.test_db import app, init_test_db, TestingSessionLocal, login_client

from fastapi.testclient import TestClient

import models

import auth



client = TestClient(app)



def setup_student_and_exam():

    """Sets up DB, logs in a student, creates a group/exam and returns exam_id"""

    init_test_db()

    db = TestingSessionLocal()



    # Create test teacher

    teacher = models.User(email="teacher3@example.com", password_hash=auth.get_password_hash("pass"), role="teacher")

    db.add(teacher)



    # Create test student

    student = models.User(email="student3@example.com", password_hash=auth.get_password_hash("pass"), role="student")

    db.add(student)

    db.commit()



    # Create group

    group = models.Group(name="Maths 101", teacher_id=teacher.id)

    db.add(group)

    db.commit()



    # Add student to group

    member = models.GroupMember(group_id=group.id, student_email=student.email)

    db.add(member)



    # Create exam (currently active)

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) # Simplistic sync

    start = now - datetime.timedelta(minutes=10)

    end = now + datetime.timedelta(minutes=50)



    exam = models.Exam(

        title="Final Test",

        group_id=group.id,

        start_time=start,

        end_time=end,

        duration_minutes=60,

        passing_marks=5

    )

    db.add(exam)

    db.commit()



    # Create a question

    q = models.Question(exam_id=exam.id, text="1+1?", marks=10)

    db.add(q)

    db.commit()



    # Create options

    db.add(models.Option(question_id=q.id, text="2", is_correct=True))

    db.add(models.Option(question_id=q.id, text="3", is_correct=False))

    db.commit()



    exam_id = exam.id

    db.close()



    # Login

    login_client(client, "student3@example.com", "pass")

    return exam_id



def test_student_take_exam_page_loads():

    try:

        exam_id = setup_student_and_exam()



        response = client.get(f"/student/take_exam/{exam_id}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"



        return True, "✓ Student take exam page loads correctly"

    except Exception as e:

        return False, f"✗ Student take exam page failed: {str(e)}"



def test_student_submit_exam():

    try:

        exam_id = setup_student_and_exam()



        # We need the question and option IDs

        db = TestingSessionLocal()

        q = db.query(models.Question).filter(models.Question.exam_id == exam_id).first()

        opt = db.query(models.Option).filter(models.Option.question_id == q.id, models.Option.is_correct == True).first()

        db.close()



        # Submit payload

        payload = {

            f"question_{q.id}": str(opt.id)

        }



        response = client.post(f"/student/submit_exam/{exam_id}", data=payload)

        assert response.status_code in [200, 302], f"Failed submission, status {response.status_code}"



        return True, "✓ Student exam submission works"

    except Exception as e:

        return False, f"✗ Student exam submission failed: {str(e)}"



def test_student_practice_list():

    try:

        # Just simple load test

        login_client(client, "student3@example.com", "pass")

        response = client.get("/student/practice_list")

        assert response.status_code == 200, "Practice list failed to load"

        return True, "✓ Student practice list loads"

    except Exception as e:

        return False, f"✗ Student practice list failed: {str(e)}"



def get_student_exam_tests():

    return [

        ("Take Exam Page", test_student_take_exam_page_loads),

        ("Submit Exam", test_student_submit_exam),

        ("Practice List", test_student_practice_list)

    ]
