"""
Test Database Utilities
Provides an isolated in-memory SQLite database for tests.
Production database is NEVER touched — TESTING env var prevents
main.py from connecting to PostgreSQL during import.
"""
import os
# ── MUST be set before importing main/database ────────────────────────────────
os.environ["TESTING"] = "1"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base
from main import app
from database import get_db

from sqlalchemy.pool import StaticPool

# Create an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_test_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

def apply_test_db_override():
    app.dependency_overrides[get_db] = get_test_db

def clear_test_db_override():
    app.dependency_overrides.clear()

def init_test_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    apply_test_db_override()

def cleanup_test_db():
    Base.metadata.drop_all(bind=engine)
    clear_test_db_override()

def get_csrf_token(test_client, path="/login"):
    resp = test_client.get(path)
    content = resp.text
    marker = 'name="csrf_token" value="'
    idx = content.find(marker)
    if idx != -1:
        start = idx + len(marker)
        return content[start:content.find('"', start)]
    return ""

def login_client(test_client, email, password):
    csrf = get_csrf_token(test_client, "/login")
    return test_client.post("/login", data={"email": email, "password": password, "csrf_token": csrf})
