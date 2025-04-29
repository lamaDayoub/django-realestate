from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User
from .utils import send_verification_email  # Will create it
from django.contrib.auth import get_user_model

User = get_user_model()
@receiver(post_save, sender=User)
def send_activation_code(sender, instance, created, **kwargs):
    if created and not instance.is_active:
        
        send_verification_email(instance, purpose='activation')
