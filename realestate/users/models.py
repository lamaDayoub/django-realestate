from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import  AbstractBaseUser, BaseUserManager, PermissionsMixin
from realestate import settings
import uuid
from datetime import timedelta
from django.utils import timezone


def user_directory_path(instance,filename):
    return f'userphotoes/user_{instance.id}/{filename}'


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)



    
class User(AbstractUser):
    username = None  # Explicitly remove the username field
    email = models.EmailField(unique=True)
    password=models.CharField(max_length=20)
    points = models.IntegerField(default=500)
    is_seller = models.BooleanField(default=False)
    favorite_properties = models.ManyToManyField(
    'properties.Property',  # Reference to the Property model
    through='properties.FavoriteProperty',  # Use the intermediary table
    related_name='favorited_by',  # Reverse relation name
    blank=True  # Allow users to have no favorite properties
   )
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='custom_user_set',  # Unique related_name
        related_query_name='user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='custom_user_set',  # Unique related_name
        related_query_name='user',
    )

    USERNAME_FIELD = 'email'  # Use email as the unique identifier
    REQUIRED_FIELDS = []  # No additional required fields

    objects = UserManager()

    def __str__(self):
        return self.email

class Profile(models.Model):
    GENDER_CHOICES = (
        ('M', 'Male'),
        ('F', 'Female'),
    )
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    
    first_name=models.CharField( max_length=100, blank=True, null=True)
    last_name=models.CharField(max_length=100, blank=True, null=True)
    photo=models.ImageField( upload_to=user_directory_path, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)  # Adjust max_length as needed
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
class VerificationCode(models.Model):
    PURPOSE_CHOICES = (
        ('activation', 'Activation'),
        ('password_reset', 'Password Reset'),
    )

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='verification_codes')
    code = models.CharField(max_length=6)  # Example: '123456'
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    expiry = models.DateTimeField()
    attempts = models.IntegerField(default=0)  # Track how many wrong tries
    max_attempts = models.IntegerField(default=5)  # You can change the limit if needed
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() > self.expiry

    def is_blocked(self):
        return self.attempts >= self.max_attempts

    def increase_attempts(self):
        self.attempts += 1
        self.save()

    def __str__(self):
        return f"{self.purpose} code for {self.user.email}"
    
class PasswordHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_histories")
    hashed_password = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return f"Password history for {self.user.email} at {self.created_at}"