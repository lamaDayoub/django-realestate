# chat/serializers.py
import os 
import uuid

from rest_framework import serializers
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage

# Assuming these imports are correct for your project structure
from users.models import Profile 
from core.serializers.fields import DamascusDateTimeField 
from chat.models import Message, Conversation # Explicitly import models needed here

# Get the User model
User = get_user_model()

# --- Helper class for file uploads (used internally by serializer) ---
class UploadedFileRepresentation:
    """
    A simple class to hold the uploaded file's path and URL for internal use.
    This is what FileUploadSerializer.create will return.
    """
    def __init__(self, name):
        self.name = name # Relative path in MEDIA_ROOT, e.g., 'chat_uploads/abc.jpg'
        self.url = f"{settings.MEDIA_URL}{name}" # Absolute URL path relative to Django host, e.g., '/media/chat_uploads/abc.jpg'

# --- Serializer for File Uploads (HTTP API) ---
class FileUploadSerializer(serializers.Serializer):
    """
    Serializer for handling file uploads via HTTP POST (input only).
    Returns the absolute URL in its response.
    """
    file = serializers.FileField(required=True, help_text="The file (image or PDF) to upload.")

    def validate_file(self, value):
        """Validates the uploaded file's type and size."""
        allowed_types = ['image/jpeg', 'image/png', 'application/pdf']
        if value.content_type not in allowed_types:
            raise serializers.ValidationError("Only JPEG, PNG images, and PDF files are allowed.")

        max_size = 5 * 1024 * 1024 # 5MB limit
        if value.size > max_size:
            raise serializers.ValidationError("File size cannot exceed 5MB.")

        return value

    def create(self, validated_data):
        """
        Saves the uploaded file to Django's default storage (MEDIA_ROOT).
        Returns an instance of UploadedFileRepresentation.
        """
        uploaded_file = validated_data['file']

        # Generate a unique filename using UUID to prevent conflicts
        file_extension = os.path.splitext(uploaded_file.name)[1]
        new_filename = f"chat_uploads/{uuid.uuid4()}{file_extension}" # Save into 'media/chat_uploads/'

        file_path = default_storage.save(new_filename, uploaded_file)

        return UploadedFileRepresentation(file_path)

    # This method is crucial. It defines how the *output* of the serializer looks.
    # DRF expects `to_representation` to return a dictionary of primitive data.
    def to_representation(self, instance):
        """Custom representation for the uploaded file response."""
        # `instance` here is the UploadedFileRepresentation object returned by `create`.
        request = self.context.get('request')
        if request and hasattr(instance, 'url'):
            file_url = request.build_absolute_uri(instance.url)
            return {'file_url': file_url}
        return {} # Return empty if no valid instance or URL

# --- Serializer for Individual Messages ---
class MessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(source='sender.id', read_only=True)
    sender_first_name = serializers.CharField(source='sender.profile.first_name', read_only=True)
    sender_last_name = serializers.CharField(source='sender.profile.last_name', read_only=True)
    sender_photo = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField() 
    created_at = DamascusDateTimeField(read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'sender_id', 'sender_first_name', 'sender_last_name', 'sender_photo',
            'content', 'file_url', 'message_type', 'created_at', 'is_read',
        ]
        read_only_fields = fields 

    def get_sender_photo(self, obj):
        request = self.context.get('request')
        if obj.sender.profile and obj.sender.profile.photo and request:
            return request.build_absolute_uri(obj.sender.profile.photo.url)
        return None

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        elif obj.message_type != Message.MessageType.TEXT and obj.content and (obj.content.startswith('http://') or obj.content.startswith('https://')):
            return obj.content
        return None

# --- Serializer for Conversation List View ---
class ConversationListSerializer(serializers.ModelSerializer):
    other_user_id = serializers.SerializerMethodField()
    other_user_first_name = serializers.SerializerMethodField()
    other_user_last_name = serializers.SerializerMethodField()
    other_user_photo = serializers.SerializerMethodField()
    other_user_is_online = serializers.SerializerMethodField()
    other_user_last_seen = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.IntegerField(read_only=True)
    created_at = DamascusDateTimeField(read_only=True)
    updated_at = DamascusDateTimeField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            'id', 'other_user_id', 'other_user_first_name', 'other_user_last_name', 
            'other_user_photo', 'other_user_is_online', 'other_user_last_seen',
            'last_message', 'unread_count', 'created_at', 'updated_at',
        ]

    def get_other_user(self, obj):
        user = self.context['request'].user
        return obj.participant2 if user == obj.participant1 else obj.participant1

    def get_other_user_id(self, obj):
        return self.get_other_user(obj).id

    def get_other_user_first_name(self, obj):
        other_user = self.get_other_user(obj)
        return other_user.profile.first_name if hasattr(other_user, 'profile') and other_user.profile else None

    def get_other_user_last_name(self, obj):
        other_user = self.get_other_user(obj)
        return other_user.profile.last_name if hasattr(other_user, 'profile') and other_user.profile else None

    def get_other_user_photo(self, obj):
        other_user = self.get_other_user(obj)
        request = self.context['request']
        if hasattr(other_user, 'profile') and other_user.profile and other_user.profile.photo and request:
            return request.build_absolute_uri(other_user.profile.photo.url)
        return None

    def get_other_user_is_online(self, obj):
        return self.get_other_user(obj).is_online

    def get_other_user_last_seen(self, obj):
        last_seen = self.get_other_user(obj).last_seen
        if last_seen:
            return DamascusDateTimeField().to_representation(last_seen)
        return None

    def get_last_message(self, obj):
        # Check if the annotated field is present on the object
        if hasattr(obj, 'last_message_id') and obj.last_message_id is not None:
            return {
                'content': obj.last_message_content,
                'created_at': DamascusDateTimeField().to_representation(obj.last_message_created_at),
                'is_read': obj.last_message_is_read
            }
        return None

    

# --- Serializer for Creating Conversations ---
class ConversationCreateSerializer(serializers.ModelSerializer):
    other_user_id = serializers.IntegerField(write_only=True, help_text="ID of the user to start a conversation with.")

    class Meta:
        model = Conversation
        fields = ['id', 'other_user_id']
        read_only_fields = ['id'] 

    def validate_other_user_id(self, value):
        request_user = self.context['request'].user
        if value == request_user.id:
            raise serializers.ValidationError("Cannot create a conversation with yourself.")

        try:
            other_user = User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("User with this ID does not exist.")

        self.other_user = other_user
        return value

    def create(self, validated_data):
        participant1 = self.context['request'].user
        participant2 = self.other_user 

        conversation = Conversation.objects.filter(
            Q(participant1=participant1, participant2=participant2) |
            Q(participant1=participant2, participant2=participant1)
        ).first()

        if conversation:
            return conversation

        conversation = Conversation.objects.create(
            participant1=participant1,
            participant2=participant2
        )
        return conversation

# --- Serializer for User Status Update (for Swagger only) ---
# This is explicitly for the UserStatusUpdateView's PATCH request body.
class UserStatusUpdateSerializer(serializers.Serializer):
    online = serializers.BooleanField(required=True, help_text='Set true for online, false for offline')