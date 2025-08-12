# chat/urls.py
from django.urls import path
from .views import (
    ConversationListView, 
    ConversationDetailView,
    CreateConversationView, 
    FileUploadView, 
    UserStatusUpdateView,
    UnreadMessagesInConversationView,
    CheckChatStatusView, 
    ActivateChatView,
    SingleConversationInfoView,
    
)

urlpatterns = [
    path('conversations/', ConversationListView.as_view(), name='conversation-list'),
    path('conversations/create/', CreateConversationView.as_view(), name='conversation-create'),
    # Note: 'pk' here refers to the Conversation ID
    path('conversations/<int:pk>/unread-messages/', UnreadMessagesInConversationView.as_view(), name='conversation-unread-messages'),
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('conversations/<int:pk>/messages/', ConversationDetailView.as_view(), name='conversation-messages'),
    path('files/upload/', FileUploadView.as_view(), name='file-upload'),
    path('status/', UserStatusUpdateView.as_view(), name='user-status-update'), 
    path('conversations/check-status/<int:property_id>/', CheckChatStatusView.as_view(), name='chat-check-status'),
    path('conversations/activate/', ActivateChatView.as_view(), name='chat-activate'),
     path('conversations/<int:pk>/info/', SingleConversationInfoView.as_view(), name='conversation-info'),
]