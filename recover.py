import os
import glob
import shutil

blobs_dir = os.path.join('.git', 'lost-found', 'other')
blobs = glob.glob(os.path.join(blobs_dir, '*'))

blob_info = []
for b in blobs:
    try:
        h = os.path.basename(b)
        obj_path = os.path.join('.git', 'objects', h[:2], h[2:])
        mtime = os.path.getmtime(obj_path)
        blob_info.append((b, mtime))
    except Exception:
        pass

# Sort by mtime descending (newest first)
blob_info.sort(key=lambda x: x[1], reverse=True)

recovered_files = set()

def identify_content(content):
    # Python
    if "tags=[\"UI Auth\"]" in content: return "routers/auth_r.py"
    if "def dashboard" in content and "active_exams_data" in content: return "routers/teacher_r.py"
    if "def dashboard" in content and "available_exams" in content: return "routers/student_r.py"
    if "class ConnectionManager:" in content: return "ws_manager.py"
    if "class CheatFlag" in content: return "models.py"
    if "declarative_base()" in content and "sessionmaker(" in content: return "database.py" 
    if "pwd_context = CryptContext" in content: return "auth.py"
    if "FastAPI(" in content and "include_router" in content: return "main.py"
    if "text-body-emphasis" in content and "replacements =" in content: return "mass_replace.py"
    
    # HTML
    if "{% block content %}{% endblock %}" in content and "themeToggleBtn" in content: return "templates/base.html"
    if "action=\"/login\"" in content: return "templates/auth/login.html"
    if "action=\"/register\"" in content: return "templates/auth/register.html"
    if "Account Settings" in content: return "templates/auth/settings.html"
    if "Account Level" in content and "Return to Dashboard" in content: return "templates/auth/profile.html"
    if "Action Alerts" in content and "Your Cohorts" in content: return "templates/teacher/dashboard.html"
    if "Action Alerts" in content and "Create New Cohort" in content: return "templates/teacher/dashboard.html"
    if "export/csv" in content or ("Student Submissions" in content): return "templates/teacher/submissions.html"
    if "Security Audit Logs" in content or "bi-exclamation-octagon-fill" in content: return "templates/teacher/flags.html"
    if "action=\"/teacher/exam/{{ exam.id }}/settings\"" in content: return "templates/teacher/exam_settings.html"
    if "addOption(" in content and "api/create_exam" in content: return "templates/teacher/exam_editor.html"
    if "Add Student to Cohort" in content or "Members of Group" in content: return "templates/teacher/group.html"
    
    if "Available Exams" in content and "Completed Sessions" in content: return "templates/student/dashboard.html"
    if "Finish Attempt" in content and "captureVideoFrame" in content: return "templates/student/exam_take.html"
    if "Score Anatomy" in content or ("Exam Analysis" in content): return "templates/student/exam_analysis.html"
    
    # CSS
    if "--primary-color" in content and "glass-card" in content: return "static/style.css"
    
    return None

for b_path, mtime in blob_info:
    try:
        with open(b_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        filename = identify_content(content)
        if filename and filename not in recovered_files:
            # We found the latest version of this file!
            os.makedirs(os.path.dirname(filename), exist_ok=True) if os.path.dirname(filename) else None
            with open(filename, 'w', encoding='utf-8') as out_f:
                out_f.write(content)
            recovered_files.add(filename)
            print(f"Recovered {filename}")
    except Exception as e:
        # ignore non-utf8 files
        pass

print(f"Total recovered: {len(recovered_files)}")
