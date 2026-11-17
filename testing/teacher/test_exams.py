"""

Teacher Tests: Exam Management

"""

import sys

import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))



from testing.test_db import app, init_test_db, TestingSessionLocal, login_client

from fastapi.testclient import TestClient

import models

import auth



client = TestClient(app)



def setup_teacher_and_login():

    """Sets up DB and logs in a test teacher, returning the client and a group_id"""

    init_test_db()

    db = TestingSessionLocal()



    # Create test teacher

    teacher = models.User(

        email="teacher2@example.com",

        password_hash=auth.get_password_hash("pass"),

        name="Test Teacher 2",

        role="teacher"

    )

    db.add(teacher)

    db.commit()



    # Create a test group

    group = models.Group(name="Test Group", teacher_id=teacher.id)

    db.add(group)

    db.commit()

    db.refresh(group)

    group_id = group.id

    db.close()



    # Perform login

    login_client(client, "teacher2@example.com", "pass")

    return group_id



def test_teacher_create_exam():

    try:

        group_id = setup_teacher_and_login()

        payload = {

            "title": "Midterm Exam",

            "group_id": group_id,

            "start_time": "2026-05-01T10:00",

            "end_time": "2026-05-01T12:00",

            "duration_minutes": 60,

            "timer_type": "overall",

            "passing_marks": 1.0,

            "questions": [

                {"text": "What is 2+2?", "marks": 1, "negative_marks": 0, "time_limit_seconds": 60, "options": [

                    {"text": "4", "is_correct": True},

                    {"text": "3", "is_correct": False}

                ]}

            ]

        }



        response = client.post("/teacher/api/create_exam", json=payload)

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"



        db = TestingSessionLocal()

        exam = db.query(models.Exam).filter(models.Exam.title == "Midterm Exam").first()

        assert exam is not None, "Exam not found in database"

        db.close()

        return True, "✓ Teacher can create exam via API"

    except Exception as e:

        return False, f"✗ Create exam failed: {str(e)}"



def test_teacher_view_exam_settings():

    try:

        group_id = setup_teacher_and_login()

        # Mock exam in db

        db = TestingSessionLocal()

        exam = models.Exam(title="Settings Exam", group_id=group_id, duration_minutes=30)

        db.add(exam)

        db.commit()

        db.refresh(exam)

        exam_id = exam.id

        db.close()



        response = client.get(f"/teacher/exam/{exam_id}/settings")

        assert response.status_code == 200, "Could not load exam settings page"

        return True, "✓ Teacher can view exam settings"

    except Exception as e:

        return False, f"✗ View exam settings failed: {str(e)}"



def get_teacher_exam_tests():

    return [

        ("Create Exam (API)", test_teacher_create_exam),

        ("View Exam Settings", test_teacher_view_exam_settings)

    ]
