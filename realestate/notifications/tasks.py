# notifications/tasks.py
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model 
from django.template.loader import render_to_string 
from django.utils.html import strip_tags 
from asgiref.sync import async_to_sync 
from channels.layers import get_channel_layer 
from django.db.models import  Prefetch 
from .models import Notification 
from users.models import Profile 
from properties.models import Property 
# No import for chat.models.Message here, as chat is separate.

User = get_user_model()

@shared_task
def send_notification_email(notification_id):
    """
    Sends an email notification for a specific Notification object.
    This is dispatched when a user is offline for general notifications.
    """
    try:
        notification = Notification.objects.select_related('recipient__profile').get(pk=notification_id)
        recipient = notification.recipient
    except Notification.DoesNotExist:
        print(f"Notification with ID {notification_id} not found for email dispatch.")
        return

    # Prepare email context
    context = {
        'notification_message': notification.message,
        'recipient_name': recipient.profile.first_name if hasattr(recipient, 'profile') and recipient.profile and recipient.profile.first_name else recipient.email,
        'notification_type': notification.get_notification_type_display(),
        'created_at': notification.created_at,
        'property_name': None,
        'property_url': None,
        'sender_name': None, # For notifications related to another user (e.g., favorited by)
    }

    # Dynamically add context based on related object type (Property or User)
    if notification.related_object:
        if isinstance(notification.related_object, Property):
            property_obj = notification.related_object
            context['property_name'] = f"{property_obj.ptype} in {property_obj.city}"
            # context['property_url'] = f"{settings.DEFAULT_API_URL}properties/{property_obj.id}/"
        elif isinstance(notification.related_object, User):
            sender_user = notification.related_object
            context['sender_name'] = f"{sender_user.profile.first_name if hasattr(sender_user, 'profile') and sender_user.profile else sender_user.email}"
        # No Message-related context here, as chat is separate.

    # Render HTML and plain text versions of the email
    html_message = render_to_string('notifications/notification_email.html', context)
    plain_message = strip_tags(html_message)

    subject = f"New {notification.get_notification_type_display()} in Aqari App!"
    # No custom subject for chat messages here.

    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [recipient.email]

    try:
        send_mail(
            subject,
            plain_message,
            from_email,
            recipient_list,
            html_message=html_message,
            fail_silently=False
        )
        print(f"Successfully sent notification email to {recipient.email} (Type: {notification.notification_type}).")
    except Exception as e:
        print(f"Failed to send notification email to {recipient.email}: {e}")


     
@shared_task
def dispatch_notification_task(notification_id):
    try:
        notification = Notification.objects.select_related(
            'recipient__profile'
        ).get(pk=notification_id)

        recipient = notification.recipient
    except Notification.DoesNotExist:
        print(f"Notification with ID {notification_id} not found for dispatch.")
        return

    # ✅ You don’t need to reassign notification.related_object
    # Just handle it dynamically in the email task
    # or WebSocket serialization, like you already do.
    recipient.refresh_from_db() 
    print(f"DEBUG: Dispatch task: Recipient {recipient.email} is_online status: {recipient.is_online}")
    if recipient.is_online:
        # Real-time delivery via WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            from .serializers import NotificationSerializer
            serialized_notification_data = NotificationSerializer(notification).data

            async_to_sync(channel_layer.group_send)(
                f'user_{recipient.id}_notifications', 
                {
                    'type': 'notification.message', # This calls notification_message handler in consumer
                    'notification': serialized_notification_data
                }
            )
            print(f"DEBUG: Dispatched real-time notification to {recipient.email} (online).")

            # 2. Calculate and send the updated unread count
            # This ensures the badge updates instantly
            new_unread_count = Notification.objects.filter(recipient=recipient, is_read=False).count()
            async_to_sync(channel_layer.group_send)(
                f'user_{recipient.id}_notifications',
                {
                    'type': 'notification.unread_count_update', # This calls notification_unread_count_update handler
                    'count': new_unread_count
                }
            )
            print(f"DEBUG: Dispatched real-time unread count update ({new_unread_count}) to {recipient.email}.")

        else:
            print("WARNING: Channel layer not available for real-time notification dispatch. Falling back to email.")
            send_notification_email.delay(notification_id)
    else:
        # Offline delivery: Send email
        send_notification_email.delay(notification_id)
        print(f"Dispatched email notification for {recipient.email} (offline).")


@shared_task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')