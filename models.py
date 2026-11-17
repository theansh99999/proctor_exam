from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, func, UniqueConstraint

from sqlalchemy.orm import relationship, backref, synonym

from datetime import datetime, timezone

from database import Base



class Organization(Base):

    __tablename__ = "organizations"



    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, unique=True, index=True, nullable=False)

    slug = Column(String, unique=True, index=True, nullable=False)

    description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)

    is_suspended = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    # Relationships

    users = relationship("User", back_populates="organization")

    groups = relationship("Group", back_populates="organization")

    exams = relationship("Exam", back_populates="organization")





class User(Base):

    __tablename__ = "users"



    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, unique=True, index=True)

    password_hash = Column(String)

    role = Column(String)  # 'super_admin', 'org_admin', 'examiner'/'teacher', 'candidate'/'student'

    name = Column(String)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    is_active = Column(Boolean, default=True)

    is_suspended = Column(Boolean, default=False)



    # Relationships

    organization = relationship("Organization", back_populates="users")

    groups_taught = relationship("Group", back_populates="teacher", foreign_keys="Group.teacher_id")

    submissions = relationship("Submission", back_populates="student")





class Group(Base):

    __tablename__ = "groups"



    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, index=True)

    teacher_id = Column(Integer, ForeignKey("users.id"))

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)



    organization = relationship("Organization", back_populates="groups")

    teacher = relationship("User", back_populates="groups_taught", foreign_keys=[teacher_id])

    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")

    exams = relationship("Exam", back_populates="group", cascade="all, delete-orphan")





class GroupMember(Base):

    __tablename__ = "group_members"

    __table_args__ = (

        UniqueConstraint("group_id", "student_id", name="uq_group_student"),

    )



    id = Column(Integer, primary_key=True, index=True)

    group_id = Column(Integer, ForeignKey("groups.id"))

    student_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=True)

    student_email = Column(String, index=True, nullable=True)



    group = relationship("Group", back_populates="members")

    student = relationship("User", backref="group_memberships")



    @property

    def email(self) -> str:

        """Return student email from relationship if available, else from student_email column."""

        if self.student and self.student.email:

            return self.student.email

        return self.student_email or ""





class AssessmentBlueprint(Base):

    __tablename__ = "assessment_blueprints"



    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(200), nullable=False)

    description = Column(Text, nullable=True)

    assessment_type = Column(String(50), default="academic", index=True)

    subject = Column(String(100), nullable=False, index=True)

    topics = Column(Text, nullable=True) # JSON list of topic names

    question_types = Column(Text, nullable=True) # JSON list of allowed question types

    difficulty_distribution = Column(Text, nullable=False) # JSON dict: {"easy": X, "medium": Y, "hard": Z}

    total_questions = Column(Integer, default=0)

    total_marks = Column(Float, default=0.0)

    section_mapping = Column(Text, nullable=True) # JSON section configurations

    negative_marking_rules = Column(Text, nullable=True) # JSON dict

    selection_constraints = Column(Text, nullable=True) # JSON dict

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    is_archived = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    organization = relationship("Organization")

    creator = relationship("User", foreign_keys=[created_by])





class AssessmentTemplate(Base):

    __tablename__ = "assessment_templates"



    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(200), nullable=False)

    description = Column(Text, nullable=True)

    assessment_type = Column(String(50), default="academic", index=True)

    duration_minutes = Column(Integer, default=60)

    instructions = Column(Text, nullable=True)

    timer_type = Column(String(20), default="overall")

    default_marks = Column(Float, default=1.0)

    default_negative_marks = Column(Float, default=0.0)

    enable_negative_marking = Column(Boolean, default=False)

    passing_criteria = Column(String(20), default="marks")

    passing_marks = Column(Float, default=0.0)

    passing_percentage = Column(Float, nullable=True)

    max_attempts = Column(Integer, default=1)

    randomize_questions = Column(Boolean, default=False)

    randomize_options = Column(Boolean, default=False)

    is_adaptive = Column(Boolean, default=False)

    visibility = Column(String(50), default="group_only")

    blueprint_id = Column(Integer, ForeignKey("assessment_blueprints.id", ondelete="SET NULL"), nullable=True)

    blueprint_config = Column(Text, nullable=True) # JSON copy of blueprint

    section_config = Column(Text, nullable=True) # JSON section presets

    attempt_policy_config = Column(Text, nullable=True) # JSON attempt policies (cooldown, score policy)

    proctoring_policy_config = Column(Text, nullable=True) # JSON proctoring policies

    adaptive_config = Column(Text, nullable=True) # JSON adaptive rules

    config_metadata = Column(Text, nullable=True) # JSON custom metadata

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    is_system = Column(Boolean, default=False)

    is_archived = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    title = synonym("name")

    attempt_policy = synonym("attempt_policy_config")



    organization = relationship("Organization")

    creator = relationship("User", foreign_keys=[created_by])

    blueprint = relationship("AssessmentBlueprint", foreign_keys=[blueprint_id])





class Exam(Base):

    __tablename__ = "exams"



    id = Column(Integer, primary_key=True, index=True)

    title = Column(String)

    description = Column(Text, nullable=True)

    assessment_type = Column(String, default="academic", index=True) # 'academic', 'placement', 'technical', 'custom'

    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    creator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)



    start_time = Column(DateTime(timezone=True), index=True)

    end_time = Column(DateTime(timezone=True), index=True)

    duration_minutes = Column(Integer)

    timer_type = Column(String, default="overall") # "overall" or "per_question"

    default_marks = Column(Float, default=1.0)

    default_negative_marks = Column(Float, default=0.0)



    # Passing criteria configuration

    passing_marks = Column(Float, default=0.0) # raw cut-off marks

    passing_criteria = Column(String, default="marks") # "marks" or "percentage"

    passing_percentage = Column(Float, nullable=True) # optional percentage cut-off



    max_attempts = Column(Integer, default=1)

    status = Column(String, default="published", index=True) # 'draft', 'published', 'scheduled', 'active', 'completed', 'archived'

    instructions = Column(Text, nullable=True)

    randomize_questions = Column(Boolean, default=False)

    randomize_options = Column(Boolean, default=False)

    enable_negative_marking = Column(Boolean, default=False)

    visibility = Column(String, default="group_only", index=True) # 'public', 'private', 'group_only'

    config_metadata = Column(Text, nullable=True) # JSON-serialized settings/tags/proctoring config

    results_released = Column(Boolean, default=False, index=True)

    is_adaptive = Column(Boolean, default=False)

    adaptive_config = Column(Text, nullable=True) # JSON: starting difficulty, step up/down, boundaries, stopping conditions

    attempt_policy = Column(Text, nullable=True) # JSON: cooldown_minutes, score_policy (best/latest/first/average), retake_eligibility

    blueprint_id = Column(Integer, ForeignKey("assessment_blueprints.id", ondelete="SET NULL"), nullable=True)

    template_id = Column(Integer, ForeignKey("assessment_templates.id", ondelete="SET NULL"), nullable=True)



    organization = relationship("Organization", back_populates="exams")

    creator = relationship("User", foreign_keys=[creator_id])

    group = relationship("Group", back_populates="exams")

    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan")

    submissions = relationship("Submission", back_populates="exam", cascade="all, delete-orphan")

    blueprint = relationship("AssessmentBlueprint", foreign_keys=[blueprint_id])

    template = relationship("AssessmentTemplate", foreign_keys=[template_id])



# Compatibility alias: Assessment maps directly to Exam model

Assessment = Exam





class AssessmentAssignment(Base):

    __tablename__ = "assessment_assignments"

    __table_args__ = (

        UniqueConstraint("assessment_id", "candidate_id", "group_id", name="uq_assessment_assignment_target"),

    )



    id = Column(Integer, primary_key=True, index=True)

    assessment_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False)

    candidate_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)

    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), index=True, nullable=True)

    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    assigned_at = Column(DateTime(timezone=True), default=func.now())



    assessment = relationship("Exam", back_populates="assignments")

    candidate = relationship("User", foreign_keys=[candidate_id], backref="candidate_assignments")

    group = relationship("Group", foreign_keys=[group_id], backref="group_assignments")

    assigner = relationship("User", foreign_keys=[assigned_by])





Exam.assignments = relationship("AssessmentAssignment", back_populates="assessment", cascade="all, delete-orphan")





class BankQuestion(Base):

    __tablename__ = "bank_questions"



    id = Column(Integer, primary_key=True, index=True)

    text = Column(Text, nullable=False)

    question_type = Column(String, default="single_choice", index=True) # single_choice, multiple_choice, true_false, short_answer, descriptive, code

    assessment_category = Column(String, default="academic", index=True) # academic, placement, technical, custom

    subject = Column(String, index=True, nullable=False)

    topic = Column(String, index=True, nullable=False)

    subtopic = Column(String, nullable=True)

    difficulty = Column(String, default="medium", index=True) # easy, medium, hard

    default_marks = Column(Float, default=1.0)

    default_negative_marks = Column(Float, default=0.0)

    explanation = Column(Text, nullable=True)

    tags = Column(Text, nullable=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String, default="draft", index=True) # draft, reviewed, published, archived

    type_config = Column(Text, nullable=True) # JSON: code constraints/samples, expected_answer, evaluation_guidelines

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    organization = relationship("Organization")

    creator = relationship("User", foreign_keys=[created_by])

    options = relationship("BankOption", back_populates="question", cascade="all, delete-orphan")

    mappings = relationship("AssessmentQuestionMap", back_populates="bank_question", cascade="all, delete-orphan")





class BankOption(Base):

    __tablename__ = "bank_options"



    id = Column(Integer, primary_key=True, index=True)

    question_id = Column(Integer, ForeignKey("bank_questions.id", ondelete="CASCADE"), index=True, nullable=False)

    text = Column(Text, nullable=False)

    is_correct = Column(Boolean, default=False)

    explanation = Column(Text, nullable=True)

    order_index = Column(Integer, default=0)



    question = relationship("BankQuestion", back_populates="options")





class AssessmentQuestionMap(Base):

    __tablename__ = "assessment_questions"

    __table_args__ = (

        UniqueConstraint("assessment_id", "bank_question_id", name="uq_assessment_bank_question"),

    )



    id = Column(Integer, primary_key=True, index=True)

    assessment_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False)

    bank_question_id = Column(Integer, ForeignKey("bank_questions.id", ondelete="CASCADE"), index=True, nullable=False)

    order_index = Column(Integer, default=0)

    marks = Column(Float, nullable=True)

    negative_marks = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())



    assessment = relationship("Exam", backref="question_mappings")

    bank_question = relationship("BankQuestion", back_populates="mappings")





class AssessmentSection(Base):

    __tablename__ = "assessment_sections"



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False)

    name = Column(String, nullable=False)

    description = Column(Text, nullable=True)

    order_index = Column(Integer, default=0)

    max_marks = Column(Float, default=0.0)

    passing_percentage = Column(Float, nullable=True)

    is_mandatory = Column(Boolean, default=True)

    time_limit_minutes = Column(Integer, nullable=True)

    navigation_mode = Column(String(20), default="free") # "free" or "sequential"

    instructions = Column(Text, nullable=True)

    randomize_questions = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=func.now())



    exam = relationship("Exam", backref=backref("sections", order_by="AssessmentSection.order_index"))

    questions = relationship("Question", back_populates="section")





class Question(Base):

    __tablename__ = "questions"



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id"))

    section_id = Column(Integer, ForeignKey("assessment_sections.id", ondelete="SET NULL"), nullable=True, index=True)

    bank_question_id = Column(Integer, ForeignKey("bank_questions.id", ondelete="SET NULL"), nullable=True)

    order_index = Column(Integer, default=0)

    question_type = Column(String, default="single_choice")

    explanation = Column(Text, nullable=True)

    text = Column(String)

    marks = Column(Float, nullable=True)

    negative_marks = Column(Float, nullable=True)

    time_limit_seconds = Column(Integer, nullable=True)

    type_config = Column(Text, nullable=True)

    is_mandatory = Column(Boolean, default=False)



    exam = relationship("Exam", back_populates="questions")

    section = relationship("AssessmentSection", back_populates="questions")

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

    __table_args__ = (

        UniqueConstraint("exam_id", "student_id", name="uq_submission_exam_student"),

    )



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id"))

    student_id = Column(Integer, ForeignKey("users.id"))

    score = Column(Float, index=True)

    submitted_at = Column(DateTime(timezone=True), default=func.now())



    exam = relationship("Exam", back_populates="submissions")

    student = relationship("User", back_populates="submissions")

    answers = relationship("StudentAnswer", back_populates="submission", cascade="all, delete-orphan")





class StudentAnswer(Base):

    __tablename__ = "student_answers"



    id = Column(Integer, primary_key=True, index=True)

    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True, index=True)

    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="CASCADE"), nullable=True, index=True)

    question_id = Column(Integer, ForeignKey("questions.id"), index=True)

    selected_option_id = Column(Integer, ForeignKey("options.id"), nullable=True)

    answer_text = Column(Text, nullable=True)

    is_correct = Column(Boolean, default=False)

    marks_awarded = Column(Float, default=0.0)

    evaluation_status = Column(String, default="evaluated", index=True) # evaluated, pending, in_progress, graded

    examiner_feedback = Column(Text, nullable=True)

    graded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    graded_at = Column(DateTime(timezone=True), nullable=True)



    submission = relationship("Submission", back_populates="answers")

    question = relationship("Question")

    selected_option = relationship("Option")

    exam_session = relationship("ExamSession", backref="student_answers")

    grader = relationship("User", foreign_keys=[graded_by])





class ProctoringPolicy(Base):

    __tablename__ = "proctoring_policies"



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)

    webcam_required = Column(Boolean, default=True)

    microphone_required = Column(Boolean, default=False)

    face_detection = Column(Boolean, default=True)

    multiple_face_detection = Column(Boolean, default=True)

    tab_switch_detection = Column(Boolean, default=True)

    fullscreen_required = Column(Boolean, default=True)

    copy_paste_restricted = Column(Boolean, default=True)

    browser_focus_monitoring = Column(Boolean, default=True)

    warning_threshold = Column(Integer, default=3)

    violation_threshold = Column(Integer, default=5)

    auto_submit_threshold = Column(Integer, default=0, nullable=True) # 0 means disabled

    risk_weights = Column(Text, nullable=True) # JSON config

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    exam = relationship("Exam", backref=backref("proctoring_policy", uselist=False, cascade="all, delete-orphan"))





class CheatFlag(Base):

    __tablename__ = "cheat_flags"



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True)

    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True, index=True)

    timestamp = Column(DateTime(timezone=True), default=func.now())

    description = Column(String)

    event_type = Column(String, default="tab_switch", index=True)

    severity = Column(String, default="medium", index=True) # low, medium, high, critical

    event_metadata = Column(Text, nullable=True) # JSON

    validation_status = Column(String, default="valid", index=True) # valid, ignored, duplicate

    is_resolved = Column(Boolean, default=False)

    review_decision = Column(String, nullable=True, index=True) # unreviewed, legitimate, suspicious, inconclusive

    reviewer_notes = Column(Text, nullable=True)

    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    reviewed_at = Column(DateTime(timezone=True), nullable=True)



    exam = relationship("Exam", backref="cheat_flags")

    student = relationship("User", foreign_keys=[student_id], backref="cheat_flags")

    reviewer = relationship("User", foreign_keys=[reviewed_by])

    exam_session = relationship("ExamSession", backref="cheat_flags")





class ExamSession(Base):

    __tablename__ = "exam_sessions"

    __table_args__ = (

        UniqueConstraint("exam_id", "student_id", "attempt_number", name="uq_exam_session_attempt"),

    )



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True)

    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    attempt_number = Column(Integer, default=1)

    started_at = Column(DateTime(timezone=True), default=func.now())

    overall_deadline = Column(DateTime(timezone=True), nullable=True)

    current_question_id = Column(Integer, ForeignKey("questions.id", ondelete="SET NULL"), nullable=True)

    current_question_index = Column(Integer, default=1)

    status = Column(String, default="in_progress", index=True)  # in_progress, completed, submitted, auto_submitted, expired

    score = Column(Float, nullable=True)

    submitted_at = Column(DateTime(timezone=True), nullable=True, index=True)

    submission_type = Column(String, default="manual")  # manual, auto_submitted, expired

    question_order = Column(Text, nullable=True)  # JSON list of question IDs for randomization

    adaptive_state = Column(Text, nullable=True) # JSON adaptive state (difficulty, streak, history)

    current_section_id = Column(Integer, ForeignKey("assessment_sections.id", ondelete="SET NULL"), nullable=True)

    completed_sections = Column(Text, nullable=True) # JSON list of completed section IDs

    integrity_score = Column(Float, default=100.0) # 0.0 to 100.0 integrity scale

    risk_level = Column(String, default="low") # low, medium, high, critical

    proctoring_status = Column(String, default="normal") # normal, warned, flagged, auto_submitted



    exam = relationship("Exam", backref="sessions")

    student = relationship("User", foreign_keys=[student_id], backref="exam_sessions")

    question_sessions = relationship("QuestionSession", back_populates="exam_session", cascade="all, delete-orphan")





class QuestionSession(Base):

    __tablename__ = "question_sessions"

    __table_args__ = (

        UniqueConstraint("exam_session_id", "question_id", name="uq_session_question"),

    )



    id = Column(Integer, primary_key=True, index=True)

    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True)

    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), index=True)

    started_at = Column(DateTime(timezone=True), default=func.now())

    deadline = Column(DateTime(timezone=True))

    selected_option_id = Column(Integer, ForeignKey("options.id", ondelete="SET NULL"), nullable=True)

    answer_text = Column(Text, nullable=True)

    is_bookmarked = Column(Boolean, default=False)

    is_locked = Column(Boolean, default=False)

    option_order = Column(Text, nullable=True) # JSON list of option IDs for option randomization persistence

    submitted_at = Column(DateTime(timezone=True), nullable=True)



    exam_session = relationship("ExamSession", back_populates="question_sessions")

    question = relationship("Question")

    selected_option = relationship("Option")





class ExamResult(Base):

    __tablename__ = "exam_results"

    __table_args__ = (

        UniqueConstraint("exam_session_id", name="uq_result_exam_session"),

    )



    id = Column(Integer, primary_key=True, index=True)

    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), index=True, nullable=False)

    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)

    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)

    attempt_number = Column(Integer, default=1)



    total_marks = Column(Float, default=0.0)

    marks_obtained = Column(Float, default=0.0)

    percentage = Column(Float, default=0.0)

    pass_fail_status = Column(String, default="PENDING", index=True) # PASS, FAIL, PENDING



    correct_count = Column(Integer, default=0)

    incorrect_count = Column(Integer, default=0)

    unanswered_count = Column(Integer, default=0)



    manual_grading_status = Column(String, default="not_required", index=True) # not_required, pending, in_progress, graded

    is_released = Column(Boolean, default=False, index=True)

    released_at = Column(DateTime(timezone=True), nullable=True)



    section_scores = Column(Text, nullable=True) # JSON array of section details

    submission_timestamp = Column(DateTime(timezone=True), nullable=True)

    evaluated_at = Column(DateTime(timezone=True), default=func.now())



    exam = relationship("Exam", backref="results")

    student = relationship("User", foreign_keys=[student_id], backref="results")

    exam_session = relationship("ExamSession", backref=backref("result", uselist=False))





class GradingAudit(Base):

    __tablename__ = "grading_audits"



    id = Column(Integer, primary_key=True, index=True)

    student_answer_id = Column(Integer, ForeignKey("student_answers.id", ondelete="CASCADE"), index=True, nullable=False)

    exam_session_id = Column(Integer, ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True, nullable=False)

    previous_marks = Column(Float, nullable=True)

    new_marks = Column(Float, nullable=False)

    previous_feedback = Column(Text, nullable=True)

    new_feedback = Column(Text, nullable=True)

    changed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    changed_at = Column(DateTime(timezone=True), default=func.now())

    reason = Column(Text, nullable=True)



    student_answer = relationship("StudentAnswer", backref="audit_trail")

    exam_session = relationship("ExamSession", backref="grading_audits")

    grader = relationship("User", foreign_keys=[changed_by])





# =============================================================================

# PHASE 8 — EXTERNAL INTEGRATIONS & INTEROPERABILITY MODELS

# =============================================================================

class IntegrationConfig(Base):

    __tablename__ = "integration_configs"

    __table_args__ = (

        UniqueConstraint("integration_name", "organization_id", name="uq_integration_org"),

    )



    id = Column(Integer, primary_key=True, index=True)

    integration_name = Column(String, index=True, nullable=False) # e.g. "question_generator", "servicenow"

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    is_enabled = Column(Boolean, default=True)

    connection_status = Column(String, default="untested", index=True) # untested, connected, error, disconnected

    base_url = Column(String, nullable=True)

    auth_type = Column(String, default="none") # none, api_key, basic, bearer

    encrypted_credentials = Column(Text, nullable=True) # JSON containing api_key, username, password, token

    config_metadata = Column(Text, nullable=True) # JSON: table mappings, field mappings, timeouts, model settings

    last_tested_at = Column(DateTime(timezone=True), nullable=True)

    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    last_error = Column(Text, nullable=True) # Sanitized error string

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    organization = relationship("Organization", backref="integration_configs")





class IntegrationLog(Base):

    __tablename__ = "integration_logs"



    id = Column(Integer, primary_key=True, index=True)

    integration_name = Column(String, index=True, nullable=False)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    operation = Column(String, index=True, nullable=False) # test_connection, request_questions, sync_assessment, sync_results, retry_sync

    entity_reference = Column(String, nullable=True) # e.g. "exam:1", "batch:uuid", "sync:42"

    status = Column(String, default="success", index=True) # success, failed, partial_success, in_progress

    attempt_count = Column(Integer, default=1)

    request_summary = Column(Text, nullable=True) # Sanitized summary

    response_summary = Column(Text, nullable=True) # Sanitized summary

    error_details = Column(Text, nullable=True) # Sanitized error details (no secrets)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)





class SyncRecord(Base):

    __tablename__ = "sync_records"



    id = Column(Integer, primary_key=True, index=True)

    integration_name = Column(String, index=True, nullable=False)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    entity_type = Column(String, index=True, nullable=False) # assessment, result

    entity_id = Column(Integer, index=True, nullable=False)

    external_reference_id = Column(String, nullable=True) # e.g. ServiceNow sys_id

    idempotency_key = Column(String, unique=True, index=True, nullable=False)

    status = Column(String, default="synced", index=True) # pending, synced, failed

    attempts = Column(Integer, default=1)

    last_error = Column(Text, nullable=True)

    synced_payload = Column(Text, nullable=True) # Sanitized JSON payload

    last_attempt_at = Column(DateTime(timezone=True), default=func.now())

    created_at = Column(DateTime(timezone=True), default=func.now())





# =============================================================================

# PHASE 9: NOTIFICATIONS & COMMUNICATION CENTER MODELS

# =============================================================================



class Notification(Base):

    __tablename__ = "notifications"



    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    category = Column(String(50), default="system", index=True)  # lifecycle, candidate, evaluation, announcement, reminder, system

    event_type = Column(String(100), index=True, nullable=False)

    title = Column(String(255), nullable=False)

    message = Column(Text, nullable=False)

    action_url = Column(String(500), nullable=True)

    is_read = Column(Boolean, default=False, index=True)

    read_at = Column(DateTime(timezone=True), nullable=True)

    is_dismissed = Column(Boolean, default=False, index=True)

    dismissed_at = Column(DateTime(timezone=True), nullable=True)

    notification_metadata = Column(Text, nullable=True)  # JSON-encoded metadata

    delivery_status = Column(String(50), default="sent", index=True)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)



    user = relationship("User", backref="notifications")

    organization = relationship("Organization")





class NotificationPreference(Base):

    __tablename__ = "notification_preferences"



    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    email_enabled = Column(Boolean, default=True)

    in_app_enabled = Column(Boolean, default=True)

    reminders_enabled = Column(Boolean, default=True)

    results_enabled = Column(Boolean, default=True)

    announcements_enabled = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    user = relationship("User", backref="notification_preference", uselist=False)

    organization = relationship("Organization")





class Announcement(Base):

    __tablename__ = "announcements"



    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    title = Column(String(255), nullable=False)

    content = Column(Text, nullable=False)

    target_type = Column(String(50), nullable=False, index=True)  # assessment, group, candidate, all_assigned

    target_id = Column(Integer, nullable=True, index=True)

    channel = Column(String(50), default="both")  # in_app, email, both

    recipient_count = Column(Integer, default=0)

    status = Column(String(50), default="sent", index=True)  # sent, failed

    announcement_metadata = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)



    sender = relationship("User", foreign_keys=[sender_id])

    organization = relationship("Organization")





class NotificationDeliveryLog(Base):

    __tablename__ = "notification_delivery_logs"



    id = Column(Integer, primary_key=True, index=True)

    notification_id = Column(Integer, ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True, index=True)

    announcement_id = Column(Integer, ForeignKey("announcements.id", ondelete="SET NULL"), nullable=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)

    recipient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    channel = Column(String(50), nullable=False, index=True)  # in_app, email

    event_type = Column(String(100), nullable=False, index=True)

    idempotency_key = Column(String(255), unique=True, nullable=True, index=True)

    status = Column(String(50), default="delivered", index=True)  # delivered, failed, pending

    retry_count = Column(Integer, default=0)

    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)

    delivered_at = Column(DateTime(timezone=True), nullable=True)



    recipient = relationship("User", foreign_keys=[recipient_id])

    notification = relationship("Notification")

    announcement = relationship("Announcement")





# =============================================================================

# PHASE 10: PLATFORM ADMINISTRATION & SYSTEM CONFIGURATION MODELS

# =============================================================================



class AuditLog(Base):

    __tablename__ = "audit_logs"



    id = Column(Integer, primary_key=True, index=True)

    actor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)

    action = Column(String(100), nullable=False, index=True)

    entity_type = Column(String(50), nullable=False, index=True)

    entity_id = Column(String(100), nullable=True, index=True)

    ip_address = Column(String(50), nullable=True)

    metadata_json = Column(Text, nullable=True)  # JSON-encoded sanitized metadata

    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)



    actor = relationship("User", foreign_keys=[actor_id])

    organization = relationship("Organization")





class PlatformConfig(Base):

    __tablename__ = "platform_configs"



    id = Column(Integer, primary_key=True, index=True)

    key = Column(String(100), unique=True, index=True, nullable=False)

    value = Column(Text, nullable=False)

    value_type = Column(String(20), default="string")  # string, int, float, bool, json

    description = Column(Text, nullable=True)

    is_sensitive = Column(Boolean, default=False)

    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    updater = relationship("User", foreign_keys=[updated_by])





class OrganizationConfig(Base):

    __tablename__ = "organization_configs"

    __table_args__ = (

        UniqueConstraint("organization_id", "key", name="uq_org_config_key"),

    )



    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    key = Column(String(100), nullable=False, index=True)

    value = Column(Text, nullable=False)

    value_type = Column(String(20), default="string")  # string, int, float, bool, json

    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=func.now())

    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())



    organization = relationship("Organization")

    updater = relationship("User", foreign_keys=[updated_by])
