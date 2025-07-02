
from django.db import models
from django.conf import settings # Needed for AUTH_USER_MODEL
from django.utils import timezone
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType 

class Notification(models.Model):
    # Recipient of the notification (the user who will see it)
    # Using settings.AUTH_USER_MODEL for best practice
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text="The user who receives this notification."
    )

    # Type of notification (for categorization and UI display)
    # Using an inner class for choices is a clean, best practice pattern
    class NotificationType(models.TextChoices):
        PROPERTY_STATUS = 'property_status', 'Property Status Change'
        PROPERTY_FAVORITED = 'property_favorited', 'Property Favorited'
        PROPERTY_PRICE_CHANGE = 'property_price_change', 'Property Price Change'
        PROPERTY_RATED = 'property_rated', 'Property Rated'
        # Add more types as your app grows
        # Example: NEW_INQUIRY = 'new_inquiry', 'New Property Inquiry'
        # Example: SYSTEM_ALERT = 'system_alert', 'System Alert'

    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        help_text="Category of the notification (e.g., property_status, property_favorited)."
    )

    # The actual message content
    message = models.TextField(
        help_text="The text content of the notification."
    )

    # Generic Foreign Key to link to any related object (e.g., a specific Property, or a User)
    # This is for the object the notification is *about*.
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True, blank=True,
        help_text="The content type of the related object (e.g., Property, User)."
    )
    object_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="The ID of the related object."
    )
    related_object = GenericForeignKey('content_type', 'object_id') # This creates the actual link

    # Status and timestamps
    is_read = models.BooleanField(default=False, help_text="True if the notification has been read by the recipient.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when the notification was created.")

    class Meta:
        ordering = ['-created_at'] # Order by newest first
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        # Display recipient email and a snippet of the message
        return f"{self.recipient.email} - {self.get_notification_type_display()} - {self.message[:50]}..."

    def mark_as_read(self):
        """Marks the notification as read."""
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])