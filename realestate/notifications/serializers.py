
from rest_framework import serializers
from .models import Notification
from django.contrib.auth import get_user_model
from users.models import Profile 
from properties.models import Property 
from core.serializers.fields import DamascusDateTimeField 

User = get_user_model()

# --- Nested Serializers for Related Objects (to avoid N+1 and provide context) ---

class NotificationUserSerializer(serializers.ModelSerializer):
    """
    A minimal serializer for the User model within a notification context.
    Used for the 'sender' of a favorite/rating notification.
    """
    first_name = serializers.CharField(source='profile.first_name', read_only=True)
    last_name = serializers.CharField(source='profile.last_name', read_only=True)
    photo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'photo']
        read_only_fields = fields

    def get_photo(self, obj):
        request = self.context.get('request')
        if obj.profile and obj.profile.photo and request:
            return request.build_absolute_uri(obj.profile.photo.url)
        return None

class NotificationPropertySerializer(serializers.ModelSerializer):
    """
    A minimal serializer for the Property model within a notification context.
    Used for the 'related_object' when notification_type is property-related.
    """
    main_photo = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = ['id', 'ptype', 'city', 'price', 'is_for_rent', 'main_photo']
        read_only_fields = fields

    def get_main_photo(self, obj):
        request = self.context.get('request')
        first_image = obj.images.first()
        if first_image and request:
            return request.build_absolute_uri(first_image.image.url)
        return None

# --- Main Notification Serializer ---

class NotificationSerializer(serializers.ModelSerializer):
    # Display the human-readable type
    notification_type_display = serializers.CharField(source='get_notification_type_display', read_only=True)

    # Recipient details (optional, if you want to show recipient in some contexts)
    recipient_email = serializers.CharField(source='recipient.email', read_only=True)

    # Generic Related Object Field
    # This field will dynamically serialize the related object based on its content_type
    related_object_data = serializers.SerializerMethodField()

    created_at = DamascusDateTimeField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id', 'recipient_id', 'recipient_email', 'notification_type', 'notification_type_display',
            'message', 'is_read', 'created_at', 'related_object_data',
            # You might also include 'content_type_id' and 'object_id' if Flutter needs them explicitly
        ]
        read_only_fields = fields # Notifications are read-only after creation

    def get_related_object_data(self, obj):
        """
        Dynamically serializes the related object based on its content_type.
        This is crucial for providing context to the notification.
        """
        if obj.related_object:
            request = self.context.get('request')
            if isinstance(obj.related_object, User):
                # If the related object is a User, use NotificationUserSerializer
                return NotificationUserSerializer(obj.related_object, context={'request': request}).data
            elif isinstance(obj.related_object, Property):
                # If the related object is a Property, use NotificationPropertySerializer
                return NotificationPropertySerializer(obj.related_object, context={'request': request}).data
            # Add more elif blocks here for other related object types (e.g., Inquiry, if you create one)
        return None