import random
from rest_framework.response import Response
from django.utils.timezone import now
from django.core.mail import send_mail
from rest_framework import status
from django.conf import settings
from .models import VerificationCode
from django.utils.timezone import now, timedelta
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from random import randint
from django.contrib.auth import get_user_model
User = get_user_model()
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
    MAX_REQUESTS_PER_HOUR = 10
    CODE_EXPIRY_MINUTES = 15
    MAX_ATTEMPTS = 5

    # Define the time range for the last hour
    one_hour_ago = now() - timedelta(hours=1)

    # Get all codes created in the last hour for this user and purpose
    recent_requests = VerificationCode.objects.filter(
        user=user,
        purpose=purpose,
        created_at__gte=one_hour_ago
    )

    # Check if the user has exceeded the limit of 10 requests in the last hour
    if recent_requests.count() >= MAX_REQUESTS_PER_HOUR:
        raise ValueError("Too many requests. Please try again later.")

    # Delete codes that were created exactly one hour ago or earlier
    VerificationCode.objects.filter(
        user=user,
        purpose=purpose,
        created_at__lt=one_hour_ago
    ).delete()

    # Generate a random 6-digit code
    code = f'{randint(100000, 999999)}'
    expiry = now() + timedelta(minutes=CODE_EXPIRY_MINUTES)

    # Save the verification code in the database
    VerificationCode.objects.create(
        user=user,
        code=code,
        purpose=purpose,
        expiry=expiry,
        attempts=0,
        max_attempts=MAX_ATTEMPTS
    )

    # Prepare email content
    subject = 'Verification Code'
    if purpose == 'activation':
        subject = 'Activate Your Account'
    elif purpose == 'password_reset':
        subject = 'Reset Your Password'

    message = f'Your verification code is {code}. It will expire in {CODE_EXPIRY_MINUTES} minutes.'

    # Send the email
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
    
    
def verify_code(email, code, purpose):
    """
    Handles verification code validation (expiry, attempts, correctness).
    Returns:
        - (user, verification) on success
        - Response with error on failure
    """
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {"detail": "User not found."}, 
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        verification = VerificationCode.objects.filter(
            user=user, 
            purpose=purpose
        ).latest('created_at')
    except VerificationCode.DoesNotExist:
        return Response(
            {"detail": "No verification code found."}, 
            status=status.HTTP_404_NOT_FOUND
        )

    # Check expiry
    if verification.is_expired():
        return Response(
            {"detail": "Code expired. Please request a new code."}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check if blocked
    if verification.is_blocked():
        return Response(
            {"detail": "Too many wrong attempts. Please request a new code."}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check code
    if verification.code != code:
        verification.increase_attempts()
        tries_left = verification.max_attempts - verification.attempts
        return Response(
            {"detail": f"Invalid code. {tries_left} tries left."}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    return user, verification  # Success!