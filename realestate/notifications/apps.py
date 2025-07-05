# notifications/apps.py
from django.apps import AppConfig

class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'

    def ready(self):
        # The import is here, but we'll try to ensure it runs after Django is fully ready.
        # This is the standard pattern.
        try:
            import notifications.signals
            print("DEBUG: Notifications signals loaded via apps.py ready method.")
        except Exception as e:
            print(f"ERROR: Failed to load notifications signals: {e}")
            # You might want to log this more robustly in production