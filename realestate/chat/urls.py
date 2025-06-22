# chat/urls.py
from django.urls import path
from .views import (
    ConversationListView, 
    ConversationDetailView,
    CreateConversationView, 
    FileUploadView, 
    UserStatusUpdateView, # Your existing API view
)

urlpatterns = [
    path('conversations/', ConversationListView.as_view(), name='conversation-list'),
    path('conversations/create/', CreateConversationView.as_view(), name='conversation-create'),
    # Note: 'pk' here refers to the Conversation ID
    path('conversations/<int:pk>/messages/', ConversationDetailView.as_view(), name='conversation-messages'),
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('status/', UserStatusUpdateView.as_view(), name='user-status-update'), # Your existing API view for manual status updates
]