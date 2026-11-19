import logging
from django.conf import settings
from django.core.mail import EmailMessage

logger = logging.getLogger(__name__)

def custom_mail(title: str, message: str, reply_to=None, recipients=None):
    if recipients is None:
        recipients = []
    try:
        from_email = getattr(settings, 'EMAIL_HOST_USER', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'noreply@euphoria.com'
        msg = EmailMessage(
            subject=f'Euphoria Business : {title}',
            body=message,
            from_email=from_email,
            to=recipients,
            reply_to=[reply_to] if reply_to else None,
        )
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        logger.error("Welcome email failed: %s", type(e).__name__)
        return False
