"""
Email Notification Service
--------------------------
Uses Python's built-in smtplib (no extra pip install needed).
Configured via .env:
    MAIL_USERNAME — Gmail address
    MAIL_PASSWORD — Gmail App Password (16-char, not your normal password)
    MAIL_FROM     — Sender display string, e.g. "ExamProctor <you@gmail.com>"
"""

import smtplib
import os
import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587  # TLS port

MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_FROM     = os.getenv("MAIL_FROM", MAIL_USERNAME)

_EMAIL_ENABLED = bool(MAIL_USERNAME and MAIL_PASSWORD and
                      not MAIL_USERNAME.startswith("your_"))


# ── Core send function ─────────────────────────────────────────────────────────
def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """
    Send a single HTML email via Gmail SMTP.
    Returns True on success, False on failure (never raises).
    """
    if not _EMAIL_ENABLED:
        print(f"[EMAIL] ⚠️  MAIL_USERNAME/PASSWORD not configured. Skipping email to {to_address}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = MAIL_FROM
        msg["To"]      = to_address

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, to_address, msg.as_string())

        print(f"[EMAIL] ✅ Sent to {to_address} — {subject}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("[EMAIL] ❌ Authentication failed. Check MAIL_USERNAME and MAIL_PASSWORD in .env")
    except smtplib.SMTPException as e:
        print(f"[EMAIL] ❌ SMTP error sending to {to_address}: {e}")
    except Exception:
        print(f"[EMAIL] ❌ Unexpected error sending to {to_address}:")
        traceback.print_exc()

    return False


# ── Email Templates ────────────────────────────────────────────────────────────
def build_exam_assigned_html(
    student_email: str,
    exam_title: str,
    group_name: str,
    teacher_name: str,
    start_time: datetime,
    end_time: datetime,
    duration_minutes: int,
    dashboard_url: str = "http://localhost:8000/student/dashboard",
) -> str:
    start_str = start_time.strftime("%A, %B %d %Y at %I:%M %p")
    end_str   = end_time.strftime("%I:%M %p")

    return f"""
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:36px 40px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:700;letter-spacing:-0.5px;">📋 New Exam Assigned</h1>
            <p style="margin:8px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">You have been assigned a new exam</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 40px;">
            <p style="margin:0 0 24px;color:#374151;font-size:15px;">Hi there 👋,</p>
            <p style="margin:0 0 24px;color:#374151;font-size:15px;">
              <strong style="color:#1f2937;">{teacher_name}</strong> has assigned you a new exam in
              <strong style="color:#1f2937;">{group_name}</strong>. Here are the details:
            </p>

            <!-- Exam Info Card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#f8f7ff;border:2px solid #e0e7ff;border-radius:10px;margin-bottom:28px;">
              <tr>
                <td style="padding:24px 28px;">
                  <h2 style="margin:0 0 16px;color:#4f46e5;font-size:20px;">{exam_title}</h2>
                  <table cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="padding:5px 0;color:#6b7280;font-size:14px;width:130px;">📅 Start Time</td>
                      <td style="padding:5px 0;color:#1f2937;font-size:14px;font-weight:600;">{start_str}</td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#6b7280;font-size:14px;">🔚 End Time</td>
                      <td style="padding:5px 0;color:#1f2937;font-size:14px;font-weight:600;">{end_str}</td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#6b7280;font-size:14px;">⏱️ Duration</td>
                      <td style="padding:5px 0;color:#1f2937;font-size:14px;font-weight:600;">{duration_minutes} minutes</td>
                    </tr>
                    <tr>
                      <td style="padding:5px 0;color:#6b7280;font-size:14px;">🏫 Group</td>
                      <td style="padding:5px 0;color:#1f2937;font-size:14px;font-weight:600;">{group_name}</td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- CTA Button -->
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td align="center" style="padding:8px 0 28px;">
                  <a href="{dashboard_url}"
                     style="display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#ffffff;
                            text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;
                            border-radius:8px;letter-spacing:0.3px;">
                    Go to Dashboard →
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:0;color:#9ca3af;font-size:13px;">
              Make sure you're ready before the exam starts. Good luck! 🍀
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:20px 40px;border-top:1px solid #e5e7eb;text-align:center;">
            <p style="margin:0;color:#9ca3af;font-size:12px;">
              This is an automated notification from <strong>ExamProctor</strong>.<br>
              Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""


# ── High-level task (called by BackgroundTasks) ────────────────────────────────
def notify_students_exam_assigned(
    group_members: list,
    exam_title: str,
    group_name: str,
    teacher_name: str,
    start_time: datetime,
    end_time: datetime,
    duration_minutes: int,
    dashboard_url: str = "http://localhost:8000/student/dashboard",
) -> None:
    """
    Sends exam-assignment emails to all group members.
    Designed to run in a FastAPI BackgroundTask — failures are logged, not raised.
    """
    success_count = 0
    for member in group_members:
        html = build_exam_assigned_html(
            student_email=member.student_email,
            exam_title=exam_title,
            group_name=group_name,
            teacher_name=teacher_name,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            dashboard_url=dashboard_url,
        )
        if send_email(
            to_address=member.student_email,
            subject=f"📋 New Exam Assigned: {exam_title}",
            html_body=html,
        ):
            success_count += 1

    total = len(group_members)
    print(f"[EMAIL] 📊 Exam notification: {success_count}/{total} emails sent for '{exam_title}'")
