"""
Management Command: test_email
==============================
Sends a test email to verify the Brevo API + SMTP fallback pipeline.

Usage:
    python manage.py test_email
    python manage.py test_email --to someone@example.com
    python manage.py test_email --type otp
    python manage.py test_email --type welcome

Options:
    --to      Recipient email address (default: ashisprajapati2131@gmail.com)
    --type    Email type to test: test | otp | welcome (default: test)
"""

from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Send a test email to verify the email service pipeline (Brevo API + SMTP fallback)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            type=str,
            default="ashisprajapati2131@gmail.com",
            help="Recipient email address (default: ashisprajapati2131@gmail.com)",
        )
        parser.add_argument(
            "--type",
            type=str,
            default="test",
            choices=["test", "otp", "welcome"],
            help="Type of email to send: test | otp | welcome (default: test)",
        )

    def handle(self, *args, **options):
        from apps.agents.services.brevo import email_service

        to_email = options["to"]
        email_type = options["type"]

        # ─── Print config summary ────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.HTTP_INFO("  [*] PadosiAgent Email Service Test"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Recipient  : {to_email}")
        self.stdout.write(f"  Email Type : {email_type}")
        self.stdout.write(f"  DEBUG      : {settings.DEBUG}")
        brevo_status = ('[OK] Set (' + settings.BREVO_API_KEY[:12] + '...)') if settings.BREVO_API_KEY else '[!!] NOT SET'
        self.stdout.write(f"  Brevo Key  : {brevo_status}")
        self.stdout.write(f"  From Email : {settings.BREVO_FROM_EMAIL}")
        self.stdout.write(f"  SMTP Host  : {settings.EMAIL_HOST}:{settings.EMAIL_PORT}")
        smtp_user = ('[OK] ' + settings.EMAIL_HOST_USER) if settings.EMAIL_HOST_USER else '[--] Not configured (SMTP fallback unavailable)'
        self.stdout.write(f"  SMTP User  : {smtp_user}")
        self.stdout.write(f"  OTP Fallbk : {'[ON]' if settings.BREVO_OTP_FALLBACK else '[OFF]'}")
        self.stdout.write("=" * 60 + "\n")

        # ─── Send based on type ──────────────────────────────────────────────
        if email_type == "test":
            self.stdout.write("Sending test email via Brevo API...")
            result = email_service.send_test(to_email)

            if result["success"]:
                channel = result["channel"]
                channel_label = "Brevo HTTP API" if channel == "brevo_api" else "SMTP Fallback"
                self.stdout.write(self.style.SUCCESS(
                    f"\n[SUCCESS] Delivered via [{channel_label}]\n"
                    f"   {result['message']}\n"
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n[FAILED] {result['message']}\n"
                    f"\nTroubleshooting:\n"
                    f"  1. Check BREVO_API_KEY in .env\n"
                    f"  2. Check MAIL_USERNAME / MAIL_PASSWORD for SMTP fallback\n"
                    f"  3. Ensure BREVO_FROM_EMAIL is a verified sender in Brevo dashboard\n"
                ))

        elif email_type == "otp":
            otp_code = "483291"  # Fixed test OTP
            self.stdout.write(f"Sending OTP email (code: {otp_code}) to {to_email}...")
            success = email_service.send_otp(to_email, "Test User", otp_code)

            if success:
                self.stdout.write(self.style.SUCCESS(
                    f"\n[SUCCESS] OTP email sent successfully to {to_email}!\n"
                    f"   Test OTP code: {otp_code}\n"
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n[FAILED] OTP email failed! Check logs above for details.\n"
                ))

        elif email_type == "welcome":
            self.stdout.write(f"Sending welcome email to {to_email}...")
            success = email_service.send_welcome(
                to_email=to_email,
                to_name="Test Agent",
                temp_password="TempPass@123",
                plan_name="Starter's Plan",
            )

            if success:
                self.stdout.write(self.style.SUCCESS(
                    f"\n[SUCCESS] Welcome email sent successfully to {to_email}!\n"
                ))
            else:
                self.stdout.write(self.style.ERROR(
                    f"\n[FAILED] Welcome email failed! Check logs above for details.\n"
                ))

        self.stdout.write("=" * 60 + "\n")
