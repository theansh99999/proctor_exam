"""
modules/analytics/schemas.py
----------------------------
Pydantic v2 schemas for Examiner Analytics, Candidate Performance,
Assessment Metrics, Question Analytics, Org Dashboard, and Report Exports.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ExaminerDashboardMetrics(BaseModel):
    total_assessments: int
    status_counts: Dict[str, int] # draft, published, scheduled, active, completed, archived
    total_candidates_assigned: int
    total_attempts: int
    average_score: float
    average_percentage: float
    pass_rate: float
    fail_rate: float
    pending_grading_count: int
    awaiting_release_count: int
    recent_assessments: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


class AssessmentFilterParams(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    assessment_type: Optional[str] = None
    status: Optional[str] = None
    assessment_id: Optional[int] = None


class TopicPerformanceItem(BaseModel):
    topic: str
    subject: str
    total_questions: int
    total_answered: int
    correct_count: int
    accuracy_percentage: float


class CandidateAttemptHistoryItem(BaseModel):
    session_id: int
    attempt_number: int
    assessment_id: int
    assessment_title: str
    assessment_type: str
    score: float
    total_marks: float
    percentage: float
    pass_fail_status: str
    is_released: bool
    submitted_at: Optional[str] = None


class CandidatePerformanceSummary(BaseModel):
    candidate_id: int
    candidate_name: str
    candidate_email: str
    total_assessments_attempted: int
    average_percentage: float
    best_percentage: float
    latest_percentage: float
    pass_count: int
    fail_count: int
    pending_count: int
    improvement_trend: str # improving, declining, consistent, insufficient_data
    attempts_history: List[CandidateAttemptHistoryItem] = []
    topic_performance: List[TopicPerformanceItem] = []

    model_config = ConfigDict(from_attributes=True)


class QuestionAccuracyItem(BaseModel):
    question_id: int
    question_text: str
    question_type: str
    topic: Optional[str] = None
    subject: Optional[str] = None
    difficulty: Optional[str] = None
    max_marks: float
    total_attempts: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    correct_percentage: float
    incorrect_percentage: float
    unanswered_percentage: float
    average_marks_obtained: float


class AssessmentAnalyticsDetail(BaseModel):
    assessment_id: int
    assessment_title: str
    assessment_type: str
    total_assigned: int
    started_count: int
    completed_count: int
    not_started_count: int
    total_attempts: int
    average_score: float
    highest_score: float
    lowest_score: float
    average_percentage: float
    pass_percentage: float
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    manual_grading_status: str
    pending_manual_grading_count: int
    section_performance: List[Dict[str, Any]] = []
    question_analytics: List[QuestionAccuracyItem] = []
    proctoring_summary: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class OrganizationDashboardMetrics(BaseModel):
    organization_id: Optional[int] = None
    organization_name: str
    total_examiners: int
    total_candidates: int
    total_assessments: int
    active_assessments: int
    completed_assessments: int
    total_attempts: int
    average_organization_percentage: float
    pass_rate: float
    group_performance: List[Dict[str, Any]] = []
    assessment_type_distribution: Dict[str, int] = {}
    activity_trend: List[Dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[Any]
