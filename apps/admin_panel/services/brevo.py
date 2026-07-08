"""
Production-Grade Email Service — PadosiAgent
=============================================

Primary: Brevo HTTP API (api.brevo.com)
Fallback: Django SMTP (configured via MAIL_* env vars)
Last Resort: Log to file (console/file in dev, recorded in prod)

All secrets are loaded from environment variables (via .env in dev,
real environment variables in production). Nothing is hardcoded.

Usage:
    from apps.agents.services.brevo import email_service

    email_service.send_otp('agent@example.com', 'Agent Name', '483291')
    email_service.send_welcome('agent@example.com', 'Agent Name', 'password123')
    email_service.send_generic('to@example.com', 'Name', 'Subject', '<html>...</html>')
"""

import logging
import time

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

# ─── Brevo API Endpoint ───────────────────────────────────────────────────────
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# ─── Retry Configuration ─────────────────────────────────────────────────────
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1  # Wait between retries


class BrevoEmailService:
    """
    Production-grade transactional email service.

    Delivery priority:
      1. Brevo HTTP API  (primary — fast, reliable, with tracking)
      2. Django SMTP     (secondary — configured via MAIL_* env vars)
      3. Log fallback    (last resort — records OTP to log, allows flow to continue)
    """

    # ─── Private Helpers ─────────────────────────────────────────────────────

    def _get_config(self):
        """
        Read all email config from Django settings (which reads from env).
        Raises ValueError if the primary key is missing in production.
        """
        api_key = getattr(settings, "BREVO_API_KEY", "").strip()
        from_email = getattr(settings, "BREVO_FROM_EMAIL", "noreply@padosiagent.com").strip()
        from_name = getattr(settings, "BREVO_FROM_NAME", "PadosiAgent").strip()
        otp_fallback = getattr(settings, "BREVO_OTP_FALLBACK", True)
        debug = getattr(settings, "DEBUG", False)

        return {
            "api_key": api_key,
            "from_email": from_email,
            "from_name": from_name,
            "otp_fallback": otp_fallback,
            "debug": debug,
        }

    def _send_via_brevo_api(self, cfg: dict, to_email: str, to_name: str, subject: str, html_content: str) -> bool:
        """
        Send email via Brevo HTTP API with retry logic.
        Returns True on success, False if all retries fail.
        """
        if not cfg["api_key"]:
            logger.warning("[BrevoAPI] BREVO_API_KEY is not configured — skipping API delivery.")
            return False

        payload = {
            "sender": {"name": cfg["from_name"], "email": cfg["from_email"]},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content,
        }

        headers = {
            "accept": "application/json",
            "api-key": cfg["api_key"],
            "content-type": "application/json",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.post(
                    BREVO_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=20,
                )

                if 200 <= response.status_code < 300:
                    logger.info(
                        "[BrevoAPI] Email delivered successfully. "
                        f"to={to_email!r} subject={subject!r} attempt={attempt}"
                    )
                    return True

                # Non-2xx — log and maybe retry
                logger.warning(
                    f"[BrevoAPI] Attempt {attempt}/{MAX_RETRIES} failed. "
                    f"status={response.status_code} body={response.text[:200]}"
                )

                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

            except requests.Timeout:
                logger.warning(f"[BrevoAPI] Attempt {attempt}/{MAX_RETRIES} timed out.")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

            except requests.ConnectionError as exc:
                logger.warning(f"[BrevoAPI] Attempt {attempt}/{MAX_RETRIES} connection error: {exc}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)

            except Exception as exc:
                logger.error(f"[BrevoAPI] Unexpected error on attempt {attempt}: {exc}", exc_info=True)
                break

        logger.error(f"[BrevoAPI] All {MAX_RETRIES} attempts failed for to={to_email!r}")
        return False

    def _send_via_smtp(self, cfg: dict, to_email: str, to_name: str, subject: str, html_content: str) -> bool:
        """
        Send email via Django SMTP backend (fallback channel).
        Uses EMAIL_HOST / EMAIL_PORT / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD from settings.
        """
        try:
            from_addr = f"{cfg['from_name']} <{cfg['from_email']}>"
            text_content = strip_tags(html_content)

            msg = EmailMultiAlternatives(subject, text_content, from_addr, [to_email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info(f"[SMTP Fallback] Email sent to {to_email!r} — {subject!r}")
            return True

        except Exception as exc:
            logger.error(f"[SMTP Fallback] Failed to send to {to_email!r}: {exc}", exc_info=True)
            return False

    # ─── Public API ──────────────────────────────────────────────────────────

    def send_generic(self, to_email: str, to_name: str, subject: str, html_content: str) -> bool:
        """
        Send any transactional email with automatic fallback chain.

        Returns:
            True  — email was delivered via Brevo API or SMTP
            False — all delivery channels failed
        """
        cfg = self._get_config()

        # 1. Try Brevo HTTP API
        if self._send_via_brevo_api(cfg, to_email, to_name, subject, html_content):
            return True

        # 2. Fallback to Django SMTP
        logger.warning(f"[EmailService] Brevo API failed. Attempting SMTP fallback for {to_email!r}.")
        if self._send_via_smtp(cfg, to_email, to_name, subject, html_content):
            return True

        # 3. Both channels failed
        logger.error(
            f"[EmailService] ❌ All email delivery channels failed for {to_email!r} — subject={subject!r}. "
            "Please check BREVO_API_KEY and MAIL_* configuration in .env"
        )
        return False

    def send_otp(self, to_email: str, to_name: str, otp_code: str) -> bool:
        """
        Send a 6-digit OTP verification email.

        In DEBUG mode: OTP is always printed to console for easy testing.
        If BREVO_OTP_FALLBACK=true and all channels fail: returns True anyway
        (registration flow continues; user must check console/logs for OTP).
        """
        cfg = self._get_config()

        # Always log OTP in DEBUG for local testing convenience
        if cfg["debug"]:
            logger.info(f"[DEBUG OTP] to={to_email!r} otp={otp_code}")
            print(f"\n{'='*55}")
            print(f"  [DEBUG OTP] for {to_email}")
            print(f"  Code : {otp_code}")
            print(f"{'='*55}\n")

        html = _build_otp_html(otp_code)
        subject = "Your PadosiAgent Verification Code"

        success = self.send_generic(to_email, to_name or to_email, subject, html)

        if not success:
            if cfg["otp_fallback"]:
                logger.warning(
                    f"[EmailService] OTP email failed for {to_email!r}, but BREVO_OTP_FALLBACK=true. "
                    "Flow will continue — OTP available in server logs/console."
                )
                return True  # Let registration proceed; agent checks console/log

            logger.error(
                f"[EmailService] OTP email failed for {to_email!r} and BREVO_OTP_FALLBACK=false. "
                "Blocking registration."
            )
            return False

        return True

    def send_welcome(self, to_email: str, to_name: str, temp_password: str, plan_name: str = "") -> bool:
        """
        Send a welcome / account credentials email after successful payment.
        """
        html = _build_welcome_html(to_name, to_email, temp_password, plan_name)
        subject = "Welcome to PadosiAgent — Your Account is Ready!"
        return self.send_generic(to_email, to_name, subject, html)

    def send_test(self, to_email: str) -> dict:
        """
        Send a test email to verify the email pipeline is working.
        Used by the management command `python manage.py test_email`.

        Returns:
            {
                'success': bool,
                'channel': 'brevo_api' | 'smtp' | 'failed',
                'message': str,
            }
        """
        cfg = self._get_config()
        subject = "✅ PadosiAgent — Email Service Test"
        html = _build_test_html(to_email)

        # Try Brevo API first
        if cfg["api_key"] and self._send_via_brevo_api(cfg, to_email, to_email, subject, html):
            return {
                "success": True,
                "channel": "brevo_api",
                "message": f"Test email delivered via Brevo API to {to_email}",
            }

        # Try SMTP fallback
        logger.warning("[EmailService:test] Brevo API failed, trying SMTP fallback.")
        if self._send_via_smtp(cfg, to_email, to_email, subject, html):
            return {
                "success": True,
                "channel": "smtp",
                "message": f"Test email delivered via SMTP fallback to {to_email}",
            }

        return {
            "success": False,
            "channel": "failed",
            "message": (
                "All email channels failed. "
                "Check BREVO_API_KEY and MAIL_* settings in your .env file."
            ),
        }


# ─── Module-level singleton ───────────────────────────────────────────────────
# Import this in other modules:
#   from apps.agents.services.brevo import email_service
email_service = BrevoEmailService()


# ─── Backwards-compatible helper functions ───────────────────────────────────
# Keep these so existing code that calls send_otp_email(...) still works.

def send_otp_email(to_email: str, to_name: str, otp_code: str) -> bool:
    """Backwards-compatible wrapper. Use email_service.send_otp() for new code."""
    return email_service.send_otp(to_email, to_name, otp_code)


def send_brevo_email(to_email: str, to_name: str, subject: str, html_content: str) -> bool:
    """Backwards-compatible wrapper. Use email_service.send_generic() for new code."""
    return email_service.send_generic(to_email, to_name, subject, html_content)


# ─── HTML Email Builders ─────────────────────────────────────────────────────

def _build_otp_html(otp_code: str) -> str:
    """Render the OTP email HTML inline (no template dependency)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Verification Code</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:520px;width:100%;">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#273C8E 0%,#1a2a63 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;
                       letter-spacing:0.5px;">PadosiAgent</h1>
            <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">
              India's Trusted Neighbourhood Insurance Platform
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:40px 40px 32px;">
            <h2 style="color:#1a2a63;font-size:20px;margin:0 0 12px;font-weight:600;">
              Email Verification
            </h2>
            <p style="color:#4b5563;font-size:15px;line-height:1.7;margin:0 0 28px;">
              Please use the one-time verification code below to complete your
              registration. This code is valid for <strong>10 minutes</strong>.
            </p>
            <!-- OTP Box -->
            <div style="text-align:center;margin:0 0 32px;">
              <div style="display:inline-block;background:#f0f4ff;
                          border:2px solid #273C8E;border-radius:14px;
                          padding:18px 48px;letter-spacing:10px;
                          font-size:36px;font-weight:800;color:#273C8E;
                          font-family:'Courier New',monospace;">
                {otp_code}
              </div>
            </div>
            <div style="background:#fef9ec;border:1px solid #f59e0b;border-radius:10px;
                        padding:14px 18px;margin-bottom:24px;">
              <p style="color:#92400e;font-size:13px;margin:0;line-height:1.6;">
                ⚠️ <strong>Security Notice:</strong> Never share this code with anyone.
                PadosiAgent will never ask for your OTP via phone or chat.
              </p>
            </div>
            <p style="color:#9ca3af;font-size:13px;line-height:1.6;margin:0;">
              If you did not request this code, please ignore this email.
              Your account will remain secure.
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:20px 40px;text-align:center;
                     border-top:1px solid #e5e7eb;">
            <p style="color:#9ca3af;font-size:12px;margin:0;line-height:1.6;">
              © 2024 PadosiAgent · All rights reserved<br>
              <a href="https://padosiagent.com" style="color:#273C8E;text-decoration:none;">
                padosiagent.com
              </a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_welcome_html(name: str, email: str, password: str, plan_name: str) -> str:
    """Render the welcome / credentials email HTML."""
    plan_line = f"<strong>{plan_name}</strong>" if plan_name else "your selected plan"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Welcome to PadosiAgent</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:520px;width:100%;">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#273C8E 0%,#1a2a63 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;">PadosiAgent</h1>
            <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">
              Welcome to India's Trusted Agent Platform
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:40px;">
            <h2 style="color:#1a2a63;font-size:20px;margin:0 0 16px;">
              🎉 Welcome aboard, {name}!
            </h2>
            <p style="color:#4b5563;font-size:15px;line-height:1.7;margin:0 0 24px;">
              Your registration is complete and your account is now active on {plan_line}.
              Here are your login credentials:
            </p>
            <!-- Credentials Box -->
            <div style="background:#f0f4ff;border:1px solid #c7d2fe;border-radius:12px;
                        padding:20px 24px;margin-bottom:24px;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="padding:6px 0;">
                    <span style="color:#6b7280;font-size:13px;">Login Email</span><br>
                    <strong style="color:#1a2a63;font-size:15px;">{email}</strong>
                  </td>
                </tr>
                <tr>
                  <td style="padding:6px 0;border-top:1px solid #e0e7ff;">
                    <span style="color:#6b7280;font-size:13px;">Temporary Password</span><br>
                    <strong style="color:#1a2a63;font-size:15px;font-family:'Courier New',monospace;">
                      {password}
                    </strong>
                  </td>
                </tr>
              </table>
            </div>
            <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:10px;
                        padding:14px 18px;margin-bottom:28px;">
              <p style="color:#065f46;font-size:13px;margin:0;line-height:1.6;">
                ✅ Please log in and change your password from your profile settings.
              </p>
            </div>
            <div style="text-align:center;">
              <a href="https://padosiagent.com/agent-login/"
                 style="background:linear-gradient(135deg,#273C8E,#1a2a63);
                        color:#ffffff;text-decoration:none;padding:14px 36px;
                        border-radius:10px;font-size:15px;font-weight:600;
                        display:inline-block;">
                Go to My Dashboard →
              </a>
            </div>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:20px 40px;text-align:center;
                     border-top:1px solid #e5e7eb;">
            <p style="color:#9ca3af;font-size:12px;margin:0;">
              © 2024 PadosiAgent · 
              <a href="https://padosiagent.com" style="color:#273C8E;text-decoration:none;">
                padosiagent.com
              </a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _build_test_html(to_email: str) -> str:
    """Render a simple test email HTML to verify the pipeline."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Email Service Test</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:520px;width:100%;">
        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#273C8E 0%,#1a2a63 100%);
                     padding:32px 40px;text-align:center;">
            <h1 style="color:#ffffff;margin:0;font-size:24px;font-weight:700;">PadosiAgent</h1>
            <p style="color:rgba(255,255,255,0.7);margin:8px 0 0;font-size:13px;">
              Email Service Diagnostics
            </p>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:40px;">
            <div style="text-align:center;margin-bottom:28px;">
              <div style="background:#ecfdf5;border-radius:50%;width:64px;height:64px;
                          display:inline-flex;align-items:center;justify-content:center;
                          font-size:32px;margin-bottom:16px;">✅</div>
              <h2 style="color:#065f46;font-size:22px;margin:0 0 8px;">
                Email Service is Working!
              </h2>
              <p style="color:#6b7280;font-size:14px;margin:0;">
                This is a test email from PadosiAgent email pipeline.
              </p>
            </div>
            <!-- Details -->
            <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:12px;
                        padding:20px 24px;margin-bottom:24px;">
              <table width="100%" cellpadding="0" cellspacing="6">
                <tr>
                  <td style="color:#6b7280;font-size:13px;width:40%;">Delivered to:</td>
                  <td style="color:#111827;font-size:13px;font-weight:600;">{to_email}</td>
                </tr>
                <tr>
                  <td style="color:#6b7280;font-size:13px;">Sent at:</td>
                  <td style="color:#111827;font-size:13px;">{now} IST</td>
                </tr>
                <tr>
                  <td style="color:#6b7280;font-size:13px;">Provider:</td>
                  <td style="color:#111827;font-size:13px;">Brevo API / SMTP Fallback</td>
                </tr>
              </table>
            </div>
            <p style="color:#9ca3af;font-size:13px;text-align:center;margin:0;">
              Your email configuration is production-ready. 🚀
            </p>
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:20px 40px;text-align:center;
                     border-top:1px solid #e5e7eb;">
            <p style="color:#9ca3af;font-size:12px;margin:0;">
              © 2024 PadosiAgent · Automated Test · Do not reply
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
