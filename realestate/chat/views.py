# chat/views.py
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q , Max, Subquery, OuterRef
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema, no_body  # Import no_body for clarity
from drf_yasg import openapi

from .models import Conversation, Message 
from django.db import models
from asgiref.sync import async_to_sync 
from django.db.models.functions import Coalesce
from django.db.models import Count
from channels.layers import get_channel_layer 
from drf_yasg.openapi import Schema

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


class ConversationListView(generics.ListAPIView):
    """
    API endpoint to list all conversations for the authenticated user.
    Includes details of the other participant, last message, and unread count.
    Also includes a total unread count across all conversations.
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

        # 2. Direct annotation for unread_count for EACH conversation
        #    Count messages in this conversation (OuterRef) that are unread (is_read=False)
        #    AND were NOT sent by the current user (sender != user).
        unread_count_annotation = models.Count(
            'messages', # Count messages related to this conversation
            filter=Q(messages__is_read=False, messages__sender__isnull=False) & ~Q(messages__sender=user)
        )

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

            # Annotate the queryset with the unread count, using Coalesce to default to 0
            unread_count=Coalesce(unread_count_annotation, 0),
        ).select_related(
            'participant1__profile',
            'participant2__profile'
        ).order_by('-updated_at') # Order by last updated conversation

        return queryset

    
    @swagger_auto_schema(
    operation_description="Retrieve all conversations for the authenticated user. Includes details of the other participant, last message, and unread count. The response also includes a 'total_unread_count' for all chats.",
    responses={
        200: openapi.Response(
            description="Conversations retrieved successfully.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'total_unread_count': openapi.Schema(type=openapi.TYPE_INTEGER, description="Total unread messages across all conversations for the user."),
                    'count': openapi.Schema(type=openapi.TYPE_INTEGER, description="Total number of conversations."),
                    'next': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_URI, nullable=True),
                    'previous': openapi.Schema(type=openapi.TYPE_STRING, format=openapi.FORMAT_URI, nullable=True),
                    'results': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            description="Conversation object (see ConversationListSerializer)"
                            # Optional: You can leave this empty and DRF-YASG will still use ConversationListSerializer
                        )
                    )
                }
            )
        ),
        401: 'Unauthorized'
    },
    security=[{'Bearer': []}]
    )
    def get(self, request, *args, **kwargs):
        # Get the standard paginated response
        response = super().get(request, *args, **kwargs)
        
        # Calculate the total unread count for the current user
        # This query is robust and counts messages NOT sent by the user and NOT read by the user
        total_unread_chat_messages = Message.objects.filter(
            Q(conversation__participant1=request.user) | Q(conversation__participant2=request.user),
            is_read=False
        ).exclude(sender=request.user).count()

        # Create a new response data structure
        custom_response_data = {
            'total_unread_count': total_unread_chat_messages,
            'count': response.data['count'],
            'next': response.data['next'],
            'previous': response.data['previous'],
            'results': response.data['results'],
        }
        
        # Return the new custom response
        return Response(custom_response_data, status=status.HTTP_200_OK)

class ConversationDetailView(generics.ListAPIView):
    """
    API endpoint to retrieve all messages for a specific conversation.
    Messages from the other participant are automatically marked as read and a real-time
    broadcast is sent to the sender's client.
    """
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Message.objects.none()

        user = self.request.user
        conversation_id = self.kwargs['pk']

        # Ensure the user is a participant in the conversation
        try:
            # FIX: Correctly combine ID lookup with Q objects for participant check
            # Combine the ID filter with the OR condition using the & operator
            conversation = Conversation.objects.get(
                Q(id=conversation_id) & (Q(participant1=user) | Q(participant2=user))
            )
        except Conversation.DoesNotExist:
            # If the conversation doesn't exist or the user is not a participant,
            # return an empty queryset. DRF will then return an empty list for messages.
            # For a 404 on the conversation itself, it's often handled by a custom
            # exception handler or by raising Http404 in the dispatch method.
            # For get_queryset, returning an empty queryset is the standard way to indicate no data.
            print(f"DEBUG: Conversation {conversation_id} not found or user {user.id} not a participant.")
            return Message.objects.none() # Return empty queryset if conversation not found or user not participant


        queryset = Message.objects.filter(
            conversation=conversation # Filter by the validated conversation object
        ).order_by('created_at').select_related('sender__profile')

        messages_to_mark_read = queryset.filter(is_read=False).exclude(sender=user)
        message_ids_to_mark_read = list(messages_to_mark_read.values_list('id', flat=True))

        if message_ids_to_mark_read:
            # Perform the bulk database update
            messages_to_mark_read.update(is_read=True)
            print(f"DEBUG: ConversationDetailView marked {len(message_ids_to_mark_read)} messages as read for conv {conversation_id}.")

            # Dispatch real-time updates via channel layer
            channel_layer = get_channel_layer()
            if channel_layer:
                # 1. Get the sender of the messages that were just read
                other_participant = conversation.get_other_participant(user)

                # 2. Broadcast a bulk read confirmation to the conversation group
                async_to_sync(channel_layer.group_send)(
                    f'chat_{conversation_id}',
                    {
                        'type': 'messages_read_confirmation',
                        'reader_user_id': str(user.id),
                        'message_ids': [str(mid) for mid in message_ids_to_mark_read]
                    }
                )
                print(f"DEBUG: Broadcasted bulk read confirmation for conv {conversation_id} to group.")

                # 3. Broadcast the new unread count for THIS specific conversation (which is now 0)
                #    We need the last message data to update the conversation list entry on the client
                last_msg_obj = conversation.messages.order_by('-created_at').first()
                last_message_data = None
                if last_msg_obj:
                    # Import MessageSerializer locally to avoid circular dependency
                    from chat.serializers import MessageSerializer
                    last_message_data = MessageSerializer(last_msg_obj, context={'request': self.request}).data
                
                # Get participant details for the current user (reader) to send to their own list
                reader_participant_details = ChatParticipantSerializer(user, context={'request': self.request}).data

                async_to_sync(channel_layer.group_send)(
                    f'user_{user.id}_conversation_list', # Send to the reader's conversation list group
                    {
                        'type': 'chat.conversation_update',
                        'conversation_id': conversation.id,
                        'last_message_data': last_message_data,
                        'unread_count_for_this_conversation': 0, # Explicitly 0 for this conversation for the reader
                        'other_participant_details': ChatParticipantSerializer(other_participant, context={'request': self.request}).data, # Details of the other person in the chat
                        'is_new_conversation': False,
                        'created_at': timezone.localtime(conversation.created_at).isoformat(),
                        'updated_at': timezone.localtime(conversation.updated_at).isoformat(),
                    }
                )
                print(f"DEBUG: Dispatched real-time conversation update (unread 0 for this conv) for conv {conversation.id} to {user.email}.")


                # 4. Recalculate and broadcast the NEW total unread count for the user who read the messages.
                total_unread_count = Message.objects.filter(
                    Q(conversation__participant1=user) | Q(conversation__participant2=user),
                    is_read=False
                ).exclude(sender=user).count()

                async_to_sync(channel_layer.group_send)(
                    f'user_{user.id}_conversation_list',
                    {
                        'type': 'chat.total_unread_count_update',
                        'count': total_unread_count
                    }
                )
                print(f"DEBUG: Dispatched new total unread count ({total_unread_count}) for {user.email}.")

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
    
    

class UnreadMessagesInConversationView(generics.ListAPIView):
    """
    API endpoint to get a list of unread message IDs for the authenticated user
    within a specific conversation.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer # We'll override list to return just IDs, but need a serializer for Swagger

    @swagger_auto_schema(
        operation_description="Get a list of unread message IDs for the authenticated user within a specific conversation. These are messages sent by the other participant that the current user has not yet read.",
        manual_parameters=[
            openapi.Parameter(
                'pk',
                openapi.IN_PATH,
                description="The ID of the conversation.",
                type=openapi.TYPE_INTEGER,
                required=True
            ),
        ],
        responses={
            200: openapi.Response(
                description="List of unread message IDs.",
                schema=openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(type=openapi.TYPE_INTEGER, description="Message ID")
                )
            ),
            401: "Unauthorized",
            403: "Forbidden (User is not a participant in the conversation).",
            404: "Conversation not found."
        },
        security=[{'Bearer': []}]
    )
    def get(self, request, pk, *args, **kwargs):
        user = request.user
        conversation_id = pk

        try:
            # Verify the conversation exists and the user is a participant
            conversation = Conversation.objects.get(
                Q(id=conversation_id) & (Q(participant1=user) | Q(participant2=user))
            )
        except Conversation.DoesNotExist:
            return Response({"detail": "Conversation not found or you are not a participant."}, status=status.HTTP_404_NOT_FOUND)

        # Get unread messages from the other participant
        unread_message_ids = Message.objects.filter(
            conversation=conversation,
            is_read=False
        ).exclude(
            sender=user
        ).values_list('id', flat=True) # Get only the IDs as a flat list

        return Response(list(unread_message_ids), status=status.HTTP_200_OK)
