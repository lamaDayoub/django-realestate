
# # realestate/asgi.py
# import os

# # Set DJANGO_SETTINGS_MODULE FIRST
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings')

# # Initialize Django ASGI application early to ensure the AppRegistry
# # is populated before importing code that may import ORM models.
# from django.core.asgi import get_asgi_application
# django_asgi_app = get_asgi_application()

# # Now you can safely import other Django/Channels components
# from channels.routing import ProtocolTypeRouter, URLRouter
# # from channels.security.websocket import AllowedHostsOriginValidator # <-- REMOVE THIS LINE ENTIRELY

# from realestate.channels_middleware import TokenAuthMiddlewareStack
# from chat import routing 

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": TokenAuthMiddlewareStack( # <-- NOW DIRECTLY WRAP with your custom middleware
#         URLRouter(routing.websocket_urlpatterns)
#     ),
# })

# realestate/asgi.py
import os

# Set DJANGO_SETTINGS_MODULE FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
from django.core.asgi import get_asgi_application
django_asgi_app = get_asgi_application()

# Now you can safely import other Django/Channels components
from channels.routing import ProtocolTypeRouter, URLRouter
# No need for AllowedHostsOriginValidator here, as we removed it previously.
from realestate.channels_middleware import TokenAuthMiddlewareStack 

# --- NEW: Import both chat and notifications routing ---
from chat import routing as chat_routing # Alias chat routing to avoid name collision
from notifications import routing as notifications_routing # <--- NEW: Import notifications routing
# --- END NEW ---

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": TokenAuthMiddlewareStack(
        URLRouter([
            # --- Include chat WebSocket URLs ---
            *chat_routing.websocket_urlpatterns, # Use the * operator to unpack the list
            # --- NEW: Include notifications WebSocket URLs ---
            *notifications_routing.websocket_urlpatterns, # <--- NEW: Unpack notification URLs
            # --- END NEW ---
        ])
    ),
})