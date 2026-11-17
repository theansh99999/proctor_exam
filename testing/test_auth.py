"""

Test Module: Authentication

Tests login, registration, logout, token generation, and password verification

"""



import sys

import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))



from fastapi.testclient import TestClient

from testing.test_db import app, init_test_db, cleanup_test_db, TestingSessionLocal, get_csrf_token

import models

import auth



client = TestClient(app)



def test_auth_register():

    """Test user registration functionality"""

    try:

        init_test_db()

        csrf = get_csrf_token(client, "/register")

        response = client.post("/register", data={

            "email": "testuser@example.com",

            "password": "testpass123",

            "name": "Test User",

            "role": "student",

            "csrf_token": csrf

        })



        # Should redirect on success (302) or return OK (200)

        assert response.status_code in [302, 200], f"Expected redirect, got {response.status_code}"



        # Verify user was created

        db = TestingSessionLocal()

        user = db.query(models.User).filter(models.User.email == "testuser@example.com").first()

        assert user is not None, "User not created in database"

        assert user.name == "Test User"

        assert user.role == "student"

        db.close()



        return True, "✓ Registration works correctly"

    except Exception as e:

        return False, f"✗ Registration failed: {str(e)}"



def test_auth_login():

    """Test user login functionality"""

    try:

        init_test_db()

        db = TestingSessionLocal()



        # Create test user

        test_user = models.User(

            email="login@example.com",

            password_hash=auth.get_password_hash("password123"),

            name="Login Test",

            role="teacher"

        )

        db.add(test_user)

        db.commit()

        db.close()



        # Test login

        csrf = get_csrf_token(client, "/login")

        response = client.post("/login", data={

            "email": "login@example.com",

            "password": "password123",

            "csrf_token": csrf

        })



        assert response.status_code in [302, 200], f"Login failed with status {response.status_code}"

        assert (

            "access_token" in response.cookies

            or "access_token" in client.cookies

            or response.url.path in ["/dashboard", "/teacher/dashboard", "/student/dashboard"]

        ), "No access token cookie set or redirect failed"



        return True, "✓ Login works correctly"

    except Exception as e:

        return False, f"✗ Login failed: {str(e)}"



def test_auth_password_verification():

    """Test password hashing and verification"""

    try:

        password = "mySecurePassword123!"

        hashed = auth.get_password_hash(password)



        # Verify correct password

        assert auth.verify_password(password, hashed), "Password verification failed"



        # Verify wrong password

        assert not auth.verify_password("wrongpassword", hashed), "Wrong password accepted"



        return True, "✓ Password hashing/verification works"

    except Exception as e:

        return False, f"✗ Password verification failed: {str(e)}"



def test_auth_token_creation():

    """Test JWT token generation"""

    try:

        from datetime import timedelta



        token_data = {"sub": "test@example.com", "role": "student"}

        token = auth.create_access_token(data=token_data, expires_delta=timedelta(minutes=60))



        assert token is not None, "Token is None"

        assert isinstance(token, str), "Token is not a string"

        assert len(token) > 0, "Token is empty"



        return True, "✓ Token creation works"

    except Exception as e:

        return False, f"✗ Token creation failed: {str(e)}"



def test_auth_logout():

    """Test logout functionality"""

    try:

        response = client.get("/logout")



        assert response.status_code in [302, 200], f"Logout failed with status {response.status_code}"



        return True, "✓ Logout works correctly"

    except Exception as e:

        return False, f"✗ Logout failed: {str(e)}"



def get_auth_tests():

    """Return all auth tests to be run by the main runner"""

    return [

        ("Register", test_auth_register),

        ("Login", test_auth_login),

        ("Password Verification", test_auth_password_verification),

        ("Token Creation", test_auth_token_creation),

        ("Logout", test_auth_logout),

    ]



if __name__ == "__main__":

    tests = get_auth_tests()

    for name, func in tests:

        print(func()[1])
