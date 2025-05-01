import random
from django.utils.timezone import now
from django.core.mail import send_mail
from django.conf import settings
from .models import VerificationCode
from django.utils.timezone import now, timedelta
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

def validate_user_email(email):
    try:
        # Validate the email format
        validate_email(email)
        
        # Check if the email ends with '@gmail.com'
        if not email.lower().endswith('@gmail.com'):
            raise ValidationError("Only Gmail addresses are allowed.")
        
        return True  # Email is valid and ends with @gmail.com
    except ValidationError as e:
        raise ValidationError(str(e))  # Raise the specific validation error
    
    
    
def send_verification_email(user, purpose):
    # Generate random 6-digit code
    one_hour_ago = now() - timedelta(hours=1)
    recent_requests = VerificationCode.objects.filter(
        user=user,
        purpose=purpose,
        created_at__gte=one_hour_ago
    ).count()

    if recent_requests >= 3:
        raise ValueError("Too many requests. Please try again later.")

    # Delete any existing verification codes for this user and purpose
    VerificationCode.objects.filter(user=user, purpose=purpose).delete()
    code = f'{random.randint(100000, 999999)}'
    expiry = now() + timedelta(minutes=15)

    # Save verification code in DB
    VerificationCode.objects.create(
        user=user,
        code=code,
        purpose=purpose,
        expiry=expiry,
        attempts=0,
        max_attempts=5  # You can change here per purpose if you want
    )

    # Send email
    subject = 'Verification Code'
    if purpose == 'activation':
        subject = 'Activate Your Account'
    elif purpose == 'password_reset':
        subject = 'Reset Your Password'

    message = f'Your verification code is {code}. It will expire in 15 minutes.'
    
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )



def send_password_change_notification(user):
    """
    Sends a plain text email notification to the user when their password is changed.
    """
    subject = "Your Password Has Been Changed"
    message = (
        f"Hello from RealEstate,\n\n"
        f"We noticed that your password has been changed. "
        f"If it wasn't you, please let us know and contact us.\n\n"
        f"Thank you,\n"
        f"RealEstate Team"
    )
    
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    