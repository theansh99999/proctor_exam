from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
import models, database, auth
import datetime

router = APIRouter(prefix="/teacher", tags=["Teacher Dashboard"])
templates = Jinja2Templates(directory="templates")

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
    now = datetime.datetime.now()
    active_count = len([e for e in exams if e.start_time <= now <= e.end_time])
    
    unique_students = set()
    if group_ids:
        members = db.query(models.GroupMember).filter(models.GroupMember.group_id.in_(group_ids)).all()
        for m in members:
            unique_students.add(m.student_email)
    total_students = len(unique_students)
    
    exam_ids = [e.id for e in exams]
    submissions = db.query(models.Submission).filter(models.Submission.exam_id.in_(exam_ids)).all() if exam_ids else []
    avg_score = round(sum(s.score for s in submissions) / len(submissions), 2) if submissions else 0
    
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
    pass_count = sum(1 for s in submissions if s.score >= 50)
    fail_count = len(submissions) - pass_count
    
    exam_labels = []
    exam_averages = []
    for e in exams:
        esubs = [s for s in submissions if s.exam_id == e.id]
        if esubs:
            trunc_title = e.title[:15] + "..." if len(e.title) > 15 else e.title
            exam_labels.append(trunc_title)
            exam_averages.append(round(sum(s.score for s in esubs)/len(esubs), 2))

    # Student Performance Insights
    student_scores = {}
    for s in submissions:
        if s.student.name not in student_scores:
            student_scores[s.student.name] = []
        student_scores[s.student.name].append(s.score)

    student_averages = [{"name": name, "avg": round(sum(scores)/len(scores), 2)} for name, scores in student_scores.items()]
    student_averages.sort(key=lambda x: x["avg"], reverse=True)
    
    top_performers = student_averages[:3]
    low_scorers = list(reversed(student_averages[-3:])) if len(student_averages) > 3 else []
    
    # ---------------------------
    # Global Alerts & Notifications
    # ---------------------------
    recent_alerts = []
    
    # Upcoming exams
    for e in exams:
        if now < e.start_time < now + datetime.timedelta(days=7):
            recent_alerts.append({
                "type": "exam",
                "bg_color": "bg-primary",
                "message": f"Upcoming Exam '{e.title}' is scheduled to start soon.",
                "time": e.start_time.strftime('%b %d, %I:%M %p'),
                "timestamp": e.start_time - datetime.timedelta(hours=24) # Hack to put it near current time for sorting
            })
            
    # Recent Cheat Flags
    if group_ids:
        recent_flags = db.query(models.CheatFlag).join(models.Exam).filter(models.Exam.group_id.in_(group_ids)).order_by(models.CheatFlag.timestamp.desc()).limit(5).all()
        for f in recent_flags:
            recent_alerts.append({
                "type": "flag",
                "bg_color": "bg-danger",
                "message": f"{f.student.name} triggered violation in '{f.exam.title}': {f.description}",
                "time": f.timestamp.strftime('%I:%M %p Today' if f.timestamp.date() == now.date() else '%b %d, %I:%M %p'),
                "timestamp": f.timestamp
            })
        
    recent_alerts.sort(key=lambda x: x["timestamp"], reverse=True)
    recent_alerts = recent_alerts[:5]

    
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
        "recent_alerts": recent_alerts
    })

@router.post("/create_group")
def create_group(name: str = Form(...), db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
    new_group = models.Group(name=name, teacher_id=current_user.id)
    db.add(new_group)
    db.commit()
    return RedirectResponse(url="/teacher/dashboard", status_code=302)

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
from typing import List

class OptionCreate(BaseModel):
    text: str
    is_correct: bool

class QuestionCreate(BaseModel):
    text: str
    options: List[OptionCreate]

class ExamCreateAPI(BaseModel):
    title: str
    group_id: int
    start_time: str
    end_time: str
    duration_minutes: int
    questions: List[QuestionCreate]

import time

def notify_students_via_email(group_members, exam_title):
    for member in group_members:
        time.sleep(2) # Fake heavy network task
        print(f"\n[BACKGROUND EMAIL SERVICE] 📧 Sent Exam assignment email to {member.student_email} for: '{exam_title}'\n")

@router.post("/api/create_exam")
def api_create_exam(exam_data: ExamCreateAPI, background_tasks: BackgroundTasks, db: Session = Depends(database.get_db), current_user: models.User = Depends(auth.require_teacher)):
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
        duration_minutes=exam_data.duration_minutes
    )
    db.add(new_exam)
    db.commit()
    db.refresh(new_exam)

    for q_data in exam_data.questions:
        q = models.Question(exam_id=new_exam.id, text=q_data.text)
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
    
    for sub in submissions:
        sub.student_name = sub.student.name
        sub.flag_count = db.query(models.CheatFlag).filter(models.CheatFlag.exam_id == exam_id, models.CheatFlag.student_id == sub.student_id).count()
        labels.append(sub.student.name)
        scores.append(round(sub.score, 2))
        total_score += sub.score
        
    avg_score = round(total_score / len(submissions), 2) if submissions else 0
        
    return templates.TemplateResponse(request=request, name="teacher/submissions.html", context={
        "user": current_user, "exam": exam, "submissions": submissions,
        "avg_score": avg_score, "chart_labels": json.dumps(labels), "chart_scores": json.dumps(scores)
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
    
    return templates.TemplateResponse(request=request, name="teacher/exam_settings.html", context={
        "user": current_user,
        "exam": exam,
        "start_time": exam.start_time.strftime('%Y-%m-%dT%H:%M'),
        "end_time": exam.end_time.strftime('%Y-%m-%dT%H:%M')
    })

@router.post("/exam/{exam_id}/settings")
def edit_exam_settings_submit(
    exam_id: int,
    title: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    duration_minutes: int = Form(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.require_teacher)
):
    exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
    if not exam or exam.group.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    exam.title = title
    try:
        exam.start_time = datetime.datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        exam.end_time = datetime.datetime.fromisoformat(end_time.replace('Z', '+00:00'))
    except Exception:
        exam.start_time = datetime.datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
        exam.end_time = datetime.datetime.strptime(end_time, "%Y-%m-%dT%H:%M")
    
    exam.duration_minutes = duration_minutes
    db.commit()
    
    return RedirectResponse(url="/teacher/dashboard", status_code=302)
