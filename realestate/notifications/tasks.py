# notifications/tasks.py
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from users.models import User 

@shared_task
def send_new_message_email(recipient_id, sender_id, message_content_preview):
    """
    Sends an email notification to an offline user about a new message.
    This task is dispatched by the ChatConsumer.
    """
    try:
        recipient = User.objects.select_related('profile').get(id=recipient_id)
        sender = User.objects.select_related('profile').get(id=sender_id)
    except User.DoesNotExist:
        # This happens if a user is deleted from the DB after a message is sent.
        print(f"User not found for email notification. Recipient ID: {recipient_id}, Sender ID: {sender_id}")
        return # Exit the task gracefully if a user is not found

    # For testing, you can see emails in your console by setting this in settings.py:
    # EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    subject = f"New message from {sender.profile.first_name} {sender.profile.last_name if hasattr(sender, 'profile') and sender.profile else ''}!"

    message = (
        f"Hello {recipient.profile.first_name if hasattr(recipient, 'profile') and recipient.profile else recipient.email},\n\n"
        f"You have a new message from {sender.profile.first_name if hasattr(sender, 'profile') and sender.profile else sender.email} in Aqari App:\n\n"
        f"'{message_content_preview}'\n\n"
        "Please log in to the app to view the full conversation.\n\n"
        "Thank you,\nYour Aqari App Team"
    )
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [recipient.email]

    try:
        send_mail(subject, message, from_email, recipient_list, fail_silently=False)
        print(f"Successfully dispatched new message email to {recipient.email} from {sender.email}")
    except Exception as e:
        print(f"Failed to send email to {recipient.email}: {e}")