#!/usr/bin/env python
"""Safe SMTP diagnostic — never prints secrets."""
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "EuphoriaDJ.settings")
import django
django.setup()
from django.conf import settings
from django.core import mail

def diagnose():
    user = settings.EMAIL_HOST_USER or "(not set)"
    pw_set = bool(settings.EMAIL_HOST_PASSWORD)
    print("SMTP host:", settings.EMAIL_HOST)
    print("SMTP port:", settings.EMAIL_PORT)
    print("SMTP TLS:", settings.EMAIL_USE_TLS)
    print("Backend:", settings.EMAIL_BACKEND)
    print("EMAIL_HOST_USER:", user if user else "NOT CONFIGURED")
    print("EMAIL_HOST_PASSWORD configured?:", pw_set)
    print(".env file present?:", os.path.isfile(".env"))

    # Try connection only when user is configured
    if user and pw_set:
        try:
            # Use Django's SMTP connection to verify auth
            connection = mail.get_connection()
            connection.open()
            connection.close()
            print("SMTP AUTH: SUCCESS")
        except Exception as e:
            # Sanitize: only exception type and safe message
            msg = str(e)
            # Strip any accidental password leakage (defensive)
            msg = msg.replace(str(settings.EMAIL_HOST_PASSWORD or ""), "***")
            print("SMTP AUTH FAILED:", type(e).__name__, "-", msg[:200])
    else:
        print("SMTP AUTH SKIPPED: credentials missing from .env / env")

if __name__ == "__main__":
    diagnose()
