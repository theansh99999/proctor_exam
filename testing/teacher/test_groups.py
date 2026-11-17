"""

Teacher Tests: Group Management

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

    """Sets up DB and logs in a test teacher, returning the client"""

    init_test_db()

    db = TestingSessionLocal()



    # Create test teacher

    teacher = models.User(

        email="teacher@example.com",

        password_hash=auth.get_password_hash("pass"),

        name="Test Teacher",

        role="teacher"

    )

    db.add(teacher)

    db.commit()

    db.close()



    # Perform login

    login_client(client, "teacher@example.com", "pass")



def test_teacher_create_group():

    try:

        setup_teacher_and_login()

        response = client.post("/teacher/create_group", data={"name": "Science 101"})

        assert response.status_code in [200, 302], "Failed to create group"



        # Verify in DB

        db = TestingSessionLocal()

        group = db.query(models.Group).filter(models.Group.name == "Science 101").first()

        assert group is not None, "Group is not found in database"

        db.close()

        return True, "✓ Teacher can create group"

    except Exception as e:

        return False, f"✗ Create group failed: {str(e)}"



def test_teacher_add_student():

    try:

        setup_teacher_and_login()

        # Create group first

        client.post("/teacher/create_group", data={"name": "Math 101"})



        db = TestingSessionLocal()

        group = db.query(models.Group).first()

        group_id = group.id

        db.close()



        # Add student

        response = client.post(f"/teacher/group/{group_id}/add_member", data={"student_email": "student@example.com"})

        assert response.status_code in [200, 302], f"Failed to add student, returned {response.status_code}"



        return True, "✓ Teacher can add student to group"

    except Exception as e:

        return False, f"✗ Add student failed: {str(e)}"



def get_teacher_group_tests():

    return [

        ("Create Group", test_teacher_create_group),

        ("Add Student to Group", test_teacher_add_student)

    ]
