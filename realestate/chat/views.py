# chat/views.py
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q 
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema, no_body # Import no_body for clarity
from drf_yasg import openapi
from .models import Conversation, Message 

# ... (rest of your imports, e.g., from .serializers) ...
from .serializers import (
    ConversationListSerializer, 
    MessageSerializer, 
    ConversationCreateSerializer, 
    FileUploadSerializer,
    UserStatusUpdateSerializer, 
)
# Assuming User is in users.models
from users.models import User 

# Import all serializers from chat.serializers
from .serializers import (
    ConversationListSerializer, 
    MessageSerializer, 
    ConversationCreateSerializer, 
    FileUploadSerializer,
    UserStatusUpdateSerializer, # <--- NEW: Import the status update serializer
)

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
        queryset = Conversation.objects.filter(
            Q(participant1=user) | Q(participant2=user)
        ).select_related(
            'participant1__profile', 
            'participant2__profile'
        ).order_by('-updated_at')
        return queryset

    @swagger_auto_schema(
        operation_description="Retrieve a list of all conversations for the authenticated user, including other participant details, last message summary, and unread message count.",
        responses={
            200: openapi.Response(
                description="List of conversations retrieved successfully.",
                schema=ConversationListSerializer(many=True),
            ),
            401: "Unauthorized. Authentication required."
        },
        security=[{'Bearer': []}]
    )
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
        # <--- NEW: Add this check to prevent KeyError: 'pk' during Swagger schema generation
        if getattr(self, 'swagger_fake_view', False):
            return Message.objects.none() # Return an empty queryset for schema introspection

        user = self.request.user
        conversation_id = self.kwargs['pk'] 

        queryset = Message.objects.filter(
            conversation_id=conversation_id,
            conversation__in=Conversation.objects.filter(
                Q(participant1=user) | Q(participant2=user)
            )
        ).order_by('created_at').select_related('sender__profile')

        messages_to_mark_read = queryset.exclude(sender=user).filter(is_read=False)
        messages_to_mark_read.update(is_read=True)

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
    """
    serializer_class = ConversationCreateSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        # The serializer's create method (which we customized) handles the core logic
        # of checking for existing conversations and creating if necessary.
        # It also sets `self.other_user` in the serializer.
        pass # The actual saving and existing check is now entirely in serializer.create

    @swagger_auto_schema(
        operation_description="Create a new private conversation between the authenticated user and another user. If a conversation already exists, it returns the existing one (HTTP 200 OK).",
        request_body=ConversationCreateSerializer,
        responses={
            201: openapi.Response(
                description="Conversation created successfully.",
                schema=ConversationCreateSerializer,
            ),
            200: openapi.Response(
                description="Conversation already exists, returning existing conversation details.",
                schema=ConversationCreateSerializer,
            ),
            400: "Bad Request. Invalid input or conversation with self/non-existent user.",
            401: "Unauthorized. Authentication required.",
        },
        security=[{'Bearer': []}]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Call serializer.save() which executes the custom create logic in ConversationCreateSerializer
        conversation = serializer.save() 

        # Determine status code based on whether the conversation was new or existing
        # We can't directly know from `serializer.save()` if it was `get_or_create`.
        # A common pattern is to add a flag to the serializer or infer.
        # A simpler approach: if `conversation` was retrieved (not created), `created_at` != `updated_at` (usually)
        # or simply check if any messages exist, but easiest is to just return 200.
        # For this context, if the serializer returns an object, we'll assume 200 if already exists.

        # To be explicit about 200 vs 201, we'd need to modify serializer.create
        # to return a tuple (instance, created_flag). Let's stick to the current simplified way.
        # The `ConversationCreateSerializer`'s `create` method already handles finding existing.

        # Let's adjust back to how it was in the initial version that worked with existing.
        # Check if conversation already existed BEFORE calling serializer.save() if we want to explicitly return 200/201.
        # The original logic was better for 200/201 distinction

        # --- Reverting to a clearer 200/201 logic for CreateConversationView.post ---
        participant1 = request.user
        other_user_id = serializer.validated_data['other_user_id']

        try:
            participant2 = User.objects.get(id=other_user_id) 
        except User.DoesNotExist:
            return Response({"detail": "Other user not found."}, status=status.HTTP_404_NOT_FOUND)

        # Check if conversation already exists (order-agnostic)
        conversation = Conversation.objects.filter(
            Q(participant1=participant1, participant2=participant2) |
            Q(participant1=participant2, participant2=participant1)
        ).first()

        if conversation:
            response_serializer = self.get_serializer(conversation)
            return Response(response_serializer.data, status=status.HTTP_200_OK) # Already exists
        else:
            # If not, create a new one using the serializer's `create` method
            new_conversation = serializer.create(validated_data=serializer.validated_data) # Explicitly call serializer's create
            new_conversation.participant1 = participant1 # Assign participants
            new_conversation.participant2 = participant2
            new_conversation.save() # Save the newly created conversation instance

            response_serializer = self.get_serializer(new_conversation)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED) # Newly created
        # --- End of explicit 200/201 logic ---


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