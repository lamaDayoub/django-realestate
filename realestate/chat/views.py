# chat/views.py
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q , Max, Subquery, OuterRef
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema, no_body # Import no_body for clarity
from drf_yasg import openapi
from .models import Conversation, Message 
from django.db import models
from asgiref.sync import async_to_sync 

from django.db.models import Count
from channels.layers import get_channel_layer 


from .serializers import (
    ConversationListSerializer, 
    MessageSerializer, 
    ConversationCreateSerializer, 
    FileUploadSerializer,
    UserStatusUpdateSerializer, 
    ChatParticipantSerializer,
)
# Assuming User is in users.models
from users.models import User 



# --- API endpoint for Manual User Status Update ---
class UserStatusUpdateView(generics.UpdateAPIView):
    """
    API endpoint to manually update a user's online status.
    Primarily for fallback or manual control; real-time status
    is best handled via WebSocket connections.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserStatusUpdateSerializer # <--- NEW: Link serializer for Swagger body

    @swagger_auto_schema(
        operation_description="Manually update user's online status. (Primarily handled by WebSockets, this is a fallback/manual API)",
        # request_body is now automatically inferred from serializer_class
        responses={
            200: openapi.Response(
                description='Status updated successfully',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'status': openapi.Schema(type=openapi.TYPE_STRING),
                        'last_seen': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_DATETIME, nullable=True)
                    }
                )
            ),
            401: 'Unauthorized'
        },
        security=[{'Bearer': []}]
    )
    def patch(self, request, *args, **kwargs):
        online = request.data.get('online')
        if online is None:
            return Response({"detail": "The 'online' field is required."}, status=status.HTTP_400_BAD_REQUEST)

        request.user.update_status(online) 

        last_seen = request.user.last_seen
        if last_seen:
            damascus_time = timezone.localtime(last_seen)
        else:
            damascus_time = None

        return Response({
            'status': 'online' if online else 'offline',
            'last_seen': damascus_time.isoformat() if damascus_time else None
        }, status=status.HTTP_200_OK)

# --- API endpoint for Listing Conversations ---
class ConversationListView(generics.ListAPIView):
    """
    API endpoint to list all conversations for the authenticated user.
    Includes details of the other participant, last message, and unread count.
    """
    serializer_class = ConversationListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # --- OPTIMIZED QUERY FOR LAST MESSAGE AND UNREAD COUNT ---
        # 1. Define a Subquery to get the last message for each conversation
        last_message_subquery = Message.objects.filter(
            conversation=OuterRef('pk')
        ).order_by('-created_at').values('id', 'content', 'message_type', 'is_read', 'created_at')[:1]

        # 2. Define a Subquery to count unread messages from the OTHER participant
        unread_count_subquery = Message.objects.filter(
            conversation=OuterRef('pk'),
            sender__in=Subquery(
                User.objects.filter(
                    Q(conversations_as_p1=OuterRef('pk')) | Q(conversations_as_p2=OuterRef('pk'))
                ).exclude(id=user.id).values('pk')[:1] # Get the other user's ID
            ),
            is_read=False
        ).order_by().values('conversation').annotate(count=models.Count('pk')).values('count')

        # 3. Build the final queryset with both annotations
        queryset = Conversation.objects.filter(
            Q(participant1=user) | Q(participant2=user)
        ).annotate(
            # Annotate the queryset with the last message's ID, content, etc.
            last_message_id=Subquery(last_message_subquery.values('id')),
            last_message_content=Subquery(last_message_subquery.values('content')),
            last_message_type=Subquery(last_message_subquery.values('message_type')),
            last_message_is_read=Subquery(last_message_subquery.values('is_read')),
            last_message_created_at=Subquery(last_message_subquery.values('created_at')),

            # Annotate the queryset with the unread count
            unread_count=Subquery(unread_count_subquery, output_field=models.IntegerField()),
        ).select_related(
            'participant1__profile', 
            'participant2__profile'
        ).order_by('-updated_at') # Order by last updated conversation

        return queryset

    @swagger_auto_schema(...) # Keep your existing swagger_auto_schema
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
# --- API endpoint for Retrieving Messages in a Conversation ---
class ConversationDetailView(generics.ListAPIView):
    """
    API endpoint to retrieve all messages for a specific conversation.
    Messages from the other participant are automatically marked as read when fetched.
    """
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None 

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Message.objects.none()

        user = self.request.user
        conversation_id = self.kwargs['pk'] 

        queryset = Message.objects.filter(
            conversation_id=conversation_id,
            conversation__in=Conversation.objects.filter(
                Q(participant1=user) | Q(participant2=user)
            )
        ).order_by('created_at').select_related('sender__profile')

        # --- NEW: Real-time updates after marking messages as read ---
        messages_to_mark_read = queryset.exclude(sender=user).filter(is_read=False)

        # Capture the count BEFORE updating, to know if any were actually unread
        initial_unread_in_conv_count = messages_to_mark_read.count()

        if initial_unread_in_conv_count > 0: # Only update if there were unread messages
            messages_to_mark_read.update(is_read=True)
            print(f"DEBUG: ConversationDetailView marked {initial_unread_in_conv_count} messages as read for conv {conversation_id}.")

            channel_layer = get_channel_layer()
            if channel_layer:
                # 1. Dispatch update for THIS conversation's unread count (now 0)
                # And update last_message for consistency
                conversation = Conversation.objects.get(id=conversation_id) # Get conversation object
                other_participant = conversation.get_other_participant(user) # Get other participant

                # Calculate last message data for update
                last_msg_obj = conversation.messages.order_by('-created_at').first()
                last_message_data = None
                if last_msg_obj:
                    # Re-use MessageSerializer to get formatted data
                    from chat.serializers import MessageSerializer # Import locally to avoid circular
                    last_message_data = MessageSerializer(last_msg_obj, context={'request': self.request}).data
                conv_created_at = timezone.localtime(conversation.created_at).isoformat()
                conv_updated_at = timezone.localtime(conversation.updated_at).isoformat()
                async_to_sync(channel_layer.group_send)(
                    f'user_{user.id}_conversation_list', # Group for current user's list updates
                    {
                        'type': 'chat.conversation_update',
                        'conversation_id': conversation.id,
                        'last_message_data': last_message_data,
                        'unread_count_for_this_conversation': 0, # Now 0 unread in this chat
                        'other_participant_details': ChatParticipantSerializer(other_participant, context={'request': self.request}).data,
                        'is_new_conversation': False, # Not a new conversation, just an update
                        'created_at': conv_created_at, # <--- ADD THIS
                        'updated_at': conv_updated_at,
                    
                    }
                )
                print(f"DEBUG: Dispatched real-time conversation update (unread 0) for conv {conversation.id} to {user.email}.")

                # 2. Dispatch update for GLOBAL chat unread count
                total_unread_chat_messages = Message.objects.filter(conversation__in=user.conversations_as_p1.all() | user.conversations_as_p2.all(), is_read=False).exclude(sender=user).count()

                async_to_sync(channel_layer.group_send)(
                    f'user_{user.id}_conversation_list', # Same group
                    {
                        'type': 'chat.total_unread_count_update',
                        'count': total_unread_chat_messages
                    }
                )
                print(f"DEBUG: Dispatched real-time global unread chat count update ({total_unread_chat_messages}) to {user.email}.")
        # --- END NEW ---

        return queryset

    @swagger_auto_schema(
        operation_description="Retrieve all messages for a specific conversation. Messages from the other participant will be automatically marked as read upon retrieval.",
        parameters=[
            openapi.Parameter('pk', openapi.IN_PATH, description="ID of the conversation", type=openapi.TYPE_INTEGER)
        ],
        responses={
            200: openapi.Response(
                description="Messages retrieved successfully.",
                schema=MessageSerializer(many=True),
            ),
            403: "Forbidden. User is not a participant in this conversation.",
            404: "Not Found. Conversation does not exist.",
        },
        security=[{'Bearer': []}]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

# --- API endpoint for Creating New Conversations ---
class CreateConversationView(generics.CreateAPIView):
    """
    API endpoint to create a new private conversation between the authenticated user and another specified user.
    If a conversation already exists, it returns the existing one (HTTP 200 OK).
    Pushes real-time updates to both participants' conversation lists.
    """
    serializer_class = ConversationCreateSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        pass 

    @swagger_auto_schema(
        operation_description="Create a new private conversation between the authenticated user and another user. If a conversation already exists, it returns the existing one (HTTP 200 OK). Pushes real-time updates to both participants' conversation lists.",
        request_body=ConversationCreateSerializer,
        responses={
            201: openapi.Response(description="Conversation created successfully.", schema=ConversationCreateSerializer),
            200: openapi.Response(description="Conversation already exists, returning existing conversation details.", schema=ConversationCreateSerializer),
            400: "Bad Request. Invalid input or conversation with self/non-existent user.",
            401: "Unauthorized. Authentication required.",
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        participant1 = request.user
        other_user_id = serializer.validated_data['other_user_id']

        try:
            participant2 = User.objects.get(id=other_user_id) 
        except User.DoesNotExist:
            return Response({"detail": "Other user not found."}, status=status.HTTP_404_NOT_FOUND)

        conversation = Conversation.objects.filter(
            Q(participant1=participant1, participant2=participant2) |
            Q(participant1=participant2, participant2=participant1)
        ).first()

        status_code = status.HTTP_200_OK # Default to 200 if conversation exists
        if not conversation:
            conversation = serializer.create(validated_data=serializer.validated_data)
            conversation.participant1 = participant1
            conversation.participant2 = participant2
            conversation.save() 
            status_code = status.HTTP_201_CREATED # Set to 201 if newly created
            print(f"DEBUG: New conversation {conversation.id} created between {participant1.email} and {participant2.email}.")
        else:
            print(f"DEBUG: Conversation {conversation.id} already exists between {participant1.email} and {participant2.email}.")

        response_serializer = self.get_serializer(conversation)

        channel_layer = get_channel_layer()
        if channel_layer:
            # Get lightweight details for the other participant in the conversation
            # Ensure participants are fetched with profile for ChatParticipantSerializer
            participant1_with_profile = User.objects.select_related('profile').get(pk=participant1.pk)
            participant2_with_profile = User.objects.select_related('profile').get(pk=participant2.pk)

            # IMPORTANT: Use `request` as context, not `self.scope`
            # Also, ensure correct participant is passed for serializer context
            # The 'other_participant_details' should be the *other* person from the perspective of the recipient of the message.

            # Prepare common payload for conversation update
            conv_created_at = timezone.localtime(conversation.created_at).isoformat()
            conv_updated_at = timezone.localtime(conversation.updated_at).isoformat()

            payload_data_base = { # Renamed to avoid confusion with final payloads
                'type': 'chat.conversation_update',
                'conversation_id': conversation.id,
                'last_message_data': None, # No last message yet for new chat
                'unread_count_for_this_conversation': 0, # No unread messages yet
                'is_new_conversation': (status_code == status.HTTP_201_CREATED),
                'created_at': conv_created_at, 
                'updated_at': conv_updated_at,
            }

            # Push update to participant1 (the request user)
            payload_p1 = payload_data_base.copy()
            payload_p1['other_participant_details'] = ChatParticipantSerializer(participant2_with_profile, context={'request': request}).data
            async_to_sync(channel_layer.group_send)(
                f'user_{participant1.id}_conversation_list', # Group for participant1's list updates
                payload_p1
            )
            print(f"DEBUG: Dispatched real-time conversation update for new chat to {participant1.email}.")

            # Push update to participant2 (the other user)
            payload_p2 = payload_data_base.copy()
            payload_p2['other_participant_details'] = ChatParticipantSerializer(participant1_with_profile, context={'request': request}).data
            async_to_sync(channel_layer.group_send)(
                f'user_{participant2.id}_conversation_list', # Group for participant2's list updates
                payload_p2
            )
            print(f"DEBUG: Dispatched real-time conversation update for new chat to {participant2.email}.")

            # Also dispatch global unread count updates (they are 0 for new chat)
            async_to_sync(channel_layer.group_send)(
                f'user_{participant1.id}_conversation_list',
                {'type': 'chat.total_unread_count_update', 'count': 0}
            )
            async_to_sync(channel_layer.group_send)(
                f'user_{participant2.id}_conversation_list',
                {'type': 'chat.total_unread_count_update', 'count': 0}
            )
            print(f"DEBUG: Dispatched real-time global unread count update (0) for new chat.")
        # --- END NEW ---

        return Response(response_serializer.data, status=status_code)

# --- API endpoint for File Uploads ---
class FileUploadView(generics.CreateAPIView):
    """
    API endpoint to upload files (images/PDFs) for messages.
    Returns the absolute URL of the uploaded file.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser] 
    serializer_class = FileUploadSerializer 

    def perform_create(self, serializer):
        """
        Calls the serializer's create method to save the file.
        The serializer's create method will return the UploadedFileRepresentation.
        """
        file_representation = serializer.save()
        return file_representation 

    @swagger_auto_schema(
        operation_description="Upload a file (image or PDF) for a message. Returns the URL of the uploaded file. This URL should then be sent via WebSocket in a 'chat_message' type message.",
        request_body=FileUploadSerializer,
        responses={
            201: openapi.Response(
                description="File uploaded successfully.",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'file_url': openapi.Schema(type=openapi.TYPE_STRING, description="Absolute URL of the uploaded file.")
                    }
                )
            ),
            400: "Bad Request. Invalid file type or no file provided.",
            401: "Unauthorized. Authentication required."
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Call perform_create which will save the file and return the UploadedFileRepresentation
        file_representation = self.perform_create(serializer)

        # Construct the absolute URL from the returned representation's .url
        # The .url property of UploadedFileRepresentation already contains MEDIA_URL prefix
        file_url = request.build_absolute_uri(file_representation.url)

        # Return the custom response. This entirely bypasses the internal
        # `get_success_headers(serializer.data)` call that was causing the AttributeError.
        return Response({'file_url': file_url}, status=status.HTTP_201_CREATED)