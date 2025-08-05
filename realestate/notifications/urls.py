
from django.urls import path
from .views import NotificationListView, UnreadNotificationCountView, NotificationMarkAllReadView, NotificationMarkSingleReadView

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('mark-all-read/', NotificationMarkAllReadView.as_view(), name='notification-mark-read'),
    path('unread-count/', UnreadNotificationCountView.as_view(), name='notification-unread-count'),
     path('<int:pk>/mark-read/', NotificationMarkSingleReadView.as_view(), name='notification-mark-single-read'),
]