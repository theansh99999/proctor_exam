from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload
import models, database, auth
from datetime import datetime, timezone

router = APIRouter(prefix="/teacher", tags=["Teacher Dashboard"])
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

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    groups = db.query(models.Group).filter(models.Group.teacher_id == current_user.id).all()
    group_ids = [g.id for g in groups]
    
    # Pre-calculate student counts for each group
    for g in groups:
        g.student_count = db.query(models.GroupMember).filter(models.GroupMember.group_id == g.id).count()
    group_ids = [g.id for g in groups]
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []
    
    # Calculate Stats
    now = datetime.now(timezone.utc)
    active_count = len([e for e in exams if e.start_time <= now <= e.end_time])
    
    unique_students = set()
    if group_ids:
        members = db.query(models.GroupMember).filter(models.GroupMember.group_id.in_(group_ids)).all()
        for m in members:
            unique_students.add(m.student_email)
    total_students = len(unique_students)
    
    # BATCH LOAD: Fetch all questions for all exams in 1 query instead of N queries
    exam_ids = [e.id for e in exams]
    all_questions = db.query(models.Question).filter(models.Question.exam_id.in_(exam_ids)).all() if exam_ids else []
    
    # Group questions by exam_id
    questions_by_exam = {}
    for q in all_questions:
        if q.exam_id not in questions_by_exam:
            questions_by_exam[q.exam_id] = []
        questions_by_exam[q.exam_id].append(q)
    
    # Calculate max marks per exam (using helper function)
    exam_max_map = {}
    for e in exams:
        questions = questions_by_exam.get(e.id, [])
        exam_max_map[e.id] = calculate_exam_max_marks(questions, e.default_marks)

    exam_ids = [e.id for e in exams]
    submissions = db.query(models.Submission).filter(models.Submission.exam_id.in_(exam_ids)).all() if exam_ids else []
    total_percentage = sum((s.score / exam_max_map[s.exam_id] * 100) for s in submissions)
    avg_score = round(total_percentage / len(submissions), 2) if submissions else 0
    
    # Active Exams Detailed Tracking
    active_exams_data = []
    for e in exams:
        if e.start_time <= now <= e.end_time:
            assigned_count = db.query(models.GroupMember).filter(models.GroupMember.group_id == e.group_id).count()
            violation_count = db.query(models.CheatFlag).filter(models.CheatFlag.exam_id == e.id).count()
            
            active_exams_data.append({
                "exam": e,
                "assigned_count": assigned_count,
                "violation_count": violation_count
            })

    # Analytics Data
    pass_count = 0
    for s in submissions:
        e = next((ex for ex in exams if ex.id == s.exam_id), None)
        passing = e.passing_marks if e and e.passing_marks is not None else 0.0
        if s.score >= passing:
            pass_count += 1
    fail_count = len(submissions) - pass_count
    
    exam_labels = []
    exam_averages = []
    for e in exams:
        esubs = [s for s in submissions if s.exam_id == e.id]
        if esubs:
            trunc_title = e.title[:15] + "..." if len(e.title) > 15 else e.title
            exam_labels.append(trunc_title)
            avg_pct = sum((s.score / exam_max_map[e.id] * 100) for s in esubs) / len(esubs)
            exam_averages.append(round(avg_pct, 2))

    # Student Performance Insights
    student_scores = {}
    for s in submissions:
        if s.student.name not in student_scores:
            student_scores[s.student.name] = []
        pct = (s.score / exam_max_map[s.exam_id]) * 100
        student_scores[s.student.name].append(pct)

    student_averages = [{"name": name, "avg": round(sum(scores)/len(scores), 2)} for name, scores in student_scores.items()]
    student_averages.sort(key=lambda x: x["avg"], reverse=True)
    
    top_performers = student_averages[:3]
    low_scorers = list(reversed(student_averages[-3:])) if len(student_averages) > 3 else []
    
    # ---------------------------
    # Global Alerts & Notifications
    # ---------------------------
    recent_alerts = []
    
    # Recent Cheat Flags
    if group_ids:
        recent_flags = db.query(models.CheatFlag).join(models.Exam).filter(models.Exam.group_id.in_(group_ids), models.CheatFlag.is_resolved.is_(False)).order_by(models.CheatFlag.timestamp.desc()).limit(5).all()
        for f in recent_flags:
            recent_alerts.append({
                "type": "flag",
                "bg_color": "bg-danger",
                "message": f"{f.student.name} triggered violation in '{f.exam.title}': {f.description}",
                "time": f.timestamp.strftime('%I:%M %p Today' if f.timestamp.date() == now.date() else '%b %d, %I:%M %p'),
                "timestamp": f.timestamp
            })
        
    recent_alerts.sort(key=lambda x: x["timestamp"], reverse=True)
    all_students = db.query(models.User).filter(models.User.role == "student").order_by(models.User.id.desc()).all()

    return templates.TemplateResponse(request=request, name="teacher/dashboard.html", context={
        "user": current_user, 
        "groups": groups,
        "exams": exams,
        "total_exams": len(exams),
        "total_students": total_students,
        "active_count": active_count,
        "avg_score": avg_score,
        "now": now,
        "active_exams_data": active_exams_data,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "exam_labels": exam_labels,
        "exam_averages": exam_averages,
        "top_performers": top_performers,
        "low_scorers": low_scorers,
        "recent_alerts": recent_alerts,
        "all_students": all_students
    })

@router.post("/create_group")
def create_group(name: str = Form(...), db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    new_group = models.Group(name=name, teacher_id=current_user.id)
    db.add(new_group)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

@router.get("/notifications", response_class=HTMLResponse)
def view_notifications(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    now = datetime.now(timezone.utc)
    groups = db.query(models.Group).filter(models.Group.teacher_id == current_user.id).all()
    group_ids = [g.id for g in groups]
    
    alerts = []
    
    # Unresolved Flags
    flags = []
    if group_ids:
        flags = db.query(models.CheatFlag).join(models.Exam).filter(models.Exam.group_id.in_(group_ids), models.CheatFlag.is_resolved.is_(False)).order_by(models.CheatFlag.timestamp.desc()).all()
    for f in flags:
        alerts.append({
            "id": f.id,
            "type": "flag",
            "bg_color": "bg-danger",
            "message": f"{f.student.name} triggered violation in '{f.exam.title}': {f.description}",
            "time": f.timestamp.strftime('%I:%M %p Today' if f.timestamp.date() == now.date() else '%b %d, %I:%M %p'),
            "timestamp": f.timestamp
        })
        
    alerts.sort(key=lambda x: x["timestamp"], reverse=True)
    return templates.TemplateResponse(request=request, name="teacher/notifications.html", context={"user": current_user, "alerts": alerts})

@router.post("/notifications/clear")
def clear_notifications(db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    groups = db.query(models.Group).filter(models.Group.teacher_id == current_user.id).all()
    group_ids = [g.id for g in groups]
    
    if group_ids:
        # Resolve all flags
        db.query(models.CheatFlag).filter(
            models.CheatFlag.exam_id.in_(
                db.query(models.Exam.id).filter(models.Exam.group_id.in_(group_ids))
            ),
            models.CheatFlag.is_resolved.is_(False)
        ).update({"is_resolved": True}, synchronize_session=False)
        
        db.commit()
    return RedirectResponse(url="/teacher/notifications", status_code=302)

@router.post("/group/{group_id}/delete")
def delete_group(group_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    group = db.query(models.Group).filter(models.Group.id == group_id, models.Group.teacher_id == current_user.id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found or not authorized")
    db.delete(group)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

@router.post("/exam/{exam_id}/delete")
def delete_exam(exam_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=404, detail="Exam not found or not authorized")
    db.delete(exam)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

@router.post("/student/create")
def create_student(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        return RedirectResponse(url="/teacher/dashboard?error=Email+already+exists", status_code=302)
    
    new_student = models.User(
        email=email,
        name=name,
        password_hash=auth.get_password_hash(password),
        role="student"
    )
    db.add(new_student)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

@router.post("/student/{student_id}/update")
def update_student(
    student_id: int,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    student = db.query(models.User).filter(models.User.id == student_id, models.User.role == "student").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    student.name = name
    student.email = email
    if password.strip():
        student.password_hash = auth.get_password_hash(password)
        
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

@router.post("/student/{student_id}/delete")
def delete_student(
    student_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    student = db.query(models.User).filter(models.User.id == student_id, models.User.role == "student").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    db.query(models.CheatFlag).filter(models.CheatFlag.student_id == student_id).delete()
    
    subs = db.query(models.Submission).filter(models.Submission.student_id == student_id).all()
    for s in subs:
        db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id == s.id).delete()
        db.delete(s)
    
    db.query(models.GroupMember).filter(models.GroupMember.student_email == student.email).delete()
    
    db.delete(student)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)


@router.get("/student/{student_id}/profile", response_class=HTMLResponse)
def view_student_profile(
    request: Request,
    student_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    student = db.query(models.User).filter(models.User.id == student_id, models.User.role == "student").first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    teacher_groups = db.query(models.Group).filter(models.Group.teacher_id == current_user.id).all()
    teacher_group_ids = [g.id for g in teacher_groups] if teacher_groups else []
    
    student_group_ids = []
    if teacher_group_ids:
        memberships = db.query(models.GroupMember).filter(
            models.GroupMember.student_email == student.email,
            models.GroupMember.group_id.in_(teacher_group_ids)
        ).all()
        student_group_ids = [m.group_id for m in memberships]
    
    assigned_exams = []
    if student_group_ids:
        assigned_exams = db.query(models.Exam).filter(models.Exam.group_id.in_(student_group_ids)).order_by(models.Exam.start_time.desc()).all()
    
    submissions = []
    if assigned_exams:
        exam_ids = [e.id for e in assigned_exams]
        submissions = db.query(models.Submission).filter(
            models.Submission.student_id == student_id,
            models.Submission.exam_id.in_(exam_ids)
        ).all()
        
    sub_map = {s.exam_id: s for s in submissions}
    now = datetime.now(timezone.utc)
    
    exam_details = []
    tests_taken = 0
    tests_missed = 0
    tests_pending = 0
    total_score = 0
    total_possible_score = 0
    
    for exam in assigned_exams:
        sub = sub_map.get(exam.id)
        questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam.id).all()
        exam_max_marks = calculate_exam_max_marks(questions, exam.default_marks)  # Using helper function
        
        # Build a marks-per-question lookup
        q_marks_map = {q.id: (q.marks if q.marks is not None else exam.default_marks) for q in questions}
        
        status = "pending"
        obtained_marks = 0.0
        if sub:
            status = "taken"
            tests_taken += 1
            # Recalculate actual obtained marks from StudentAnswer records
            answers = db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id == sub.id).all()
            for ans in answers:
                if ans.is_correct:
                    obtained_marks += q_marks_map.get(ans.question_id, exam.default_marks)
                elif ans.selected_option_id is not None:
                    neg = questions[0].negative_marks if questions else None
                    neg_marks = neg if neg is not None else exam.default_negative_marks
                    obtained_marks -= neg_marks
            obtained_marks = max(obtained_marks, 0.0)  # floor at 0
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
        
    return templates.TemplateResponse(request=request, name="teacher/student_profile.html", context={
        "user": current_user,
        "student": student,
        "exam_details": exam_details,
        "tests_assigned": len(assigned_exams),
        "tests_taken": tests_taken,
        "tests_missed": tests_missed,
        "tests_pending": tests_pending,
        "total_score": round(total_score, 2),
        "total_possible_score": round(total_possible_score, 2)
    })

@router.get("/group/{group_id}", response_class=HTMLResponse)
def view_group(group_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    group = db.query(models.Group).filter(models.Group.id == group_id, models.Group.teacher_id == current_user.id).first()
    if not group:
        return RedirectResponse(url="/teacher/dashboard", status_code=302)
    members = db.query(models.GroupMember).filter(models.GroupMember.group_id == group_id).all()
    return templates.TemplateResponse(request=request, name="teacher/group.html", context={"group": group, "members": members, "user": current_user})

@router.post("/group/{group_id}/add_member")
def add_member(group_id: int, student_email: str = Form(...), db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    # Verify group ownership
    group = db.query(models.Group).filter(models.Group.id == group_id, models.Group.teacher_id == current_user.id).first()
    if group:
        # Avoid duplicate
        existing = db.query(models.GroupMember).filter_by(group_id=group_id, student_email=student_email).first()
        if not existing:
            member = models.GroupMember(group_id=group_id, student_email=student_email)
            db.add(member)
            db.commit()
    return RedirectResponse(url=f"/teacher/group/{group_id}", status_code=302)

@router.get("/exam-editor", response_class=HTMLResponse)
def exam_editor(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    groups = db.query(models.Group).filter(models.Group.teacher_id == current_user.id).all()
    return templates.TemplateResponse(request=request, name="teacher/exam_editor.html", context={"groups": groups, "user": current_user})

from pydantic import BaseModel
from typing import List, Optional

class OptionCreate(BaseModel):
    text: str
    is_correct: bool

class QuestionCreate(BaseModel):
    text: str
    options: List[OptionCreate]
    marks: Optional[float] = None
    negative_marks: Optional[float] = None
    time_limit_seconds: Optional[int] = None

class ExamCreateAPI(BaseModel):
    title: str
    group_id: int
    start_time: str
    end_time: str
    duration_minutes: int
    timer_type: str = "overall"
    default_marks: float = 1.0
    default_negative_marks: float = 0.0
    passing_marks: float = 0.0
    questions: List[QuestionCreate]

class OptionEdit(BaseModel):
    id: Optional[int] = None
    text: str
    is_correct: bool

class QuestionEdit(BaseModel):
    id: Optional[int] = None
    text: str
    options: List[OptionEdit]
    marks: Optional[float] = None
    negative_marks: Optional[float] = None
    time_limit_seconds: Optional[int] = None

class ExamEditAPI(BaseModel):
    title: str
    start_time: str
    end_time: str
    duration_minutes: int
    timer_type: str = "overall"
    default_marks: float = 1.0
    default_negative_marks: float = 0.0
    passing_marks: float = 0.0
    questions: List[QuestionEdit]

import time

def notify_students_via_email(group_members, exam_title):
    for member in group_members:
        time.sleep(2) # Fake heavy network task
        print(f"\n[BACKGROUND EMAIL SERVICE] 📧 Sent Exam assignment email to {member.student_email} for: '{exam_title}'\n")

@router.post("/api/create_exam")
def api_create_exam(exam_data: ExamCreateAPI, background_tasks: BackgroundTasks, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    if not exam_data.questions:
        raise HTTPException(status_code=400, detail="At least 1 question must be added")
    # parse datetime
    try:
        st = datetime.datetime.fromisoformat(exam_data.start_time.replace('Z', '+00:00'))
        et = datetime.datetime.fromisoformat(exam_data.end_time.replace('Z', '+00:00'))
    except Exception:
        # Fallback simplistic parsing if needed
        st = datetime.datetime.strptime(exam_data.start_time, "%Y-%m-%dT%H:%M")
        et = datetime.datetime.strptime(exam_data.end_time, "%Y-%m-%dT%H:%M")

    new_exam = models.Exam(
        title=exam_data.title,
        group_id=exam_data.group_id,
        start_time=st,
        end_time=et,
        duration_minutes=exam_data.duration_minutes,
        timer_type=exam_data.timer_type,
        default_marks=exam_data.default_marks,
        default_negative_marks=exam_data.default_negative_marks,
        passing_marks=exam_data.passing_marks
    )
    db.add(new_exam)
    db.commit()
    db.refresh(new_exam)

    for q_data in exam_data.questions:
        q = models.Question(
            exam_id=new_exam.id, 
            text=q_data.text,
            marks=q_data.marks,
            negative_marks=q_data.negative_marks,
            time_limit_seconds=q_data.time_limit_seconds
        )
        db.add(q)
        db.commit()
        db.refresh(q)
        for o_data in q_data.options:
            o = models.Option(question_id=q.id, text=o_data.text, is_correct=o_data.is_correct)
            db.add(o)
    db.commit()
    
    members = db.query(models.GroupMember).filter(models.GroupMember.group_id == exam_data.group_id).all()
    background_tasks.add_task(notify_students_via_email, members, exam_data.title)

    return {"status": "success"}

import json

@router.get("/exam/{exam_id}/submissions", response_class=HTMLResponse)
def view_submissions(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        return RedirectResponse(url="/teacher/dashboard", status_code=302)
    
    submissions = db.query(models.Submission).filter(models.Submission.exam_id == exam_id).all()
    
    labels = []
    scores = []
    total_score = 0
    passing_marks = exam.passing_marks or 0
    
    # Calculate total possible marks for this exam
    questions = db.query(models.Question).options(joinedload(models.Question.options)).filter(models.Question.exam_id == exam_id).order_by(models.Question.id).all()
    total_possible = sum(
        (q.marks if q.marks is not None else exam.default_marks) for q in questions
    )
    if total_possible <= 0:
        total_possible = 1
        
    passed_submissions = []
    failed_submissions = []
    
    for sub in submissions:
        sub.student_name = sub.student.name
        sub.flag_count = db.query(models.CheatFlag).filter(models.CheatFlag.exam_id == exam_id, models.CheatFlag.student_id == sub.student_id).count()
        labels.append(sub.student.name)
        pct = (sub.score / total_possible) * 100
        scores.append(round(pct, 2))
        total_score += pct
        if sub.score >= passing_marks:
            passed_submissions.append(sub)
        else:
            failed_submissions.append(sub)
        
    avg_score = round(total_score / len(submissions), 2) if submissions else 0
    
    # --- Per-Question Analysis ---
    total_students = len(submissions)
    question_analysis = []
    for idx, q in enumerate(questions):
        q_marks = q.marks if q.marks is not None else exam.default_marks
        all_answers = db.query(models.StudentAnswer).filter(models.StudentAnswer.question_id == q.id).all()
        correct_count = sum(1 for a in all_answers if a.is_correct)
        wrong_count = sum(1 for a in all_answers if not a.is_correct and a.selected_option_id is not None)
        skipped_count = total_students - len(all_answers)
        
        # Per-option breakdown
        option_stats = []
        for opt in q.options:
            picked_by = [
                a.submission.student.name 
                for a in all_answers 
                if a.selected_option_id == opt.id
            ]
            option_stats.append({
                "id": opt.id,
                "text": opt.text,
                "is_correct": opt.is_correct,
                "count": len(picked_by),
                "students": picked_by
            })
        
        question_analysis.append({
            "num": idx + 1,
            "id": q.id,
            "text": q.text,
            "marks": q_marks,
            "correct_count": correct_count,
            "wrong_count": wrong_count,
            "skipped_count": skipped_count,
            "total": total_students,
            "option_stats": option_stats
        })
        
    return templates.TemplateResponse(request=request, name="teacher/submissions.html", context={
        "user": current_user, "exam": exam, "submissions": submissions,
        "passed_submissions": passed_submissions,
        "failed_submissions": failed_submissions,
        "avg_score": avg_score,
        "passing_marks": passing_marks,
        "total_possible": total_possible,
        "question_analysis": question_analysis,
        "chart_labels": json.dumps(labels),
        "chart_scores": json.dumps(scores)
    })

@router.get("/exam/{exam_id}/student/{student_id}/report", response_class=HTMLResponse)
def view_student_report(exam_id: int, student_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        return RedirectResponse(url="/teacher/dashboard", status_code=302)
    
    student = db.query(models.User).filter(models.User.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    submission = db.query(models.Submission).filter(
        models.Submission.exam_id == exam_id,
        models.Submission.student_id == student_id
    ).first()
    if not submission:
        return RedirectResponse(url=f"/teacher/exam/{exam_id}/submissions", status_code=302)
    
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
    
    return templates.TemplateResponse(request=request, name="teacher/student_report.html", context={
        "user": current_user,
        "exam": exam,
        "student": student,
        "submission": submission,
        "report_rows": report_rows,
        "total_possible": total_possible,
        "passing_marks": exam.passing_marks or 0
    })

@router.get("/exam/{exam_id}/student/{student_id}/flags", response_class=HTMLResponse)
def view_student_flags(exam_id: int, student_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        return RedirectResponse(url="/teacher/dashboard", status_code=302)
        
    student = db.query(models.User).filter(models.User.id == student_id).first()
    flags = db.query(models.CheatFlag).filter(models.CheatFlag.exam_id == exam_id, models.CheatFlag.student_id == student_id).order_by(models.CheatFlag.timestamp.desc()).all()
    
    return templates.TemplateResponse(request=request, name="teacher/flags.html", context={"user": current_user, "exam": exam, "student": student, "flags": flags})

import csv
from io import StringIO

@router.get("/exam/{exam_id}/export/csv")
def export_csv(exam_id: int, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    submissions = db.query(models.Submission).filter(models.Submission.exam_id == exam_id).all()
    
    file_stream = StringIO()
    writer = csv.writer(file_stream)
    writer.writerow(["Student ID", "Student Name", "Email", "Score (%)", "Submitted At", "Total Cheat Warnings"])
    
    for sub in submissions:
        flag_count = db.query(models.CheatFlag).filter(models.CheatFlag.exam_id == exam_id, models.CheatFlag.student_id == sub.student_id).count()
        writer.writerow([sub.student_id, sub.student.name, sub.student.email, round(sub.score, 2), sub.submitted_at.strftime('%Y-%m-%d %H:%M:%S'), flag_count])
        
    file_stream.seek(0)
    response = StreamingResponse(iter([file_stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename=exam_{exam_id}_report.csv"
    return response

@router.get("/exam/{exam_id}/settings", response_class=HTMLResponse)
def edit_exam_settings_page(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    questions_data = []
    for q in exam.questions:
        q_dict = {
            "id": q.id,
            "text": q.text,
            "marks": q.marks,
            "negative_marks": q.negative_marks,
            "time_limit_seconds": q.time_limit_seconds,
            "options": [{"id": o.id, "text": o.text, "correct": o.is_correct} for o in q.options]
        }
        questions_data.append(q_dict)

    return templates.TemplateResponse(request=request, name="teacher/exam_settings.html", context={
        "user": current_user,
        "exam": exam,
        "start_time": exam.start_time.strftime('%Y-%m-%dT%H:%M'),
        "end_time": exam.end_time.strftime('%Y-%m-%dT%H:%M'),
        "questions_json": json.dumps(questions_data)
    })

@router.post("/api/edit_exam/{exam_id}")
def api_edit_exam(
    exam_id: int,
    exam_data: ExamEditAPI,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if not exam_data.questions:
        raise HTTPException(status_code=400, detail="At least 1 question must be added")

    exam.title = exam_data.title
    try:
        exam.start_time = datetime.datetime.fromisoformat(exam_data.start_time.replace('Z', '+00:00'))
        exam.end_time = datetime.datetime.fromisoformat(exam_data.end_time.replace('Z', '+00:00'))
    except Exception:
        exam.start_time = datetime.datetime.strptime(exam_data.start_time, "%Y-%m-%dT%H:%M")
        exam.end_time = datetime.datetime.strptime(exam_data.end_time, "%Y-%m-%dT%H:%M")
    
    exam.duration_minutes = exam_data.duration_minutes
    exam.timer_type = exam_data.timer_type
    exam.default_marks = exam_data.default_marks
    exam.default_negative_marks = exam_data.default_negative_marks
    exam.passing_marks = exam_data.passing_marks

    incoming_q_ids = [q.id for q in exam_data.questions if q.id is not None]
    
    # Delete removed questions
    for existing_q in exam.questions:
        if existing_q.id not in incoming_q_ids:
            db.query(models.StudentAnswer).filter(models.StudentAnswer.question_id == existing_q.id).delete()
            db.delete(existing_q)
            
    # Update / Insert questions
    for q_data in exam_data.questions:
        if q_data.id is not None:
            q = db.query(models.Question).filter_by(id=q_data.id).first()
            if q:
                q.text = q_data.text
                q.marks = q_data.marks
                q.negative_marks = q_data.negative_marks
                q.time_limit_seconds = q_data.time_limit_seconds
                
                incoming_o_ids = [o.id for o in q_data.options if o.id is not None]
                for existing_o in q.options:
                    if existing_o.id not in incoming_o_ids:
                        db.query(models.StudentAnswer).filter(models.StudentAnswer.selected_option_id == existing_o.id).delete()
                        db.delete(existing_o)
                        
                for o_data in q_data.options:
                    if o_data.id is not None:
                        o = db.query(models.Option).filter_by(id=o_data.id).first()
                        if o:
                            o.text = o_data.text
                            o.is_correct = o_data.is_correct
                    else:
                        new_o = models.Option(question_id=q.id, text=o_data.text, is_correct=o_data.is_correct)
                        db.add(new_o)
        else:
            new_q = models.Question(
                exam_id=exam.id, 
                text=q_data.text,
                marks=q_data.marks,
                negative_marks=q_data.negative_marks,
                time_limit_seconds=q_data.time_limit_seconds
            )
            db.add(new_q)
            db.commit()
            db.refresh(new_q)
            for o_data in q_data.options:
                new_o = models.Option(question_id=new_q.id, text=o_data.text, is_correct=o_data.is_correct)
                db.add(new_o)

    db.commit()
    return {"status": "success"}

@router.get("/exam/{exam_id}/monitor", response_class=HTMLResponse)
def monitor_exam_live(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized or Exam not found")
        
    assigned_count = db.query(models.GroupMember).filter(models.GroupMember.group_id == exam.group_id).count()
    e_subs = db.query(models.Submission).filter(models.Submission.exam_id == exam_id).all()
    passing_marks = exam.passing_marks or 0
    live_submissions = []
    pass_c = 0
    
    for sub in e_subs:
        if sub.score >= passing_marks:
            pass_c += 1
        live_submissions.append({
            "name": sub.student.name,
            "score": round(sub.score, 2),
            "passed": sub.score >= passing_marks
        })
        
    live_submissions.sort(key=lambda x: x["score"], reverse=True)
    
    return templates.TemplateResponse(request=request, name="teacher/exam_monitor.html", context={
        "user": current_user,
        "exam": exam,
        "assigned_count": assigned_count,
        "total_subs": len(e_subs),
        "pass_count": pass_c,
        "fail_count": len(e_subs) - pass_c,
        "live_submissions": live_submissions
    })
