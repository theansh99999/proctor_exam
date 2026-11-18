from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.concurrency import run_in_threadpool
import models, database, auth
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
from time_utils import utc_now, to_utc, to_utc_iso
from core.templates import templates
from modules.assessments.service import AssessmentService
from modules.proctoring.service import ProctoringService
import traceback
import json
import random

router = APIRouter(prefix="/student", tags=["Student Interface"])



# ── Helper Function for Score Calculation ──────────────────────────────────────

def calculate_exam_max_marks(questions: list, default_marks: float) -> float:

    """

    Calculate maximum possible marks for an exam given questions.



    Args:

        questions: List of Question objects

        default_marks: Default marks per question if not specified



    Returns:

        Total maximum marks possible (minimum 1 if no marks found)

    """

    max_m = sum((q.marks if q.marks is not None else default_marks) for q in questions)

    return max_m if max_m > 0 else 1



# ── Notification API ──────────────────────────────────────────────────────────

@router.get("/notifications", response_class=JSONResponse)

def get_student_notifications(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student_api)):

    """Returns structured notification data for the logged-in student as JSON."""

    now = utc_now()

    eligible_ids = AssessmentService.get_eligible_assessment_ids_for_candidate(db, current_user)

    exams = db.query(models.Exam).filter(

        models.Exam.id.in_(eligible_ids),

        models.Exam.status.notin_(["draft", "archived"])

    ).all() if eligible_ids else []



    submissions_done = {s.exam_id for s in db.query(models.Submission).filter(models.Submission.student_id == current_user.id).all()}



    notifications = []



    for exam in exams:

        if exam.id in submissions_done:

            continue  # already submitted – no notification needed



        st = to_utc(exam.start_time)

        et = to_utc(exam.end_time)

        time_to_start = (st - now).total_seconds()

        time_since_start = (now - st).total_seconds()

        time_to_end = (et - now).total_seconds()



        if time_to_end <= 0:

            continue  # exam already ended



        if time_to_start > 0:

            # Upcoming — show assignment reminder

            notifications.append({

                "type": "upcoming",

                "icon": "📅",

                "title": f"{exam.title} — Upcoming",

                "message": f"Scheduled for {st.strftime('%b %d, %I:%M %p')}",

                "seconds_to_start": int(time_to_start),

                "urgent": time_to_start <= 300,  # within 5 minutes

                "exam_id": exam.id,

            })

        elif time_since_start >= 0 and time_to_end > 0:

            # Active right now

            notifications.append({

                "type": "active",

                "icon": "🔴",

                "title": f"{exam.title} — LIVE NOW",

                "message": f"Exam is active! Ends at {et.strftime('%I:%M %p')}. Click to start.",

                "seconds_to_start": 0,

                "urgent": True,

                "exam_id": exam.id,

            })



    return JSONResponse(content={"notifications": notifications})





@router.get("/dashboard", response_class=HTMLResponse)

def dashboard(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    now = utc_now()

    eligible_ids = AssessmentService.get_eligible_assessment_ids_for_candidate(db, current_user)

    exams = db.query(models.Exam).filter(

        models.Exam.id.in_(eligible_ids),

        models.Exam.status.notin_(["draft", "archived"])

    ).all() if eligible_ids else []



    active_exams = []

    upcoming_exams = []

    past_exams = []

    completed_submissions = {sub.exam_id: sub for sub in db.query(models.Submission).filter(models.Submission.student_id == current_user.id).all()}



    # BATCH LOAD: Fetch all questions for all exams in 1 query instead of N queries

    exam_ids = [e.id for e in exams]

    all_questions = db.query(models.Question).filter(models.Question.exam_id.in_(exam_ids)).all() if exam_ids else []



    # Group questions by exam_id

    questions_by_exam = {}

    for q in all_questions:

        if q.exam_id not in questions_by_exam:

            questions_by_exam[q.exam_id] = []

        questions_by_exam[q.exam_id].append(q)



    # Calculate max marks per exam using grouped questions (using helper function)

    exam_max_map = {}

    for exam in exams:

        questions = questions_by_exam.get(exam.id, [])

        exam_max_map[exam.id] = calculate_exam_max_marks(questions, exam.default_marks)



    for exam in exams:

        st = to_utc(exam.start_time)

        et = to_utc(exam.end_time)

        if exam.id in completed_submissions:

            pct = round((completed_submissions[exam.id].score / exam_max_map[exam.id]) * 100, 2)

            past_exams.append({"exam": exam, "score": completed_submissions[exam.id].score, "percentage": pct, "max_marks": exam_max_map[exam.id]})

        elif now < st:

            upcoming_exams.append(exam)

        elif st <= now <= et:

            active_exams.append(exam)

        else:

            past_exams.append({"exam": exam, "score": "Missed", "percentage": 0, "max_marks": exam_max_map[exam.id]})



    total_attempted = len(completed_submissions)



    total_percentage = 0

    for sub in completed_submissions.values():

        total_percentage += (sub.score / exam_max_map[sub.exam_id]) * 100



    avg_score = round(total_percentage / total_attempted, 2) if total_attempted > 0 else 0

    upcoming_count = len(upcoming_exams)

    violations_count = db.query(models.CheatFlag).filter(models.CheatFlag.student_id == current_user.id).count()



    import json

    from collections import defaultdict



    # Line Chart Data (Progress over time)

    sorted_subs = sorted(completed_submissions.values(), key=lambda x: x.submitted_at)

    line_labels = json.dumps([sub.submitted_at.strftime('%b %d') for sub in sorted_subs])

    line_data = json.dumps([round((sub.score / exam_max_map[sub.exam_id]) * 100, 2) for sub in sorted_subs])



    # Pie Chart Data (Pass vs Fail)

    pass_count = 0

    fail_count = 0



    # BATCH LOAD: Fetch all exams for submissions in 1 query instead of fetching per submission

    submission_exam_ids = list(completed_submissions.keys())

    submission_exams = {ex.id: ex for ex in db.query(models.Exam).filter(models.Exam.id.in_(submission_exam_ids)).all()} if submission_exam_ids else {}



    for sub in completed_submissions.values():

        exam = submission_exams.get(sub.exam_id)  # No query - already fetched!

        passing_marks = exam.passing_marks if exam and exam.passing_marks else 0.0

        # passing_marks is RAW MARKS, not percentage - compare directly with submission score

        if sub.score >= passing_marks:

            pass_count += 1

        else:

            fail_count += 1



    pie_labels = json.dumps(["Passed", "Failed"])

    pie_data = json.dumps([pass_count, fail_count])



    return templates.TemplateResponse(request=request, name="student/dashboard.html", context={

        "user": current_user,

        "active_exams": active_exams,

        "upcoming_exams": upcoming_exams,

        "past_exams": past_exams,

        "total_attempted": total_attempted,

        "avg_score": avg_score,

        "upcoming_count": upcoming_count,

        "violations_count": violations_count,

        "line_labels": line_labels,

        "line_data": line_data,

        "pie_labels": pie_labels,

        "pie_data": pie_data

    })



# ── Exam Session & Question Session Tracking Helpers ────────────────────────

def compute_overall_deadline(exam: models.Exam, started_at: datetime) -> Optional[datetime]:

    exam_end = to_utc(exam.end_time)

    duration_deadline = started_at + timedelta(minutes=exam.duration_minutes) if exam.duration_minutes else exam_end

    if exam_end and duration_deadline:

        return min(exam_end, duration_deadline)

    return duration_deadline or exam_end



def evaluate_question_response(

    q: models.Question,

    exam: models.Exam,

    selected_option_id: Optional[int],

    answer_text: Optional[str]

) -> Tuple[bool, float]:

    """

    Evaluates candidate's response across all six question types according to

    institutional marking scheme and negative marking rules.

    Delegates to unified EvaluationService.

    Returns (is_correct: bool, marks_awarded: float).

    """

    from modules.evaluation.service import EvaluationService

    is_corr, marks, _ = EvaluationService.evaluate_question_response(q, exam, selected_option_id, answer_text)

    return is_corr, marks



def get_or_create_exam_session(

    db: Session,

    exam_id_or_exam: Any,

    student_id: int,

    exam: Optional[models.Exam] = None

) -> models.ExamSession:

    if isinstance(exam_id_or_exam, models.Exam):

        exam = exam_id_or_exam

        exam_id = exam.id

    else:

        exam_id = int(exam_id_or_exam)

        if exam is None:

            exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()



    # 1. Check for active in_progress session

    session = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == student_id,

        models.ExamSession.status == "in_progress"

    ).first()

    if session:

        return session



    # 2. Check attempt limits and policies

    from modules.assessments.attempt_policies import AttemptPolicyService

    eligibility = AttemptPolicyService.check_attempt_eligibility(db, exam, student_id)

    if not eligibility["eligible"]:

        raise HTTPException(status_code=403, detail=eligibility["reason"] or "Maximum assessment attempts reached.")



    completed_sessions = eligibility["completed_attempts"]



    next_attempt = completed_sessions + 1

    now = utc_now()

    overall_deadline = compute_overall_deadline(exam, now)



    # 3. Question Randomization

    all_qs = db.query(models.Question).filter(models.Question.exam_id == exam_id).order_by(models.Question.order_index, models.Question.id).all()

    q_order_str = None

    first_q_id = all_qs[0].id if all_qs else None



    if getattr(exam, "randomize_questions", False) and all_qs:

        fixed_qs = [q for q in all_qs if getattr(q, "is_mandatory", False)]

        random_qs = [q for q in all_qs if not getattr(q, "is_mandatory", False)]

        if fixed_qs:

            shuffled_random = random.sample(random_qs, len(random_qs))

            final_order = [q.id for q in fixed_qs] + [q.id for q in shuffled_random]

        else:

            final_order = [q.id for q in random.sample(all_qs, len(all_qs))]

        q_order_str = json.dumps(final_order)

        first_q_id = final_order[0]



    session = models.ExamSession(

        exam_id=exam_id,

        student_id=student_id,

        attempt_number=next_attempt,

        started_at=now,

        overall_deadline=overall_deadline,

        current_question_id=first_q_id,

        current_question_index=1,

        status="in_progress",

        question_order=q_order_str

    )

    db.add(session)

    try:

        db.commit()

        db.refresh(session)

    except Exception:

        db.rollback()

        # Concurrent creation race condition safety: fetch concurrently created session

        session = db.query(models.ExamSession).filter(

            models.ExamSession.exam_id == exam_id,

            models.ExamSession.student_id == student_id,

            models.ExamSession.status == "in_progress"

        ).first()



    # Initialize adaptive testing if enabled

    if getattr(exam, "is_adaptive", False) and session:

        from modules.assessments.adaptive import AdaptiveService

        AdaptiveService.initialize_adaptive_session(db, session, exam)



    # Initialize sections if present

    if session:

        from modules.assessments.sections import SectionService

        SectionService.get_active_section(db, session)



    return session



def get_or_create_question_session(

    db: Session,

    exam_session: models.ExamSession,

    question: models.Question,

    exam: models.Exam

) -> models.QuestionSession:

    qs = db.query(models.QuestionSession).filter(

        models.QuestionSession.exam_session_id == exam_session.id,

        models.QuestionSession.question_id == question.id

    ).first()

    if qs:

        return qs



    now = utc_now()

    limit_sec = question.time_limit_seconds or 60

    calc_deadline = now + timedelta(seconds=limit_sec)



    # Capping question deadline with overall exam deadline

    if exam_session.overall_deadline:

        deadline = min(calc_deadline, to_utc(exam_session.overall_deadline))

    else:

        deadline = calc_deadline



    qs = models.QuestionSession(

        exam_session_id=exam_session.id,

        question_id=question.id,

        started_at=now,

        deadline=deadline,

        is_locked=False

    )

    db.add(qs)

    try:

        db.commit()

        db.refresh(qs)

    except Exception:

        db.rollback()

        # Concurrent request already created it

        qs = db.query(models.QuestionSession).filter(

            models.QuestionSession.exam_session_id == exam_session.id,

            models.QuestionSession.question_id == question.id

        ).first()

    return qs



def finalize_exam_session(

    db: Session,

    exam_session: models.ExamSession,

    student: Any,

    exam: Any,

    submission_type: str = "manual"

) -> models.Submission:

    if isinstance(student, models.Exam) and isinstance(exam, models.User):

        student, exam = exam, student



    # If already finalized, return idempotent result

    if exam_session.status in ("completed", "submitted", "auto_submitted", "expired"):

        existing_sub = db.query(models.Submission).filter(

            models.Submission.exam_id == exam.id,

            models.Submission.student_id == student.id

        ).first()

        if existing_sub:

            return existing_sub



    # Lock all question sessions

    for qs in exam_session.question_sessions:

        qs.is_locked = True



    # Map saved answers from question_sessions

    saved_answers = {qs.question_id: (qs.selected_option_id, getattr(qs, "answer_text", None)) for qs in exam_session.question_sessions}



    questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam.id).all()



    total_score = 0.0

    for q in questions:

        opt_id, ans_text = saved_answers.get(q.id, (None, None))

        is_correct, marks = evaluate_question_response(q, exam, opt_id, ans_text)

        total_score += marks



    total_score = max(0.0, total_score)

    now = utc_now()



    exam_session.status = "submitted" if submission_type == "manual" else ("auto_submitted" if submission_type == "auto" else "completed")

    exam_session.score = total_score

    exam_session.submitted_at = now

    exam_session.submission_type = submission_type



    # Submission record

    existing_sub = db.query(models.Submission).filter(

        models.Submission.exam_id == exam.id,

        models.Submission.student_id == student.id

    ).first()



    if existing_sub:

        existing_sub.score = total_score

        existing_sub.submitted_at = now

        sub = existing_sub

    else:

        sub = models.Submission(

            exam_id=exam.id,

            student_id=student.id,

            score=total_score,

            submitted_at=now

        )

        db.add(sub)

        db.flush()



    # Clear old answers for this submission and session, then record answers

    db.query(models.StudentAnswer).filter(

        (models.StudentAnswer.submission_id == sub.id) | (models.StudentAnswer.exam_session_id == exam_session.id)

    ).delete()

    for q in questions:

        opt_id, ans_text = saved_answers.get(q.id, (None, None))

        ans = models.StudentAnswer(

            submission_id=sub.id,

            exam_session_id=exam_session.id,

            question_id=q.id,

            selected_option_id=opt_id,

            answer_text=ans_text

        )

        db.add(ans)



    db.flush()

    from modules.evaluation.service import EvaluationService

    res = EvaluationService.evaluate_attempt(db, exam_session)

    sub.score = res.marks_obtained

    exam_session.score = res.marks_obtained

    db.commit()



    # Phase 9: Candidate activity notification

    try:

        from modules.notifications.service import NotificationService

        ev_name = "assessment_submitted" if submission_type == "normal" else "assessment_auto_submitted"

        NotificationService.trigger_candidate_activity_event(

            db=db,

            event_type=ev_name,

            exam_id=exam.id,

            student_id=student.id

        )

    except Exception as notif_err:

        print(f"[NOTIF_WARN] Could not trigger candidate activity event: {notif_err}")



    return sub



@router.get("/instructions/{exam_id}", response_class=HTMLResponse)

def view_assessment_instructions(

    exam_id: int,

    request: Request,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student)

):

    if getattr(current_user, "is_suspended", False) or not getattr(current_user, "is_active", True):

        raise HTTPException(status_code=403, detail="Your account is suspended or inactive.")

    if current_user.organization_id:

        org = db.query(models.Organization).filter(models.Organization.id == current_user.organization_id).first()

        if org and (getattr(org, "is_suspended", False) or not getattr(org, "is_active", True)):

            raise HTTPException(status_code=403, detail="Your organization is currently suspended or inactive.")



    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Assessment not found")



    if exam.status in ("draft", "archived"):

        return RedirectResponse(url="/student/dashboard", status_code=302)



    if not AssessmentService.is_candidate_eligible(db, exam, current_user):

        raise HTTPException(status_code=403, detail="Not authorized or assigned to this assessment")



    completed_sessions = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == current_user.id,

        models.ExamSession.status.in_(["completed", "submitted", "auto_submitted", "expired"])

    ).count()



    max_att = exam.max_attempts or 1

    remaining_attempts = max(0, max_att - completed_sessions)



    active_session = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == current_user.id,

        models.ExamSession.status == "in_progress"

    ).first()



    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()

    max_marks = calculate_exam_max_marks(questions, exam.default_marks)



    from modules.proctoring.service import ProctoringService

    policy = ProctoringService.get_or_create_policy(db, exam)



    return templates.TemplateResponse(

        request=request,

        name="student/instructions.html",

        context={

            "user": current_user,

            "exam": exam,

            "policy": policy,

            "total_questions": len(questions),

            "max_marks": max_marks,

            "remaining_attempts": remaining_attempts,

            "active_session": active_session

        }

    )



@router.get("/exam/{exam_id}", response_class=HTMLResponse)

@router.get("/take_exam/{exam_id}", response_class=HTMLResponse)

def take_exam(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    try:

        if getattr(current_user, "is_suspended", False) or not getattr(current_user, "is_active", True):

            raise HTTPException(status_code=403, detail="Your account is suspended or inactive.")

        if current_user.organization_id:

            org = db.query(models.Organization).filter(models.Organization.id == current_user.organization_id).first()

            if org and (getattr(org, "is_suspended", False) or not getattr(org, "is_active", True)):

                raise HTTPException(status_code=403, detail="Your organization is currently suspended or inactive.")



        exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

        if not exam:

            raise HTTPException(status_code=404, detail="Exam not found")



        # Draft and archived assessments are never accessible

        if exam.status in ("draft", "archived"):

            return RedirectResponse(url="/student/dashboard", status_code=302)



        # Check eligibility (group enrollment or direct assignment)

        if not AssessmentService.is_candidate_eligible(db, exam, current_user):

            raise HTTPException(status_code=403, detail="Not authorized or assigned to this assessment")



        # Check time validity

        now = utc_now()

        st = to_utc(exam.start_time)

        et = to_utc(exam.end_time)

        if now < st or now > et:

            return RedirectResponse(url="/student/dashboard", status_code=302)



        # Active ExamSession tracking (handles max_attempts and randomization)

        try:

            exam_session = get_or_create_exam_session(db, exam_id, current_user.id, exam)

        except HTTPException:

            return RedirectResponse(url="/student/dashboard", status_code=302)



        if exam_session.status in ("completed", "submitted", "auto_submitted", "expired"):

            return RedirectResponse(url="/student/dashboard", status_code=302)



        all_questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()



        # Handle Question Order Randomization

        if getattr(exam_session, "question_order", None):

            try:

                order_ids = json.loads(exam_session.question_order)

                q_map = {q.id: q for q in all_questions}

                questions = [q_map[qid] for qid in order_ids if qid in q_map]

            except Exception:

                questions = sorted(all_questions, key=lambda q: (q.order_index or 0, q.id))

        else:

            questions = sorted(all_questions, key=lambda q: (q.order_index or 0, q.id))



        randomize_opts = getattr(exam, "randomize_options", False)

        for q in questions:

            raw_ops = list(q.options)

            if randomize_opts and len(raw_ops) > 1:

                qs = db.query(models.QuestionSession).filter(

                    models.QuestionSession.exam_session_id == exam_session.id,

                    models.QuestionSession.question_id == q.id

                ).first()

                if qs and getattr(qs, "option_order", None):

                    try:

                        ordered_ids = json.loads(qs.option_order)

                        op_map = {op.id: op for op in raw_ops}

                        q.ops = [op_map[oid] for oid in ordered_ids if oid in op_map]

                        missing = [op for op in raw_ops if op.id not in ordered_ids]

                        if missing:

                            q.ops.extend(missing)

                    except Exception:

                        q.ops = raw_ops

                else:

                    shuffled_ops = list(raw_ops)

                    random.shuffle(shuffled_ops)

                    ordered_ids = [op.id for op in shuffled_ops]

                    if not qs:

                        now_qs = utc_now()

                        qs = models.QuestionSession(

                            exam_session_id=exam_session.id,

                            question_id=q.id,

                            started_at=now_qs,

                            deadline=exam_session.overall_deadline or now_qs,

                            is_locked=False,

                            option_order=json.dumps(ordered_ids)

                        )

                        db.add(qs)

                    else:

                        qs.option_order = json.dumps(ordered_ids)

                    try:

                        db.commit()

                    except Exception:

                        db.rollback()

                    q.ops = shuffled_ops

            else:

                q.ops = raw_ops



            if getattr(q, "type_config", None):

                try:

                    q.type_config_dict = json.loads(q.type_config) if isinstance(q.type_config, str) else q.type_config

                except Exception:

                    q.type_config_dict = {}

            else:

                q.type_config_dict = {}



        # Initialize first question session if per_question

        if exam.timer_type == "per_question" and questions:

            get_or_create_question_session(db, exam_session, questions[0], exam)



        policy = ProctoringService.get_or_create_policy(db, exam)



        return templates.TemplateResponse(request=request, name="student/exam_take.html", context={

            "user": current_user,

            "exam": exam,

            "policy": policy,

            "questions": questions,

            "exam_session": exam_session

        })

    except HTTPException:

        raise

    except Exception as e:

        print(f"Error in take_exam: {str(e)}")

        import traceback

        traceback.print_exc()

        raise HTTPException(status_code=500, detail=f"Error loading exam: {str(e)}")



@router.post("/submit_exam/{exam_id}")

async def submit_exam(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    form_data = await request.form()



    def process_submission():

        exam_in = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

        if not exam_in:

            raise HTTPException(status_code=404, detail="Exam not found")

        if not AssessmentService.is_candidate_eligible(db, exam_in, current_user):

            raise HTTPException(status_code=403, detail="Not authorized or assigned to this assessment")



        # Check active ExamSession

        exam_session = db.query(models.ExamSession).filter(

            models.ExamSession.exam_id == exam_id,

            models.ExamSession.student_id == current_user.id,

            models.ExamSession.status == "in_progress"

        ).first()



        # If no active in_progress session, check if already submitted (idempotency)

        if not exam_session:

            latest_session = db.query(models.ExamSession).filter(

                models.ExamSession.exam_id == exam_id,

                models.ExamSession.student_id == current_user.id

            ).order_by(models.ExamSession.attempt_number.desc()).first()

            if latest_session and latest_session.status in ("completed", "submitted", "auto_submitted", "expired"):

                existing_sub = db.query(models.Submission).filter(

                    models.Submission.exam_id == exam_id,

                    models.Submission.student_id == current_user.id

                ).first()

                return exam_in, existing_sub



        questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()



        # Map saved answers from question_sessions (for per-question and autosaved answers)

        saved_q_answers = {}

        if exam_session:

            for qs in exam_session.question_sessions:

                if exam_in.timer_type == "per_question":

                    if qs.submitted_at and to_utc(qs.submitted_at) <= to_utc(qs.deadline) + timedelta(seconds=3):

                        saved_q_answers[qs.question_id] = (qs.selected_option_id, getattr(qs, "answer_text", None))

                else:

                    saved_q_answers[qs.question_id] = (qs.selected_option_id, getattr(qs, "answer_text", None))



        total_score = 0.0

        now = utc_now()

        evaluation_records = []



        for q in questions:

            saved_opt, saved_text = saved_q_answers.get(q.id, (None, None))

            effective_opt_id = None

            effective_text = None



            if exam_in.timer_type == "per_question":

                # Server-authoritative: only answers verified and saved before per-question deadline are accepted

                effective_opt_id = saved_opt

                effective_text = saved_text

            else:

                # Overall timer allows form values with fallback to autosaved session values

                form_opt_val = form_data.get(f"question_{q.id}")

                form_text_val = form_data.get(f"question_{q.id}_text") or form_data.get(f"question_{q.id}")

                form_multi_vals = form_data.getlist(f"question_{q.id}[]")



                if form_multi_vals:

                    effective_text = json.dumps([int(x) for x in form_multi_vals if str(x).isdigit()])

                    effective_opt_id = int(form_multi_vals[0]) if form_multi_vals and str(form_multi_vals[0]).isdigit() else None

                elif form_opt_val and str(form_opt_val).isdigit():

                    effective_opt_id = int(form_opt_val)

                    effective_text = saved_text

                elif form_text_val and not str(form_text_val).isdigit():

                    effective_text = str(form_text_val)

                    effective_opt_id = saved_opt

                else:

                    # Fallback to autosaved session values

                    effective_opt_id = saved_opt

                    effective_text = saved_text



            is_correct, marks = evaluate_question_response(q, exam_in, effective_opt_id, effective_text)

            total_score += marks

            evaluation_records.append({

                "question_id": q.id,

                "selected_option_id": effective_opt_id,

                "answer_text": effective_text,

                "is_correct": is_correct

            })



        total_score = max(0.0, total_score)



        # Lock active ExamSession

        if exam_session:

            sub_type = form_data.get("submission_type", "manual")

            exam_session.status = "submitted" if sub_type == "manual" else ("auto_submitted" if sub_type == "auto" else "completed")

            exam_session.score = total_score

            exam_session.submitted_at = now

            exam_session.submission_type = sub_type

            for qs in exam_session.question_sessions:

                qs.is_locked = True



        # Update or create Submission

        existing_sub = db.query(models.Submission).filter(

            models.Submission.exam_id == exam_id,

            models.Submission.student_id == current_user.id

        ).first()



        if existing_sub:

            existing_sub.score = total_score

            existing_sub.submitted_at = now

            sub_in = existing_sub

            db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id == sub_in.id).delete()

        else:

            sub_in = models.Submission(

                exam_id=exam_id,

                student_id=current_user.id,

                score=total_score,

                submitted_at=now

            )

            db.add(sub_in)

            db.flush()



        for rec in evaluation_records:

            ans = models.StudentAnswer(

                submission_id=sub_in.id,

                exam_session_id=exam_session.id if exam_session else None,

                question_id=rec["question_id"],

                selected_option_id=rec["selected_option_id"],

                answer_text=rec["answer_text"],

                is_correct=rec["is_correct"]

            )

            db.add(ans)



        db.flush()

        if exam_session:

            from modules.evaluation.service import EvaluationService

            res = EvaluationService.evaluate_attempt(db, exam_session)

            sub_in.score = res.marks_obtained

            exam_session.score = res.marks_obtained

        db.commit()

        return exam_in, sub_in



    exam, sub = await run_in_threadpool(process_submission)



    # Broadcast to Teacher (non-blocking)

    if exam and exam.group:

        from ws_manager import manager

        teacher_id = exam.group.teacher_id

        passing_marks = exam.passing_marks or 0

        # passing_marks is RAW MARKS (not percentage) - compare with submission score (also raw marks)

        try:

            await manager.send_personal_message({

                "type": "live_submission",

                "exam_id": exam.id,

                "student_name": current_user.name,

                "score": round(sub.score, 2),

                "passed": sub.score >= passing_marks

            }, teacher_id)

        except Exception as ws_err:

            print(f"WebSocket broadcast error: {ws_err}")



    return RedirectResponse(url="/student/dashboard", status_code=302)



@router.get("/practice_exam/{exam_id}", response_class=HTMLResponse)

def practice_exam(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    # Check if student is in the group (must be assigned)

    member = db.query(models.GroupMember).filter(

        models.GroupMember.group_id == exam.group_id,

        ((models.GroupMember.student_id == current_user.id) | (models.GroupMember.student_email == current_user.email))

    ).first()

    if not member:

        raise HTTPException(status_code=403, detail="Not assigned to this exam")



    # Only missed exams can be practiced (exam has ended)

    now = utc_now()

    if now <= to_utc(exam.end_time):

        return RedirectResponse(url="/student/dashboard", status_code=302)





    questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()

    for q in questions:

        q.ops = q.options



    return templates.TemplateResponse(request=request, name="student/practice_exam.html", context={

        "user": current_user,

        "exam": exam,

        "questions": questions,

    })



@router.post("/submit_practice/{exam_id}", response_class=HTMLResponse)

async def submit_practice(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    form_data = await request.form()  # ✅ Properly await form data



    # Run all DB operations in threadpool (FastAPI handles automatically)

    def process_practice():

        exam_in = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

        if not exam_in:

            return None, None, None, None, None, None



        questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()



        total_score = 0.0

        max_marks = 0.0

        report_rows = []



        for q in questions:

            q_marks = q.marks if q.marks is not None else exam_in.default_marks

            q_neg_marks = q.negative_marks if q.negative_marks is not None else exam_in.default_negative_marks

            max_marks += q_marks



            selected_option_id = form_data.get(f"question_{q.id}")

            is_correct = False

            selected_opt = None

            earned = 0.0



            if selected_option_id:

                opt = next((o for o in q.options if o.id == int(selected_option_id)), None)

                selected_opt = opt

                if opt and opt.is_correct:

                    is_correct = True

                    total_score += q_marks

                    earned = q_marks

                else:

                    total_score -= q_neg_marks

                    earned = -q_neg_marks



            report_rows.append({

                "num": questions.index(q) + 1,

                "text": q.text,

                "marks": q_marks,

                "options": q.options,

                "selected_option": selected_opt,

                "is_correct": is_correct,

                "skipped": selected_option_id is None,

                "earned": earned,

            })



        # Floor score to minimum 0 (negative marks cannot make score go below 0)

        total_score = max(0.0, total_score)

        passing_marks = exam_in.passing_marks or 0.0

        # passing_marks is RAW MARKS (not percentage) - compare directly with total_score

        passed = total_score >= passing_marks

        return exam_in, total_score, max_marks, report_rows, passing_marks, passed



    exam, total_score, max_marks, report_rows, passing_marks, passed = await run_in_threadpool(process_practice)

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    return templates.TemplateResponse(request=request, name="student/practice_result.html", context={

        "user": current_user,

        "exam": exam,

        "total_score": round(total_score, 2),

        "max_marks": round(max_marks, 2),

        "passing_marks": passing_marks,

        "passed": passed,

        "report_rows": report_rows,

    })





from pydantic import BaseModel

from typing import Optional, List, Dict, Any



class QuestionAnswerRequest(BaseModel):

    question_id: int

    selected_option_id: Optional[int] = None

    selected_option_ids: Optional[List[int]] = None

    answer_text: Optional[str] = None

    is_bookmarked: Optional[bool] = None



class NextQuestionRequest(BaseModel):

    current_question_id: int



@router.get("/api/exam/{exam_id}/timer_state")

def get_exam_timer_state(

    exam_id: int,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student_api)

):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    # Check enrollment / assignment eligibility

    if not AssessmentService.is_candidate_eligible(db, exam, current_user):

        raise HTTPException(status_code=403, detail="Student not enrolled in or assigned to this assessment")



    # Check if already submitted

    submission = db.query(models.Submission).filter(

        models.Submission.exam_id == exam_id,

        models.Submission.student_id == current_user.id

    ).first()

    if submission:

        return {"status": "submitted", "is_expired": True, "score": submission.score}



    now = utc_now()

    exam_session = get_or_create_exam_session(db, exam_id, current_user.id, exam)



    # Server-side check: overall deadline expired

    if exam_session.overall_deadline and now > to_utc(exam_session.overall_deadline):

        sub = finalize_exam_session(db, exam_session, current_user, exam, submission_type="auto")

        return {

            "status": "expired",

            "is_expired": True,

            "reason": "overall_deadline_reached",

            "score": sub.score

        }



    # Handle Question Order Randomization

    all_questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()

    if getattr(exam_session, "question_order", None):

        try:

            ordered_ids = json.loads(exam_session.question_order)

            q_map = {q.id: q for q in all_questions}

            questions = [q_map[qid] for qid in ordered_ids if qid in q_map]

        except Exception:

            questions = sorted(all_questions, key=lambda q: (q.order_index or 0, q.id))

    else:

        questions = sorted(all_questions, key=lambda q: (q.order_index or 0, q.id))



    if exam.timer_type == "per_question":

        q_sessions = {qs.question_id: qs for qs in exam_session.question_sessions}

        saved_answers = {qs.question_id: qs.selected_option_id for qs in exam_session.question_sessions if qs.selected_option_id}

        locked_q_ids = [qs.question_id for qs in exam_session.question_sessions if qs.is_locked]



        current_q = None

        current_idx = 1

        for idx, q in enumerate(questions, 1):

            qs = q_sessions.get(q.id)

            if not qs:

                qs = get_or_create_question_session(db, exam_session, q, exam)

                q_sessions[q.id] = qs



            deadline_with_grace = to_utc(qs.deadline) + timedelta(seconds=3)

            if now > deadline_with_grace or qs.is_locked:

                if not qs.is_locked:

                    qs.is_locked = True

                    db.commit()

                if q.id not in locked_q_ids:

                    locked_q_ids.append(q.id)

            else:

                current_q = q

                current_idx = idx

                break



        if not current_q:

            # All questions expired -> server auto finalizes

            sub = finalize_exam_session(db, exam_session, current_user, exam, submission_type="auto")

            return {

                "status": "completed",

                "is_expired": True,

                "reason": "all_questions_expired",

                "score": sub.score,

                "saved_answers": saved_answers,

                "locked_question_ids": locked_q_ids

            }



        active_qs = q_sessions[current_q.id]

        rem_sec = max(0, int((to_utc(active_qs.deadline) - now).total_seconds()))



        exam_session.current_question_id = current_q.id

        exam_session.current_question_index = current_idx

        db.commit()



        return {

            "status": "active",

            "timer_type": "per_question",

            "current_question_id": current_q.id,

            "current_question_index": current_idx,

            "total_questions": len(questions),

            "remaining_seconds": rem_sec,

            "deadline": to_utc_iso(active_qs.deadline),

            "is_locked": active_qs.is_locked,

            "locked_question_ids": locked_q_ids,

            "saved_answers": saved_answers

        }

    else:

        # Overall timer

        overall_rem = max(0, int((to_utc(exam_session.overall_deadline) - now).total_seconds())) if exam_session.overall_deadline else 3600

        saved_answers = {}

        saved_answers_detail = {}

        for qs in exam_session.question_sessions:

            if qs.selected_option_id or getattr(qs, "answer_text", None) or getattr(qs, "is_bookmarked", False):

                saved_answers[qs.question_id] = qs.selected_option_id

                multi_ids = []

                txt = getattr(qs, "answer_text", None)

                if txt and txt.startswith("[") and txt.endswith("]"):

                    try:

                        multi_ids = json.loads(txt)

                    except Exception:

                        pass

                saved_answers_detail[qs.question_id] = {

                    "selected_option_id": qs.selected_option_id,

                    "selected_option_ids": multi_ids,

                    "answer_text": txt,

                    "is_bookmarked": getattr(qs, "is_bookmarked", False)

                }



        return {

            "status": "active",

            "timer_type": "overall",

            "remaining_seconds": overall_rem,

            "total_questions": len(questions),

            "saved_answers": saved_answers,

            "saved_answers_detail": saved_answers_detail,

            "is_expired": False

        }



@router.post("/api/exam/{exam_id}/save_question_answer")

def save_question_answer(

    exam_id: int,

    req: QuestionAnswerRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student_api)

):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    exam_session = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == current_user.id,

        models.ExamSession.status == "in_progress"

    ).first()

    if not exam_session:

        # Check if already completed/submitted

        completed_sess = db.query(models.ExamSession).filter(

            models.ExamSession.exam_id == exam_id,

            models.ExamSession.student_id == current_user.id,

            models.ExamSession.status.in_(["completed", "submitted", "auto_submitted", "expired"])

        ).first()

        if completed_sess:

            raise HTTPException(status_code=400, detail="Attempt already completed or expired. Answer rejected.")



        if not AssessmentService.is_candidate_eligible(db, exam, current_user):

            raise HTTPException(status_code=403, detail="Not authorized or assigned to this assessment")



        exam_session = get_or_create_exam_session(db, exam_id, current_user.id, exam)



    now = utc_now()

    if exam_session.overall_deadline and now > to_utc(exam_session.overall_deadline) + timedelta(seconds=3):

        finalize_exam_session(db, exam_session, current_user, exam, submission_type="auto")

        raise HTTPException(status_code=400, detail="Overall exam deadline has expired. Answer rejected.")



    question = db.query(models.Question).filter(models.Question.id == req.question_id, models.Question.exam_id == exam_id).first()

    if not question:

        raise HTTPException(status_code=404, detail="Question not found in this exam")



    if req.selected_option_id is not None:

        opt = db.query(models.Option).filter(models.Option.id == req.selected_option_id, models.Option.question_id == req.question_id).first()

        if not opt:

            raise HTTPException(status_code=400, detail="Invalid option for question")



    qs = get_or_create_question_session(db, exam_session, question, exam)



    # Per-question deadline validation

    if exam.timer_type == "per_question":

        grace_deadline = to_utc(qs.deadline) + timedelta(seconds=3)

        if qs.is_locked or now > grace_deadline:

            qs.is_locked = True

            db.commit()

            raise HTTPException(status_code=400, detail="Question deadline has expired. Answer rejected.")



    # Save answers depending on question type

    if req.selected_option_id is not None:

        qs.selected_option_id = req.selected_option_id

    elif req.selected_option_ids is not None:

        qs.answer_text = json.dumps(req.selected_option_ids)

        qs.selected_option_id = req.selected_option_ids[0] if req.selected_option_ids else None



    if req.answer_text is not None and req.selected_option_ids is None:

        qs.answer_text = req.answer_text



    if req.is_bookmarked is not None:

        qs.is_bookmarked = req.is_bookmarked



    qs.submitted_at = now

    db.commit()

    return {

        "status": "saved",

        "question_id": req.question_id,

        "selected_option_id": qs.selected_option_id,

        "answer_text": getattr(qs, "answer_text", None),

        "is_bookmarked": getattr(qs, "is_bookmarked", False),

        "saved_at": to_utc_iso(now)

    }



@router.post("/api/exam/{exam_id}/next_question")

def next_question_endpoint(

    exam_id: int,

    req: NextQuestionRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student_api)

):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    exam_session = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == current_user.id,

        models.ExamSession.status == "in_progress"

    ).first()

    if not exam_session:

        raise HTTPException(status_code=400, detail="No active exam session")



    # Lock current question session

    cur_qs = db.query(models.QuestionSession).filter(

        models.QuestionSession.exam_session_id == exam_session.id,

        models.QuestionSession.question_id == req.current_question_id

    ).first()

    if cur_qs:

        cur_qs.is_locked = True

        db.commit()



    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).order_by(models.Question.id).all()

    q_ids = [q.id for q in questions]



    try:

        cur_idx = q_ids.index(req.current_question_id)

    except ValueError:

        cur_idx = -1



    if cur_idx + 1 < len(questions):

        next_q = questions[cur_idx + 1]

        next_qs = get_or_create_question_session(db, exam_session, next_q, exam)

        exam_session.current_question_id = next_q.id

        exam_session.current_question_index = cur_idx + 2

        db.commit()



        now = utc_now()

        rem_sec = max(0, int((to_utc(next_qs.deadline) - now).total_seconds()))

        return {

            "status": "next",

            "question_id": next_q.id,

            "question_index": cur_idx + 2,

            "remaining_seconds": rem_sec,

            "total_questions": len(questions)

        }

    else:

        # Last question completed -> auto finalize

        sub = finalize_exam_session(db, exam_session, current_user, exam)

        return {

            "status": "completed",

            "is_last": True,

            "score": sub.score

        }



@router.post("/api/exam/{exam_id}/finalize_session")

def finalize_session_endpoint(

    exam_id: int,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student_api)

):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    exam_session = db.query(models.ExamSession).filter(

        models.ExamSession.exam_id == exam_id,

        models.ExamSession.student_id == current_user.id,

        models.ExamSession.status == "in_progress"

    ).first()

    if not exam_session:

        sub = db.query(models.Submission).filter(

            models.Submission.exam_id == exam_id,

            models.Submission.student_id == current_user.id

        ).first()

        return {"status": "already_finalized", "score": sub.score if sub else 0.0}



    sub = finalize_exam_session(db, exam_session, current_user, exam)

    return {"status": "finalized", "score": sub.score}



class CheatFlagRequest(BaseModel):

    exam_id: int

    description: str

    event_type: Optional[str] = None

    severity: Optional[str] = None

    metadata: Optional[Dict[str, Any]] = None



@router.post("/api/cheat_flag")

async def log_cheat_flag(

    flag: CheatFlagRequest,

    db: Session = Depends(database.get_db),

    current_user: models.User = Depends(auth.require_student_api)

):

    from modules.proctoring.service import ProctoringService

    from modules.proctoring.schemas import ProctoringEventIngest



    # Infer event_type from description if not provided

    event_type = flag.event_type

    if not event_type:

        desc_l = flag.description.lower()

        if "tab" in desc_l:

            event_type = "tab_switch"

        elif "focus" in desc_l or "window" in desc_l:

            event_type = "window_blur"

        elif "fullscreen" in desc_l:

            event_type = "fullscreen_exit"

        elif "multiple faces" in desc_l:

            event_type = "multiple_faces"

        elif "no face" in desc_l or "face not detected" in desc_l:

            event_type = "face_not_detected"

        elif "camera" in desc_l:

            event_type = "camera_disconnected"

        elif "microphone" in desc_l or "talking" in desc_l or "noise" in desc_l:

            event_type = "microphone_disconnected"

        else:

            event_type = "suspicious_activity"



    event_in = ProctoringEventIngest(

        exam_id=flag.exam_id,

        description=flag.description,

        event_type=event_type,

        severity=flag.severity,

        metadata=flag.metadata

    )

    return await ProctoringService.ingest_event(db, current_user, event_in)



@router.get("/practice_list", response_class=HTMLResponse)

def practice_list(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    group_memberships = db.query(models.GroupMember).filter(

        (models.GroupMember.student_id == current_user.id) | (models.GroupMember.student_email == current_user.email)

    ).all()

    group_ids = [gm.group_id for gm in group_memberships]



    now = utc_now()

    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []



    practice_exams = [exam for exam in exams if now > to_utc(exam.end_time)]



    return templates.TemplateResponse(request=request, name="student/practice_list.html", context={

        "user": current_user,

        "practice_exams": practice_exams

    })



@router.get("/performance", response_class=HTMLResponse)

def student_performance(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    # Find all groups the student belongs to

    group_memberships = db.query(models.GroupMember).filter(

        (models.GroupMember.student_id == current_user.id) | (models.GroupMember.student_email == current_user.email)

    ).all()

    group_ids = [gm.group_id for gm in group_memberships]



    now = utc_now()

    assigned_exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).order_by(models.Exam.start_time.desc()).all() if group_ids else []



    submissions = []

    if assigned_exams:

        exam_ids = [e.id for e in assigned_exams]

        submissions = db.query(models.Submission).filter(

            models.Submission.student_id == current_user.id,

            models.Submission.exam_id.in_(exam_ids)

        ).all()



    sub_map = {s.exam_id: s for s in submissions}



    # BATCH LOAD: Fetch all questions for all exams in 1 query

    exam_ids = [e.id for e in assigned_exams]

    all_questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id.in_(exam_ids)).all() if exam_ids else []

    questions_by_exam = {}

    for q in all_questions:

        if q.exam_id not in questions_by_exam:

            questions_by_exam[q.exam_id] = []

        questions_by_exam[q.exam_id].append(q)



    # BATCH LOAD: Fetch all answers for all submissions in 1 query

    submission_ids = [s.id for s in submissions]

    all_answers = db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id.in_(submission_ids)).all() if submission_ids else []

    answers_by_submission = {}

    for ans in all_answers:

        if ans.submission_id not in answers_by_submission:

            answers_by_submission[ans.submission_id] = []

        answers_by_submission[ans.submission_id].append(ans)



    exam_details = []

    tests_taken = 0

    tests_missed = 0

    tests_pending = 0

    total_score = 0.0

    total_possible_score = 0.0



    for exam in assigned_exams:

        sub = sub_map.get(exam.id)

        questions = questions_by_exam.get(exam.id, [])  # No query - already batch loaded!

        exam_max_marks = calculate_exam_max_marks(questions, exam.default_marks)  # Using helper function

        q_marks_map = {q.id: (q.marks if q.marks is not None else exam.default_marks) for q in questions}



        status = "pending"

        obtained_marks = 0.0

        if sub:

            status = "taken"

            tests_taken += 1

            answers = answers_by_submission.get(sub.id, [])  # No query - already batch loaded!

            for ans in answers:

                if ans.is_correct:

                    obtained_marks += q_marks_map.get(ans.question_id, exam.default_marks)

                elif ans.selected_option_id is not None:

                    neg = questions[0].negative_marks if questions else None

                    neg_marks = neg if neg is not None else exam.default_negative_marks

                    obtained_marks -= neg_marks

            # Floor at 0 - marks cannot go negative

            obtained_marks = max(obtained_marks, 0.0)

            total_score += obtained_marks

            total_possible_score += exam_max_marks

        elif now > to_utc(exam.end_time):

            status = "missed"

            tests_missed += 1

        else:

            tests_pending += 1



        exam_details.append({

            "exam": exam,

            "submission": sub,

            "status": status,

            "max_marks": round(exam_max_marks, 2),

            "questions_count": len(questions),

            "obtained_marks": round(obtained_marks, 2)

        })



    return templates.TemplateResponse(request=request, name="student/performance.html", context={

        "user": current_user,

        "exam_details": exam_details,

        "tests_assigned": len(assigned_exams),

        "tests_taken": tests_taken,

        "tests_missed": tests_missed,

        "tests_pending": tests_pending,

        "total_score": round(total_score, 2),

        "total_possible_score": round(total_possible_score, 2),

    })





@router.get("/my_report/{exam_id}", response_class=HTMLResponse)

def student_my_report(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):

    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()

    if not exam:

        raise HTTPException(status_code=404, detail="Exam not found")



    # Make sure student was a member of this exam's group

    member = db.query(models.GroupMember).filter(

        models.GroupMember.group_id == exam.group_id,

        ((models.GroupMember.student_id == current_user.id) | (models.GroupMember.student_email == current_user.email))

    ).first()

    if not member:

        return RedirectResponse(url="/student/performance", status_code=302)



    submission = db.query(models.Submission).filter(

        models.Submission.exam_id == exam_id,

        models.Submission.student_id == current_user.id

    ).first()

    if not submission:

        return RedirectResponse(url="/student/performance", status_code=302)



    res = db.query(models.ExamResult).filter_by(exam_id=exam_id, student_id=current_user.id).order_by(models.ExamResult.attempt_number.desc()).first()

    is_released = True

    if res is not None:

        is_released = res.is_released or (exam.results_released is True)

    elif exam.results_released is False:

        is_released = False



    if not is_released:

        return templates.TemplateResponse(request=request, name="student/results_pending.html", context={

            "user": current_user,

            "exam": exam,

            "message": "Results for this assessment are currently being evaluated and have not been released by the examiner yet."

        })



    questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).order_by(models.Question.id).all()

    answers_map = {

        a.question_id: a

        for a in db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id == submission.id).all()

    }



    total_possible = calculate_exam_max_marks(questions, exam.default_marks)  # Using helper function



    report_rows = []

    for idx, q in enumerate(questions):

        ans = answers_map.get(q.id)

        correct_opt = next((o for o in q.options if o.is_correct), None)

        selected_opt = ans.selected_option if ans and ans.selected_option_id else None

        q_marks = q.marks if q.marks is not None else exam.default_marks



        report_rows.append({

            "num": idx + 1,

            "text": q.text,

            "marks": q_marks,

            "options": q.options,

            "selected_option": selected_opt,

            "correct_option": correct_opt,

            "is_correct": ans.is_correct if ans else False,

            "skipped": ans is None or ans.selected_option_id is None

        })



    return templates.TemplateResponse(request=request, name="student/my_report.html", context={

        "user": current_user,

        "exam": exam,

        "submission": submission,

        "report_rows": report_rows,

        "total_possible": total_possible,

        "passing_marks": exam.passing_marks or 0

    })
