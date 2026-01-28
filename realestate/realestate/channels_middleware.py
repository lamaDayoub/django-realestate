# realestate/channels_middleware.py
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser 
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
import urllib.parse

@database_sync_to_async
def get_user_from_token(token_key):
    """
    Attempts to authenticate a user using a JWT token.
    """
    try:
        access_token = AccessToken(token_key)
        user_id = access_token['user_id']
        User = get_user_model() 
        user = User.objects.select_related('profile').get(id=user_id)
        if not user.is_active:
            return AnonymousUser() # User exists but is inactive
        return user
    except (InvalidToken, TokenError, KeyError, User.DoesNotExist):
       
        return AnonymousUser() # Token invalid, expired, or user not found

class TokenAuthMiddleware:
    """
    Custom middleware to authenticate users using a JWT token from the query string.
    """
    def __init__(self, inner):
        # Store the ASGI application we're wrapping
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Check if it's a WebSocket handshake
        if scope['type'] == 'websocket':
            query_string = scope['query_string'].decode('utf-8')
            params = urllib.parse.parse_qs(query_string)
            token = params.get('token', [None])[0]

            if token:
                # Authenticate the user asynchronously
                scope['user'] = await get_user_from_token(token)
            else:
                scope['user'] = AnonymousUser() # No token, so set as anonymous

        # Call the next ASGI application in the stack
        return await self.inner(scope, receive, send)

# Helper function to apply the middleware
def TokenAuthMiddlewareStack(inner):
    return TokenAuthMiddleware(inner)