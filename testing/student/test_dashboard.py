"""

Student Tests: Dashboard

"""

import sys

import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))



from testing.test_db import app, init_test_db, TestingSessionLocal, login_client

from fastapi.testclient import TestClient

import models

import auth



client = TestClient(app)



def setup_student_and_login():

    """Sets up DB and logs in a test student, returning the client"""

    init_test_db()

    db = TestingSessionLocal()



    # Create test student

    student = models.User(

        email="student@example.com",

        password_hash=auth.get_password_hash("pass"),

        name="Test Student",

        role="student"

    )

    db.add(student)

    db.commit()

    db.close()



    # Perform login

    login_client(client, "student@example.com", "pass")



def test_student_dashboard_loads():

    try:

        setup_student_and_login()



        response = client.get("/student/dashboard")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        assert "Test Student" in response.text, "Student name not found in dashboard HTML"



        return True, "✓ Student dashboard loads correctly"

    except Exception as e:

        return False, f"✗ Student dashboard failed: {str(e)}"



def test_student_notifications():

    try:

        setup_student_and_login()



        response = client.get("/student/notifications")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"



        return True, "✓ Student API notifications fetch works"

    except Exception as e:

        return False, f"✗ API notifications fetch failed: {str(e)}"



def get_student_dashboard_tests():

    return [

        ("Dashboard Load", test_student_dashboard_loads),

        ("Notifications Fetch", test_student_notifications)

    ]
