from pydantic import BaseModel, EmailStr
from typing import List, Optional
import datetime

# User Schemas
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str = ""
    role: str = "student"

class UserOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: str

    class Config:
        from_attributes = True

# Group Schemas
class GroupCreate(BaseModel):
    name: str

class GroupOut(BaseModel):
    id: int
    name: str
    teacher_id: int

    class Config:
        from_attributes = True

class GroupMemberAdd(BaseModel):
    student_email: EmailStr

# Exam Schemas
class OptionSchema(BaseModel):
    text: str
    is_correct: bool = False

class QuestionSchema(BaseModel):
    text: str
    options: List[OptionSchema]

class ExamCreate(BaseModel):
    title: str
    group_id: int
    start_time: datetime.datetime
    end_time: datetime.datetime
    duration_minutes: int
    questions: List[QuestionSchema]

class ExamOut(BaseModel):
    id: int
    title: str
    group_id: int
    start_time: datetime.datetime
    end_time: datetime.datetime
    duration_minutes: int

    class Config:
        from_attributes = True

# Token Schemas
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class CheatFlagCreate(BaseModel):
    exam_id: int
    description: str
