
from django.db import models
from django.utils import timezone

from django.contrib.auth import get_user_model

User = get_user_model()

def upload_to_message_files(instance, filename):
    return f'messages/{instance.conversation.id}/{filename}'

class Conversation(models.Model):
    participant1 = models.ForeignKey(User, related_name='conversations_as_p1', on_delete=models.CASCADE)
    participant2 = models.ForeignKey(User, related_name='conversations_as_p2', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    activated_at = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Timestamp when the conversation was last activated/paid for."
    )
    expires_at = models.DateTimeField(
        null=True, 
        blank=True, 
        help_text="Timestamp when the conversation session expires."
    )


    def __str__(self):
        return f"Chat between {self.participant1.email} and {self.participant2.email} (ID: {self.id})"
    class Meta:
        unique_together = [['participant1', 'participant2']]
        ordering = ['-updated_at']

    def get_other_participant(self, user):
        return self.participant2 if user == self.participant1 else self.participant1
    
    
class Message(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'text', 'Text'
        PDF = 'pdf', 'PDF'
        IMAGE = 'image', 'Image'
    
    conversation = models.ForeignKey(Conversation, related_name='messages', on_delete=models.CASCADE)
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to=upload_to_message_files, null=True, blank=True)
    message_type = models.CharField(max_length=10, choices=MessageType.choices, default=MessageType.TEXT)
    created_at = models.DateTimeField(default=timezone.now)
    is_read = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.id:  # Only on creation
            self.created_at = timezone.now()
        super().save(*args, **kwargs)
    def __str__(self):
        msg_type = self.get_message_type_display()
        return f"{msg_type} message from {self.sender.email} at {self.created_at}"
    class Meta:
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['is_read']),
        ]
        ordering = ['created_at']

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=['is_read'])