from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import models, database, auth
import datetime

router = APIRouter(prefix="/student", tags=["Student Interface"])
templates = Jinja2Templates(directory="templates")

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    # Find groups the student is part of
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]

    # Find exams for these groups
    now = datetime.datetime.now()
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []
    
    active_exams = []
    upcoming_exams = []
    past_exams = []
    completed_submissions = {sub.exam_id: sub for sub in db.query(models.Submission).filter(models.Submission.student_id == current_user.id).all()}

    for exam in exams:
        if exam.id in completed_submissions:
            past_exams.append({"exam": exam, "score": completed_submissions[exam.id].score})
        elif now < exam.start_time:
            upcoming_exams.append(exam)
        elif exam.start_time <= now <= exam.end_time:
            active_exams.append(exam)
        else:
            past_exams.append({"exam": exam, "score": "Missed"})

    total_attempted = len(completed_submissions)
    total_score = sum(sub.score for sub in completed_submissions.values())
    avg_score = round(total_score / total_attempted, 2) if total_attempted > 0 else 0
    upcoming_count = len(upcoming_exams)
    violations_count = db.query(models.CheatFlag).filter(models.CheatFlag.student_id == current_user.id).count()

    import json
    from collections import defaultdict
    
    # Line Chart Data (Progress over time)
    sorted_subs = sorted(completed_submissions.values(), key=lambda x: x.submitted_at)
    line_labels = json.dumps([sub.submitted_at.strftime('%b %d') for sub in sorted_subs])
    line_data = json.dumps([sub.score for sub in sorted_subs])
    
    # Pie Chart Data (By Group Name)
    group_scores = defaultdict(list)
    for sub in completed_submissions.values():
        exam = db.query(models.Exam).filter(models.Exam.id == sub.exam_id).first()
        if exam and exam.group:
            group_scores[exam.group.name].append(sub.score)
            
    pie_labels = json.dumps(list(group_scores.keys()))
    pie_data = json.dumps([round(sum(scores)/len(scores), 2) for scores in group_scores.values()])

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
    now = datetime.datetime.now()
    if now < exam.start_time or now > exam.end_time:
        return RedirectResponse(url="/student/dashboard", status_code=302)

    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()
    # Eager load options to avoid lazy load issues in template, though sqlalchemy handles it if properly configured
    for q in questions:
        q.ops = db.query(models.Option).filter(models.Option.question_id == q.id).all()

    return templates.TemplateResponse(request=request, name="student/exam_take.html", context={
        "user": current_user,
        "exam": exam,
        "questions": questions,
        "now": now.isoformat()
    })

@router.post("/submit_exam/{exam_id}")
async def submit_exam(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    form_data = await request.form()
    
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    questions = db.query(models.Question).filter(models.Question.exam_id == exam_id).all()
    
    sub = models.Submission(exam_id=exam_id, student_id=current_user.id, score=0.0)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    total_score = 0.0

    for q in questions:
        q_marks = q.marks if q.marks is not None else exam.default_marks
        q_neg_marks = q.negative_marks if q.negative_marks is not None else exam.default_negative_marks
        
        selected_option_id = form_data.get(f"question_{q.id}")
        is_correct = False
        opt_val = None
        if selected_option_id:
            opt_val = int(selected_option_id)
            option = db.query(models.Option).filter(models.Option.id == opt_val).first()
            if option and option.is_correct:
                is_correct = True
                total_score += q_marks
            else:
                total_score -= q_neg_marks
                
        # Save Answer deeply
        ans = models.StudentAnswer(
            submission_id=sub.id,
            question_id=q.id,
            selected_option_id=opt_val,
            is_correct=is_correct
        )
        db.add(ans)
    
    sub.score = total_score
    db.commit()
    
    # Broadcast to Teacher
    from ws_manager import manager
    if exam and exam.group:
        teacher_id = exam.group.teacher_id
        passing_marks = exam.passing_marks or 0
        await manager.send_personal_message({
            "type": "live_submission",
            "exam_id": exam.id,
            "student_name": current_user.name,
            "score": round(sub.score, 2),
            "passed": sub.score >= passing_marks
        }, teacher_id)

    return RedirectResponse(url="/student/dashboard", status_code=302)

@router.get("/analysis/{exam_id}", response_class=HTMLResponse)
def view_exam_analysis(exam_id: int, request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
        
    submission = db.query(models.Submission).filter(models.Submission.exam_id == exam_id, models.Submission.student_id == current_user.id).first()
    if not submission:
        raise HTTPException(status_code=403, detail="You have not submitted this exam yet")
        
    answers = db.query(models.StudentAnswer).filter(models.StudentAnswer.submission_id == submission.id).all()
    
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
        
    return templates.TemplateResponse(request=request, name="student/exam_analysis.html", context={
        "user": current_user,
        "exam": exam,
        "submission": submission,
        "analysis_data": analysis_data
    })

from pydantic import BaseModel

class CheatFlagRequest(BaseModel):
    exam_id: int
    description: str

@router.post("/api/cheat_flag")
async def log_cheat_flag(flag: CheatFlagRequest, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    new_flag = models.CheatFlag(
        exam_id=flag.exam_id,
        student_id=current_user.id,
        description=flag.description
    )
    db.add(new_flag)
    db.commit()
    
    # Broadcast to Teacher
    from ws_manager import manager
    exam = db.query(models.Exam).filter(models.Exam.id == flag.exam_id).first()
    if exam:
        teacher_id = exam.group.teacher_id
        await manager.send_personal_message(
            {"student_name": current_user.name, "description": flag.description, "exam_title": exam.title},
            teacher_id
        )

    return {"status": "logged"}

@router.get("/notifications", response_class=HTMLResponse)
def view_notifications(request: Request, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_student)):
    now = datetime.datetime.now()
    group_memberships = db.query(models.GroupMember).filter(models.GroupMember.student_email == current_user.email).all()
    group_ids = [gm.group_id for gm in group_memberships]
    
    exams = db.query(models.Exam).filter(models.Exam.group_id.in_(group_ids)).all() if group_ids else []
    
    alerts = []
    
    # Upcoming exams
    for e in exams:
        if now < e.start_time and e.start_time <= now + datetime.timedelta(days=7):
            alerts.append({
                "type": "exam",
                "bg_color": "bg-primary",
                "message": f"Upcoming Exam '{e.title}' starts conceptually soon",
                "time": e.start_time.strftime('%b %d, %I:%M %p'),
                "timestamp": e.start_time
            })
            
    alerts.sort(key=lambda x: x["timestamp"])
    return templates.TemplateResponse(request=request, name="teacher/notifications.html", context={"user": current_user, "alerts": alerts, "is_student": True})
