"""
modules/notifications/templates/renderer.py
-------------------------------------------
Reusable HTML & plain text template renderer for all assessment & communication events.
"""
from typing import Dict, Any, Tuple


def _base_email_html(title: str, subtitle: str, body_content: str, action_url: str = "", action_label: str = "View in Dashboard") -> str:
    action_btn = ""
    if action_url:
        action_btn = f"""
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px;">
          <tr>
            <td align="center">
              <a href="{action_url}"
                 style="display:inline-block;background:linear-gradient(135deg,#4f46e5,#7c3aed);color:#ffffff;
                        text-decoration:none;font-size:15px;font-weight:700;padding:12px 32px;
                        border-radius:8px;letter-spacing:0.3px;">
                {action_label} →
              </a>
            </td>
          </tr>
        </table>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 36px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;">{title}</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.85);font-size:13px;">{subtitle}</p>
          </td>
        </tr>
        <!-- Content -->
        <tr>
          <td style="padding:32px 36px;color:#374151;font-size:15px;line-height:1.6;">
            {body_content}
            {action_btn}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:16px 36px;border-top:1px solid #e5e7eb;text-align:center;">
            <p style="margin:0;color:#9ca3af;font-size:12px;">
              ExamProctor Assessment Platform • Automated Notification
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def render_event_content(
    event_type: str,
    recipient_name: str,
    params: Dict[str, Any]
) -> Tuple[str, str, str]:
    """
    Renders (subject/title, message_text, html_content) for a given notification event type.
    """
    exam_title = params.get("exam_title", "Assessment")
    action_url = params.get("action_url", "/dashboard")

    if event_type == "assessment_published":
        title = f"📢 Assessment Published: {exam_title}"
        msg = f"Assessment '{exam_title}' has been published and is now available in your catalog."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>The assessment <strong>{exam_title}</strong> has been published and is now active on the platform.</p>
        <p>Review requirements and instructions before participating.</p>"""

    elif event_type == "assessment_scheduled":
        start_time = params.get("start_time", "Scheduled time")
        end_time = params.get("end_time", "")
        title = f"📅 Assessment Scheduled: {exam_title}"
        msg = f"Assessment '{exam_title}' is scheduled for {start_time}."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Your assessment <strong>{exam_title}</strong> is scheduled:</p>
        <ul>
          <li><strong>Start Time:</strong> {start_time}</li>
          {f'<li><strong>End Time:</strong> {end_time}</li>' if end_time else ''}
        </ul>"""

    elif event_type == "assignment_created":
        title = f"📋 New Assessment Assigned: {exam_title}"
        msg = f"You have been assigned to assessment '{exam_title}'. Please review the schedule and requirements."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>You have been assigned to complete <strong>{exam_title}</strong>.</p>
        <p>Please check your dashboard for scheduling details and instructions.</p>"""

    elif event_type == "assessment_rescheduled":
        start_time = params.get("start_time", "New time")
        title = f"🕒 Schedule Updated: {exam_title}"
        msg = f"The schedule for '{exam_title}' has been updated to {start_time}."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Please note that the schedule for <strong>{exam_title}</strong> has changed.</p>
        <p><strong>New Start Time:</strong> {start_time}</p>"""

    elif event_type == "assessment_cancelled":
        title = f"❌ Assessment Cancelled: {exam_title}"
        msg = f"Assessment '{exam_title}' has been cancelled by the examiner."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Assessment <strong>{exam_title}</strong> has been cancelled. No action is required on your part.</p>"""

    elif event_type == "assessment_approaching_start":
        title = f"⚡ Assessment Starting Soon: {exam_title}"
        msg = f"Assessment '{exam_title}' will begin shortly. Please prepare your workstation."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p><strong>{exam_title}</strong> is starting soon. Make sure your camera, microphone, and browser are ready.</p>"""

    elif event_type == "assessment_reminder_24h":
        title = f"⏰ 24-Hour Reminder: {exam_title}"
        msg = f"Reminder: Assessment '{exam_title}' starts in 24 hours."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>This is a reminder that <strong>{exam_title}</strong> is scheduled to begin in 24 hours.</p>"""

    elif event_type == "assessment_reminder_1h":
        title = f"🚨 1-Hour Reminder: {exam_title}"
        msg = f"Final Reminder: Assessment '{exam_title}' begins in 1 hour."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p><strong>{exam_title}</strong> begins in 1 hour. Please log in early to complete proctoring checks.</p>"""

    elif event_type == "assessment_submitted":
        title = f"✅ Assessment Submitted: {exam_title}"
        msg = f"Your responses for '{exam_title}' have been successfully received and submitted."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Your submission for <strong>{exam_title}</strong> has been received and recorded.</p>"""

    elif event_type == "assessment_auto_submitted":
        title = f"⏱️ Assessment Auto-Submitted: {exam_title}"
        msg = f"Your session for '{exam_title}' reached its deadline and was automatically submitted."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Your session for <strong>{exam_title}</strong> reached its allotted deadline and was safely auto-submitted.</p>"""

    elif event_type == "assessment_expired":
        title = f"⌛ Assessment Session Expired: {exam_title}"
        msg = f"Your session for '{exam_title}' has expired."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Your assessment session for <strong>{exam_title}</strong> has concluded.</p>"""

    elif event_type == "manual_grading_completed":
        title = f"📝 Manual Grading Completed: {exam_title}"
        msg = f"The examiner has completed evaluation for '{exam_title}'."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Manual grading for your responses on <strong>{exam_title}</strong> is complete.</p>"""

    elif event_type == "result_released":
        title = f"🎉 Results Released: {exam_title}"
        msg = f"Official results for '{exam_title}' are now available in your student portal."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>The results for <strong>{exam_title}</strong> have been released.</p>
        <p>Click below to view your score, breakdown, and performance analysis.</p>"""

    elif event_type == "result_revised":
        title = f"🔄 Result Revised: {exam_title}"
        msg = f"Your result for '{exam_title}' has been updated following examiner regrading."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>An examiner has reviewed and revised your score for <strong>{exam_title}</strong>.</p>"""

    elif event_type == "feedback_available":
        title = f"💬 Examiner Feedback Available: {exam_title}"
        msg = f"New examiner feedback is available for '{exam_title}'."
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <p>Your examiner has provided written feedback on your assessment answers for <strong>{exam_title}</strong>.</p>"""

    elif event_type == "announcement":
        ann_title = params.get("title", "Important Announcement")
        title = f"📣 Announcement: {ann_title}"
        content = params.get("content", "")
        msg = f"{ann_title}: {content}"
        body = f"""<p>Hello <strong>{recipient_name}</strong>,</p>
        <div style="background:#f8f7ff;border-left:4px solid #4f46e5;padding:16px 20px;margin:16px 0;border-radius:4px;">
          <h3 style="margin:0 0 8px;color:#4f46e5;">{ann_title}</h3>
          <p style="margin:0;color:#1f2937;">{content}</p>
        </div>"""

    else:
        title = params.get("title", "ExamProctor Notification")
        msg = params.get("message", "You have a new notification.")
        body = f"<p>Hello <strong>{recipient_name}</strong>,</p><p>{msg}</p>"

    html_content = _base_email_html(
        title=title,
        subtitle="ExamProctor Assessment Notification",
        body_content=body,
        action_url=action_url,
        action_label=params.get("action_label", "View in Portal")
    )

    return title, msg, html_content
