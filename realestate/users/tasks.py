# users/tasks.py
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model

User = get_user_model()

@shared_task
def send_verification_email_task(user_id, purpose, code, expiry_minutes):
    """
    Celery task to send a verification email.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        print(f"User with ID {user_id} not found for verification email task.")
        return

    subject = 'Verification Code'
    if purpose == 'activation':
        subject = 'Activate Your Account'
    elif purpose == 'password_reset':
        subject = 'Reset Your Password'

    # You can enhance this with HTML templates later if needed
    message = f'Your verification code is {code}. It will expire in {expiry_minutes} minutes.'

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        print(f"Successfully dispatched verification email to {user.email} for {purpose}.")
    except Exception as e:
        print(f"Failed to send verification email to {user.email}: {e}")

@shared_task
def send_password_change_notification_task(user_id):
    """
    Celery task to send a password change notification email.
    """
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        print(f"User with ID {user_id} not found for password change notification task.")
        return

    subject = "Your Password Has Been Changed"
    message = (
        f"Hello from RealEstate,\n\n"
        f"We noticed that your password has been changed. "
        f"If it wasn't you, please let us know and contact us.\n\n"
        f"Thank you,\n"
        f"RealEstate Team"
    )
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        print(f"Successfully dispatched password change notification email to {user.email}.")
    except Exception as e:
        print(f"Failed to send password change notification email to {user.email}: {e}")