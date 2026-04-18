from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.concurrency import run_in_threadpool
import models, database, auth
from datetime import datetime, timezone
import traceback

router = APIRouter(prefix="/student", tags=["Student Interface"])
templates = Jinja2Templates(directory="templates")

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
def get_student_notifications(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    """Returns structured notification data for the logged-in student as JSON."""
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]

    now = datetime.now(timezone.utc)
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []

    submissions_done = {s.exam_id for s in db.query(models.Submission).filter(models.Submission.student_id == current_user.id).all()}

    notifications = []

    for exam in exams:
        if exam.id in submissions_done:
            continue  # already submitted – no notification needed

        time_to_start = (exam.start_time - now).total_seconds()
        time_since_start = (now - exam.start_time).total_seconds()
        time_to_end = (exam.end_time - now).total_seconds()

        if time_to_end <= 0:
            continue  # exam already ended

        if time_to_start > 0:
            # Upcoming — show assignment reminder
            notifications.append({
                "type": "upcoming",
                "icon": "📅",
                "title": f"{exam.title} — Upcoming",
                "message": f"Scheduled for {exam.start_time.strftime('%b %d, %I:%M %p')}",
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
                "message": f"Exam is active! Ends at {exam.end_time.strftime('%I:%M %p')}. Click to start.",
                "seconds_to_start": 0,
                "urgent": True,
                "exam_id": exam.id,
            })

    return JSONResponse(content={"notifications": notifications})


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    # Find groups the student is part of
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]

    # Find exams for these groups
    now = datetime.now(timezone.utc)
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []
    
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
        if exam.id in completed_submissions:
            pct = round((completed_submissions[exam.id].score / exam_max_map[exam.id]) * 100, 2)
            past_exams.append({"exam": exam, "score": completed_submissions[exam.id].score, "percentage": pct, "max_marks": exam_max_map[exam.id]})
        elif now < exam.start_time:
            upcoming_exams.append(exam)
        elif exam.start_time <= now <= exam.end_time:
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

@router.get("/take_exam/{exam_id}", response_class=HTMLResponse)
def take_exam(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    try:
        exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
        if not exam:
            raise HTTPException(status_code=404, detail="Exam not found")

        # Check if student is in group
        member = db.query(models.GroupMember).filter(models.GroupMember.group_id == exam.group_id, models.GroupMember.student_email == current_user.email).first()
        if not member:
            raise HTTPException(status_code=403, detail="Not a member of this group")

        # Check if already submitted
        submission = db.query(models.Submission).filter(models.Submission.exam_id == exam_id, models.Submission.student_id == current_user.id).first()
        if submission:
            return RedirectResponse(url="/student/dashboard", status_code=302)

        # Check time validity
        now = datetime.now(timezone.utc)
        if now < exam.start_time or now > exam.end_time:
            return RedirectResponse(url="/student/dashboard", status_code=302)

        questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()
        for q in questions:
            q.ops = q.options

        return templates.TemplateResponse(request=request, name="student/exam_take.html", context={
            "user": current_user,
            "exam": exam,
            "questions": questions
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
    form_data = await request.form()  # ✅ Properly await form data
    
    # Run all DB operations in threadpool (FastAPI handles automatically)
    def process_submission():
        exam_in = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
        questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).all()
        
        sub_in = models.Submission(exam_id=exam_id, student_id=current_user.id, score=0.0)
        db.add(sub_in)
        db.commit()
        db.refresh(sub_in)

        total_score = 0.0

        for q in questions:
            q_marks = q.marks if q.marks is not None else exam_in.default_marks
            q_neg_marks = q.negative_marks if q.negative_marks is not None else exam_in.default_negative_marks
            
            selected_option_id = form_data.get(f"question_{q.id}")
            is_correct = False
            opt_val = None
            if selected_option_id:
                opt_val = int(selected_option_id)
                option = next((o for o in q.options if o.id == opt_val), None)
                if option and option.is_correct:
                    is_correct = True
                    total_score += q_marks
                else:
                    total_score -= q_neg_marks
                    
            ans = models.StudentAnswer(
                submission_id=sub_in.id,
                question_id=q.id,
                selected_option_id=opt_val,
                is_correct=is_correct
            )
            db.add(ans)
        
        # Floor score to minimum 0 (negative marks cannot make score go below 0)
        total_score = max(0.0, total_score)
        sub_in.score = total_score
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
        models.GroupMember.student_email == current_user.email
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="Not assigned to this exam")

    # Only missed exams can be practiced (exam has ended)
    now = datetime.now(timezone.utc)
    if now <= exam.end_time:
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

@router.get("/analysis/{exam_id}", response_class=HTMLResponse)
def view_exam_analysis(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
        
    submission = db.query(models.Submission).filter(models.Submission.exam_id == exam_id, models.Submission.student_id == current_user.id).first()
    if not submission:
        raise HTTPException(status_code=403, detail="You have not submitted this exam yet")
        
    answers = db.query(models.StudentAnswer).options(
        joinedload(models.StudentAnswer.question).joinedload(models.Question.options),
        joinedload(models.StudentAnswer.selected_option)
    ).filter(models.StudentAnswer.submission_id == submission.id).all()
    
    analysis_data = []
    for ans in answers:
        q = ans.question
        correct_options = [opt for opt in q.options if opt.is_correct]
        analysis_data.append({
            "question_text": q.text,
            "your_answer": ans.selected_option.text if ans.selected_option else "Skipped",
            "is_correct": ans.is_correct,
            "correct_answers": [opt.text for opt in correct_options]
        })
        
    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()
    max_marks = calculate_exam_max_marks(questions, exam.default_marks)  # Using helper function
    
    return templates.TemplateResponse(request=request, name="student/exam_analysis.html", context={
        "user": current_user,
        "exam": exam,
        "submission": submission,
        "analysis_data": analysis_data,
        "max_marks": max_marks
    })

from pydantic import BaseModel

class CheatFlagRequest(BaseModel):
    exam_id: int
    description: str

@router.post("/api/cheat_flag")
async def log_cheat_flag(flag: CheatFlagRequest, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    # Run DB operation in threadpool
    def save_cheat_flag():
        try:
            new_flag = models.CheatFlag(
                exam_id=flag.exam_id,
                student_id=current_user.id,
                description=flag.description
            )
            db.add(new_flag)
            db.commit()
            exam = db.query(models.Exam).filter(models.Exam.id == flag.exam_id).first()
            return exam
        except Exception as e:
            print(f"Cheat flag DB error: {str(e)}")
            raise
    
    try:
        exam = await run_in_threadpool(save_cheat_flag)
        
        # Broadcast to Teacher (non-blocking)
        if exam and exam.group:
            from ws_manager import manager
            teacher_id = exam.group.teacher_id
            try:
                await manager.send_personal_message(
                    {"student_name": current_user.name, "description": flag.description, "exam_title": exam.title},
                    teacher_id
                )
            except Exception as ws_err:
                print(f"WebSocket broadcast error: {ws_err}")

        return {"status": "logged"}
    except Exception as e:
        print(f"Cheat flag error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error logging cheat flag: {str(e)}")

@router.get("/practice_list", response_class=HTMLResponse)
def practice_list(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]
    
    now = datetime.now(timezone.utc)
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []
    
    practice_exams = [exam for exam in exams if now > exam.end_time]
    
    return templates.TemplateResponse(request=request, name="student/practice_list.html", context={
        "user": current_user,
        "practice_exams": practice_exams
    })

@router.get("/performance", response_class=HTMLResponse)
def student_performance(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    # Find all groups the student belongs to
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]

    now = datetime.now(timezone.utc)
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
        elif now > exam.end_time:
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
        models.GroupMember.student_email == current_user.email
    ).first()
    if not member:
        return RedirectResponse(url="/student/performance", status_code=302)

    submission = db.query(models.Submission).filter(
        models.Submission.exam_id == exam_id,
        models.Submission.student_id == current_user.id
    ).first()
    if not submission:
        return RedirectResponse(url="/student/performance", status_code=302)

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


