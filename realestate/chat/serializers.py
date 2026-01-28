

# chat/serializers.py

import os
import uuid

from rest_framework import serializers
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import Q

from users.models import Profile
from core.serializers.fields import DamascusDateTimeField
from chat.models import Message, Conversation

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
        allowed_types = [
            'image/jpeg',
            'image/png',
            'image/gif',    # Added GIF
            'image/bmp',    # Added BMP
            'image/webp',   # Added WebP
            'image/tiff',   # Added TIFF
            'application/pdf'
        ]
        if value.content_type not in allowed_types:
            raise serializers.ValidationError("Only JPEG, PNG, GIF, BMP, WebP, TIFF images, and PDF files are allowed.")

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

    def to_representation(self, instance):
        """Custom representation for the uploaded file response."""
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
    
    # RE-INTRODUCED: SerializerMethodField for sender_photo and file_url for HTTP views
    sender_photo = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    
    created_at = DamascusDateTimeField(read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'sender_id', 'sender_first_name', 'sender_last_name', 'sender_photo',
            'content', 'file_url', 'message_type', 'created_at', 'is_read',
        ]
        read_only_fields = fields # All fields are read-only for output

    # RE-INTRODUCED METHOD: For HTTP API to get sender photo URL
    def get_sender_photo(self, obj):
        request = self.context.get('request')
        if obj.sender.profile and obj.sender.profile.photo and request:
            return request.build_absolute_uri(obj.sender.profile.photo.url)
        return None # Return None if no photo or request context

    # RE-INTRODUCED METHOD: For HTTP API to get file URL from Message.file
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        # Handle case where content might contain an external URL (e.g., if not stored in FileField)
        elif obj.message_type != Message.MessageType.TEXT and obj.content and (obj.content.startswith('http://') or obj.content.startswith('https://')):
            return obj.content
        return None


class ChatParticipantSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for chat participants (used in real-time updates).
    Includes basic user and profile info.
    """
    first_name = serializers.CharField(source='profile.first_name', read_only=True)
    last_name = serializers.CharField(source='profile.last_name', read_only=True)
    
    # RE-INTRODUCED: SerializerMethodField for photo_url for HTTP views
    photo_url = serializers.SerializerMethodField()
    
    is_online = serializers.BooleanField(read_only=True)
    last_seen = DamascusDateTimeField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'photo_url', 'is_online', 'last_seen']
        read_only_fields = fields

    # RE-INTRODUCED METHOD: For HTTP API to get participant photo URL
    def get_photo_url(self, obj):
        request = self.context.get('request')
        if hasattr(obj, 'profile') and obj.profile and obj.profile.photo and request:
            return request.build_absolute_uri(obj.profile.photo.url)
        return None


# --- Serializer for Conversation List View ---
class ConversationListSerializer(serializers.ModelSerializer):
    other_user_id = serializers.SerializerMethodField()
    # CHANGED: These must be SerializerMethodField as they depend on get_other_user
    other_user_first_name = serializers.SerializerMethodField()
    other_user_last_name = serializers.SerializerMethodField()
    other_user_photo = serializers.SerializerMethodField()
    other_user_is_online = serializers.SerializerMethodField()
    other_user_last_seen = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
   
    unread_count = serializers.IntegerField(read_only=True) # This will be fixed by Coalesce

    created_at = DamascusDateTimeField(read_only=True)
    updated_at = DamascusDateTimeField(read_only=True)
    activated_at = DamascusDateTimeField(read_only=True)
    expires_at = DamascusDateTimeField(read_only=True)
    class Meta:
        model = Conversation
        fields = [
            'id', 'other_user_id', 'other_user_first_name', 'other_user_last_name',
            'other_user_photo', 'other_user_is_online', 'other_user_last_seen',
            'last_message', 'unread_count', 'created_at', 'updated_at',
            'activated_at', 'expires_at'
        ]

    def get_other_user(self, obj):
        # This method is crucial for determining which participant is "other"
        user = self.context['request'].user
        # The Conversation object in the queryset is already select_related to participant1__profile and participant2__profile
        # so accessing .profile here should not cause N+1 queries.
        return obj.participant2 if user == obj.participant1 else obj.participant1

    def get_other_user_id(self, obj):
        return self.get_other_user(obj).id

    # RE-INTRODUCED/FIXED METHODS for other_user details
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
        other_user = self.get_other_user(obj)
        return other_user.is_online

    def get_other_user_last_seen(self, obj):
        other_user = self.get_other_user(obj)
        last_seen = other_user.last_seen
        if last_seen:
            return DamascusDateTimeField().to_representation(last_seen)
        return None

    def get_last_message(self, obj):
        if hasattr(obj, 'last_message_id') and obj.last_message_id is not None:
            return {
                'id': obj.last_message_id, # ADDED: The ID of the last message
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
class UserStatusUpdateSerializer(serializers.Serializer):
    online = serializers.BooleanField(required=True, help_text='Set true for online, false for offline')


class ChatStatusCheckSerializer(serializers.Serializer):
    """
    Serializer for the response of the chat status check API.
    """
    status_code = serializers.CharField(
        max_length=50,
        help_text="Status of the chat: NEW_CHAT_AVAILABLE, CHAT_ACTIVE, CHAT_EXPIRED_REACTIVATE, INSUFFICIENT_POINTS."
    )
    conversation_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the conversation, if it exists."
    )
    cost = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Points cost for new chat or reactivation."
    )
    current_points = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Current points balance of the user (if insufficient points)."
    )
    expires_at = DamascusDateTimeField(
        required=False,
        allow_null=True,
        help_text="Timestamp when the conversation session expires (if active/expired)."
    )
    message = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Descriptive message for the status."
    )


# NEW SERIALIZER FOR CHAT ACTIVATION API (PART 2)
class ChatActivateSerializer(serializers.Serializer):
    """
    Serializer for the request to activate/reactivate a chat.
    """
    property_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="The ID of the property for which to activate/reactivate chat."
    )
    conversation_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional: The ID of an existing conversation to reactivate."
    )
    owner_id=serializers.IntegerField(
        help_text="Optional: The ID ofthe other participant."
    )

class SingleConversationDetailSerializer(ConversationListSerializer): # FIX: Inherit from ConversationListSerializer
    """
    Serializer for a single conversation's details, reusing ConversationListSerializer's logic.
    This provides the same top-level fields as a single item from the conversation list.
    """
    class Meta(ConversationListSerializer.Meta): # Inherit Meta from parent
        model = Conversation
        # No need to redefine fields here unless you want to exclude some from the parent.
        # By default, it will inherit all fields from ConversationListSerializer.
        fields = ConversationListSerializer.Meta.fields
        read_only_fields =  ConversationListSerializer.Meta.fields
    