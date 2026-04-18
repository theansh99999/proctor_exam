# 🎓 ExamProctor — AI-Powered Online Exam Platform

<p align="center">
  <strong>A full-stack online examination system with real-time AI proctoring, live analytics, and automated email notifications.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white" alt="SQLAlchemy">
  <img src="https://img.shields.io/badge/WebSocket-Enabled-brightgreen" alt="WebSocket">
  <img src="https://img.shields.io/badge/MediaPipe-Face%20Detection-FF6F00?logo=google&logoColor=white" alt="MediaPipe">
</p>

---

## ✨ Features Overview

### 👨‍🏫 Teacher Portal
| Feature | Description |
|---------|-------------|
| 📊 **Dashboard** | Live stats — active exams, student count, violation alerts |
| 📝 **Exam Builder** | Create exams with per-question marks, negative marking, and time limits |
| 👥 **Group Management** | Create student groups and bulk-assign exams |
| 📅 **Scheduling** | Set precise start/end times with automatic status transitions (Upcoming → Live → Ended) |
| 🔴 **Live Monitoring** | Real-time WebSocket panel showing student submissions and violation flags as they happen |
| 📈 **Analytics** | Pass/Fail pie charts, score distributions, per-student performance breakdown |
| 📤 **CSV Export** | Download full submission data for any exam |
| 🔔 **Notifications** | Bell dropdown with upcoming exam reminders and live cheat alerts |
| 👤 **Student Profiles** | View individual student history, answer sheets, and violation logs |

### 👨‍🎓 Student Portal
| Feature | Description |
|---------|-------------|
| 🏠 **Dashboard** | Live countdown timers for upcoming exams, score trajectory chart, pass/fail chart |
| 📝 **Smart Exam Taking** | AI-proctored exam with fullscreen enforcement and question palette |
| 🔒 **AI Proctoring** | MediaPipe face detection — flags no-face, multiple faces, head-turn, looking-down |
| 🎧 **Audio Monitoring** | Detects sustained background noise/talking during exam |
| ⚡ **Violation Tracking** | 5-strike system with auto-submit on max violations; each flagged in real-time to teacher |
| 📖 **Practice Mode** | Re-attempt any missed/completed exam in practice mode (results not saved) |
| 📊 **Performance Analysis** | Full answer sheet with correct/wrong highlighting, per-question marks breakdown |
| 📈 **Performance Dashboard** | See all assigned exams, scores, and cumulative analytics in one place |

### 📧 Email Notifications
- Automated HTML email sent to all students when a new exam is assigned
- Includes exam title, group, teacher name, start/end time, duration, and dashboard link
- Built with Python's built-in `smtplib` — **no extra packages required**
- Gracefully skips if not configured (no crashes)

---

## 🏗️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | FastAPI (Python 3.10+) |
| **Database** | PostgreSQL + SQLAlchemy ORM |
| **Auth** | JWT (via `python-jose`) + bcrypt password hashing |
| **Real-time** | WebSockets (`websockets` library) |
| **AI Proctoring** | MediaPipe Tasks Vision (browser-side, CDN) |
| **Frontend** | Jinja2 Templates + Bootstrap 5 + Chart.js |
| **Email** | Python `smtplib` (Gmail SMTP / TLS) |
| **Background Jobs** | FastAPI `BackgroundTasks` |

---

## 📁 Project Structure

```
exam proctor/
├── main.py                  # App entry point, router registration
├── models.py                # SQLAlchemy ORM models
├── database.py              # DB engine & session factory
├── auth.py                  # JWT auth, password hashing, dependency guards
├── schemas.py               # Pydantic request/response schemas
├── email_service.py         # Real Gmail SMTP email notification service
├── ws_manager.py            # WebSocket connection manager
├── requirements.txt
├── .env                     # Environment config (not committed)
│
├── routers/
│   ├── auth_r.py            # Login, register, logout routes
│   ├── teacher_r.py         # All teacher-facing routes & APIs
│   └── student_r.py         # All student-facing routes & APIs
│
├── templates/
│   ├── base.html            # Shared layout (navbar, theme toggle, notifications)
│   ├── teacher/             # Teacher page templates
│   └── student/             # Student page templates
│
├── static/
│   └── style.css            # Custom CSS (dark/light mode, glassmorphism)
│
└── testing/                 # Automated test suite (isolated SQLite in-memory DB)
    ├── test_runner.py
    ├── test_db.py
    ├── teacher/
    └── student/
```

---

## 🚀 Local Setup

### Prerequisites
- Python 3.10+
- PostgreSQL 14+
- Git

### 1. Clone the repository
```bash
git clone https://github.com/theansh99999/proctor_exam.git
cd proctor_exam
```

### 2. Create and activate virtual environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy the `.env` template and fill in your values:

```env
# Database
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/exam_proctor

# Security — generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=your-secure-random-key-minimum-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=120

# Email (Gmail SMTP) — optional, exam creation works without it
MAIL_USERNAME=your_gmail@gmail.com
MAIL_PASSWORD=your_16_char_app_password
MAIL_FROM=ExamProctor <your_gmail@gmail.com>
```

> **Gmail App Password:** Go to `myaccount.google.com → Security → 2-Step Verification → App Passwords` to generate a 16-character app password (your normal Gmail password will NOT work).

### 5. Create the database

```bash
# In PostgreSQL shell
CREATE DATABASE exam_proctor;
```

Tables are created automatically on first run via SQLAlchemy `create_all`.

### 6. Run the development server
```bash
fastapi dev main.py
```

App will be available at **http://127.0.0.1:8000**

---

## 🔐 Authentication Flow

1. **Teachers** register at `/register` (role = teacher)
2. **Students** are added by teachers (teacher enters student email while creating a group)
3. Students register at `/register` using the same email their teacher added
4. Login issues an `HttpOnly` cookie with a JWT access token
5. Token expires after 120 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

---

## 🤖 AI Proctoring Details

The proctoring system runs entirely **browser-side** using the [MediaPipe Tasks Vision](https://ai.google.dev/edge/mediapipe/solutions/vision/face_detector) WASM model (no server GPU required).

### Violation Types
| Violation | Trigger Delay | Description |
|-----------|--------------|-------------|
| No Face Detected | 3 seconds | Student left the frame |
| Multiple Faces | 2 seconds | Someone else in frame |
| Extreme Head Turn (Left/Right) | 1.5 seconds | Looking at another device |
| Moderate Look Away | 2 seconds | Consistently looking sideways |
| Looking Down | 2 seconds | Possibly reading notes |
| Tab Switch / Window Blur | Immediate | Switched to another app |
| Audio / Talking | 2.5 seconds | Sustained background noise |
| Fullscreen Exit | Immediate | Exited fullscreen mode |

### Strike System
- **5 violations** → exam auto-submits
- Each violation is logged to the database and broadcast live to the teacher via WebSocket
- Proctoring only activates **after** the student clicks "I Understand, Start Exam" — permission dialogs do not count as violations

---

## 🧪 Automated Testing

The project includes an isolated test suite using an **in-memory SQLite database** (does not touch production data).

```bash
# Run tests from terminal
python testing/test_runner.py
```

Tests cover:
- Teacher: Group creation, student management, exam creation
- Student: Dashboard data, exam flow

---

## 📊 Database Models

```
User ──────────────── GroupMember ──────── Group
 │                                            │
 │  (teacher)                              Exam
 │                                            │
 └──Submission ──────────── StudentAnswer     │
         │                                    │
     CheatFlag                           Question ── Option
```

---

## 🌐 Key Routes

### Auth
| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/login` | Login page |
| GET/POST | `/register` | Registration page |
| GET | `/logout` | Logout & clear cookie |

### Teacher (`/teacher/...`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Main teacher dashboard |
| POST | `/api/create_exam` | Create a new exam (JSON) |
| GET | `/exam/{id}/monitor` | Live exam monitoring |
| GET | `/exam/{id}/submissions` | Submission list with analytics |
| GET | `/student/{id}/profile` | Individual student profile |
| GET | `/export/{id}/csv` | Download exam results as CSV |

### Student (`/student/...`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Student dashboard |
| GET | `/take_exam/{id}` | Enter proctored exam |
| POST | `/submit_exam/{id}` | Submit exam answers |
| GET | `/my_report/{id}` | Detailed answer sheet |
| GET | `/practice_exam/{id}` | Practice a missed exam |
| GET | `/performance` | Full performance history |
| GET | `/notifications` | Real-time JSON notifications (API) |
| POST | `/api/cheat_flag` | Log a proctoring violation (API) |

---

## 🤝 Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## 📄 License

This project is for educational purposes. Feel free to use, modify, and distribute.

---

<p align="center">Built with ❤️ using FastAPI + MediaPipe By Ansh Kumar Rai</p>
