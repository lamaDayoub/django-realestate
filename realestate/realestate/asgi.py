# realestate/asgi.py
# import os
# from django.core.asgi import get_asgi_application
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.security.websocket import AllowedHostsOriginValidator
# from channels.auth import AuthMiddlewareStack

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings') 

# django_asgi_app = get_asgi_application()
# from chat import routing # Import routing after django_asgi_app

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AllowedHostsOriginValidator(
#         AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns))
#     ),
# })
# realestate/asgi.py
# import os
# from django.core.asgi import get_asgi_application
# from channels.routing import ProtocolTypeRouter, URLRouter
# # from channels.auth import AuthMiddlewareStack # REMOVE THIS LINE
# from channels.security.websocket import AllowedHostsOriginValidator # KEEP FOR NOW, BUT BE AWARE

# # Import your custom middleware
# from realestate.channels_middleware import TokenAuthMiddlewareStack 

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings') # Ensure this is 'realestate.settings'

# django_asgi_app = get_asgi_application()
# from chat import routing 

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AllowedHostsOriginValidator( # Keep this for now, but if 403 persists, remove it.
#         TokenAuthMiddlewareStack( # Use your custom JWT authentication middleware
#             URLRouter(routing.websocket_urlpatterns)
#         )
#     ),
# })

# realestate/asgi.py
# import os
# from django.core.asgi import get_asgi_application
# # from channels.auth import AuthMiddlewareStack # REMOVE THIS LINE
# from channels.security.websocket import AllowedHostsOriginValidator 
# from channels.routing import ProtocolTypeRouter, URLRouter
# # Import your custom middleware
# from realestate.channels_middleware import TokenAuthMiddlewareStack # <-- This import is happening too early

# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings')

# django_asgi_app = get_asgi_application() # <-- Django setup happens here

# from chat import routing # This import MUST be after django_asgi_app

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AllowedHostsOriginValidator( 
#         TokenAuthMiddlewareStack( 
#             URLRouter(routing.websocket_urlpatterns)
#         )
#     ),
# })

# realestate/asgi.py
# import os

# # Set DJANGO_SETTINGS_MODULE FIRST
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'realestate.settings')

# # Initialize Django ASGI application early to ensure the AppRegistry
# # is populated before importing code that may import ORM models.
# from django.core.asgi import get_asgi_application
# django_asgi_app = get_asgi_application()

# # Now you can safely import other Django/Channels components
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.security.websocket import AllowedHostsOriginValidator 
# from realestate.channels_middleware import TokenAuthMiddlewareStack
# from chat import routing # This import also needs to be AFTER get_asgi_application()

# application = ProtocolTypeRouter({
#     "http": django_asgi_app,
#     "websocket": AllowedHostsOriginValidator( 
#         TokenAuthMiddlewareStack( 
#             URLRouter(routing.websocket_urlpatterns)
#         )
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
# from channels.security.websocket import AllowedHostsOriginValidator # <-- REMOVE THIS LINE ENTIRELY

from realestate.channels_middleware import TokenAuthMiddlewareStack
from chat import routing 

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": TokenAuthMiddlewareStack( # <-- NOW DIRECTLY WRAP with your custom middleware
        URLRouter(routing.websocket_urlpatterns)
    ),
})