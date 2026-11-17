"""
modules/notifications/channels/email.py
--------------------------------------
Email notification channel with SMTP transport, retries, and credential protection.
"""
from typing import Optional, Dict, Any
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from time_utils import utc_now
from modules.notifications.channels.base import BaseNotificationChannel, DeliveryResult


class EmailNotificationChannel(BaseNotificationChannel):
    """Channel that sends HTML and plain-text emails via SMTP."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        mail_from: Optional[str] = None,
        max_retries: int = 3,
        retry_delay_seconds: float = 0.5
    ):
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(smtp_port or os.getenv("SMTP_PORT", 587))
        self.username = username or os.getenv("MAIL_USERNAME", "")
        self.password = password or os.getenv("MAIL_PASSWORD", "")
        self.mail_from = mail_from or os.getenv("MAIL_FROM", self.username or "ExamProctor <notifications@examproctor.local>")
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    @property
    def channel_name(self) -> str:
        return "email"

    @property
    def is_configured(self) -> bool:
        """Check if SMTP credentials are configured and not placeholder values."""
        return bool(self.username and self.password and not self.username.startswith("your_"))

    def deliver(
        self,
        recipient_id: int,
        recipient_email: Optional[str],
        recipient_name: str,
        title: str,
        message: str,
        html_content: Optional[str] = None,
        action_url: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None
    ) -> DeliveryResult:
        """Deliver email with retry logic on transient errors."""
        if not recipient_email or "@" not in recipient_email:
            return DeliveryResult(
                success=False,
                channel="email",
                recipient_id=recipient_id,
                error_message="Invalid or missing recipient email address.",
                retryable=False
            )

        # Allow tests to mock email sending or run in mock mode
        if os.getenv("MOCK_EMAIL", "").lower() in ("true", "1", "yes") or (event_metadata and event_metadata.get("mock_email")):
            return DeliveryResult(
                success=True,
                channel="email",
                recipient_id=recipient_id,
                delivered_at=utc_now()
            )

        if not self.is_configured:
            return DeliveryResult(
                success=False,
                channel="email",
                recipient_id=recipient_id,
                error_message="SMTP server credentials not configured. Email skipped.",
                retryable=False
            )

        # Prepare MIME message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"] = self.mail_from
        msg["To"] = recipient_email

        # Attach Plain-text part
        plain_text = f"Hello {recipient_name},\n\n{message}"
        if action_url:
            plain_text += f"\n\nView details: {action_url}"
        plain_text += "\n\n— ExamProctor Automated Notification"
        msg.attach(MIMEText(plain_text, "plain", "utf-8"))

        # Attach HTML part
        if html_content:
            msg.attach(MIMEText(html_content, "html", "utf-8"))
        else:
            fallback_html = f"<p>Hello <strong>{recipient_name}</strong>,</p><p>{message}</p>"
            if action_url:
                fallback_html += f"<p><a href='{action_url}'>View Details</a></p>"
            msg.attach(MIMEText(fallback_html, "html", "utf-8"))

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(self.username, self.password)
                    server.sendmail(self.username, recipient_email, msg.as_string())

                return DeliveryResult(
                    success=True,
                    channel="email",
                    recipient_id=recipient_id,
                    delivered_at=utc_now()
                )
            except (smtplib.SMTPAuthenticationError, smtplib.SMTPNotSupportedError) as auth_err:
                # Permanent error - do not retry
                return DeliveryResult(
                    success=False,
                    channel="email",
                    recipient_id=recipient_id,
                    error_message=f"SMTP Authentication failed: {str(auth_err)}",
                    retryable=False
                )
            except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError) as transient_err:
                last_error = f"SMTP attempt {attempt} failed: {str(transient_err)}"
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_seconds)
            except Exception as e:
                last_error = f"Unexpected email error: {str(e)}"
                break

        return DeliveryResult(
            success=False,
            channel="email",
            recipient_id=recipient_id,
            error_message=last_error or "SMTP delivery failed after retries.",
            retryable=True
        )
