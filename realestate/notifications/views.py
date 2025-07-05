
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Count, Prefetch 
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import serializers
from .models import Notification
from .serializers import NotificationSerializer
from users.models import User 
from properties.models import Property 
from django.contrib.contenttypes.models import ContentType # For GenericForeignKey lookups
from rest_framework.views import APIView 
from rest_framework.serializers import Serializer as DRFSerializer
from asgiref.sync import async_to_sync 
from channels.layers import get_channel_layer
class NotificationListView(generics.ListAPIView):
    """
    API endpoint to list all notifications for the authenticated user.
    Retrieves all notifications (read and unread).
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Notification.objects.filter(recipient=user)

        # --- OPTIMIZATION for GenericForeignKey (keep as is) ---
        user_content_type = ContentType.objects.get_for_model(User)
        property_content_type = ContentType.objects.get_for_model(Property)

        queryset = queryset.prefetch_related(
            Prefetch(
                'related_object',
                queryset=User.objects.select_related('profile'),
                to_attr='_prefetched_user_object'
            ) if user_content_type else None,
            Prefetch(
                'related_object',
                queryset=Property.objects.prefetch_related('images'),
                to_attr='_prefetched_property_object'
            ) if property_content_type else None,
        )
        # --- END OPTIMIZATION ---


        return queryset.order_by('-created_at')

    @swagger_auto_schema(
        operation_description="List all notifications for the authenticated user. Returns all notifications (read and unread).",
        
        manual_parameters=[], 
        responses={
            200: openapi.Response(description="Notifications retrieved successfully.", schema=NotificationSerializer(many=True)),
            401: "Unauthorized"
        },
        security=[{'Bearer': []}]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

class NotificationMarkAllReadView(APIView): 
    """
    API endpoint to mark all unread notifications for the authenticated user as read.
    """
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(
        operation_description="Mark all unread notifications for the authenticated user as read.",
        responses={
            200: openapi.Response(
                description="All unread notifications marked as read.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={'detail': openapi.Schema(type=openapi.TYPE_STRING)}
                )
            ),
            401: "Unauthorized"
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, *args, **kwargs):
        user = request.user
        unread_notifications = Notification.objects.filter(recipient=user, is_read=False)
        updated_count = unread_notifications.update(is_read=True)

        # --- NEW: Real-time Update for Unread Count ---
        # Calculate new unread count (will be 0 after marking all read)
        new_unread_count = Notification.objects.filter(recipient=user, is_read=False).count() # Should be 0

        # Dispatch real-time update to user's notification WebSocket
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'user_{user.id}_notifications', # User's personal notification group
                {
                    'type': 'notification.unread_count_update', # Calls notification_unread_count_update handler
                    'count': new_unread_count # Send the updated count (0)
                }
            )
            print(f"DEBUG: Dispatched real-time unread count update ({new_unread_count}) after mark-all-read for {user.email}.")
        # --- END NEW ---

        return Response(
            {'detail': f"Successfully marked {updated_count} notifications as read."},
            status=status.HTTP_200_OK
        )

class UnreadNotificationCountView(APIView): 
    """
    API endpoint to get the count of unread notifications for the authenticated user.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = DRFSerializer 

    @swagger_auto_schema(
        operation_description="Get the count of unread notifications for the authenticated user.",
        responses={
            200: openapi.Response(
                description="Unread count retrieved successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={'unread_count': openapi.Schema(type=openapi.TYPE_INTEGER)}
                )
            ),
            401: "Unauthorized"
        },
        security=[{'Bearer': []}]
    )
    def get(self, request, *args, **kwargs):
        user = request.user
        unread_count = Notification.objects.filter(recipient=user, is_read=False).count()
        return Response({'unread_count': unread_count}, status=status.HTTP_200_OK)