from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # 'teacher' or 'student'
    name = Column(String)

    # Relationships
    groups_taught = relationship("Group", back_populates="teacher")
    submissions = relationship("Submission", back_populates="student")

class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    teacher_id = Column(Integer, ForeignKey("users.id"))
    
    teacher = relationship("User", back_populates="groups_taught")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="group", cascade="all, delete-orphan")

class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    student_email = Column(String, index=True)

    group = relationship("Group", back_populates="members")

class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    group_id = Column(Integer, ForeignKey("groups.id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    duration_minutes = Column(Integer)
    timer_type = Column(String, default="overall") # "overall" or "per_question"
    default_marks = Column(Float, default=1.0)
    default_negative_marks = Column(Float, default=0.0)
    passing_marks = Column(Float, default=0.0)

    group = relationship("Group", back_populates="exams")
    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="exam", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"))
    text = Column(String)
    marks = Column(Float, nullable=True)
    negative_marks = Column(Float, nullable=True)
    time_limit_seconds = Column(Integer, nullable=True)

    exam = relationship("Exam", back_populates="questions")
    options = relationship("Option", back_populates="question", cascade="all, delete-orphan")

class Option(Base):
    __tablename__ = "options"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"))
    text = Column(String)
    is_correct = Column(Boolean, default=False)

    question = relationship("Question", back_populates="options")

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"))
    student_id = Column(Integer, ForeignKey("users.id"))
    score = Column(Float, index=True)
    submitted_at = Column(DateTime, default=func.now())

    exam = relationship("Exam", back_populates="submissions")
    student = relationship("User", back_populates="submissions")
    answers = relationship("StudentAnswer", back_populates="submission", cascade="all, delete-orphan")

class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    selected_option_id = Column(Integer, ForeignKey("options.id"), nullable=True)
    is_correct = Column(Boolean, default=False)

    submission = relationship("Submission", back_populates="answers")
    question = relationship("Question")
    selected_option = relationship("Option")

class CheatFlag(Base):
    __tablename__ = "cheat_flags"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id"))
    student_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime, default=func.now())
    description = Column(String)
    is_resolved = Column(Boolean, default=False)

    exam = relationship("Exam", backref="cheat_flags")
    student = relationship("User", backref="cheat_flags")
