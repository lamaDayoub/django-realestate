# notifications/consumers.py
import json
import urllib.parse

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.utils import timezone # <--- NEW: Import timezone

from .models import Notification 

User = get_user_model()

class NotificationConsumer(AsyncWebsocketConsumer):
    # We need a global tracker for notification connections too,
    # similar to ChatConsumer's online_users.
    # This helps determine if a user has ANY active notification connection.
    notification_online_users = {} # Key: user_id, Value: set of channel_names

    async def connect(self):
        """
        Handles new WebSocket connections for notifications.
        Authenticates the user, adds them to their personal notification group,
        and updates their overall online status.
        """
        print(f"DEBUG: NotificationConsumer connect called for channel {self.channel_name}") # <--- NEW DEBUG
        query_string = self.scope['query_string'].decode('utf-8')
        params = urllib.parse.parse_qs(query_string)
        token = params.get('token', [None])[0]

        if not token:
            print("Notification Authentication failed: No token provided.")
            await self.close(code=4001) 
            return

        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            self.user = await self.get_user(user_id)

            if not self.user or not self.user.is_active:
                print(f"Notification Authentication failed: User {user_id} not found or inactive.")
                await self.close(code=4002) 
                return

        except (InvalidToken, TokenError, KeyError) as e:
            print(f"Notification Authentication failed: Invalid or expired token. Error: {e}")
            await self.close(code=4003) 
            return
        except Exception as e:
            print(f"Notification Authentication failed: General error - {e}")
            await self.close(code=4004) 
            return

        self.scope['user'] = self.user 

        self.notification_group_name = f'user_{self.user.id}_notifications'

        await self.channel_layer.group_add(
            self.notification_group_name,
            self.channel_name
        )

        # --- NEW LOGIC: Update User's Online Status (for Notification Consumer) ---
        # Add current channel to the set of notification connections for this user
        if self.user.id not in self.notification_online_users:
            self.notification_online_users[self.user.id] = set()
        self.notification_online_users[self.user.id].add(self.channel_name)

        # If this is the FIRST notification connection for this user, update is_online
        if len(self.notification_online_users[self.user.id]) == 1:
            await self.update_user_status(True) # Set is_online = True, last_seen = None
            # No need to broadcast here, ChatConsumer already handles global presence updates.
            # If ChatConsumer is not used, you'd broadcast from here.
        # --- END NEW LOGIC ---

        await self.accept()
        print(f"User {self.user.email} (ID: {self.user.id}) connected to Notification WebSocket.")

    async def disconnect(self, close_code):
        """
        Handles WebSocket disconnections for notifications.
        Removes user from their personal notification group and updates overall online status.
        """
        print(f"DEBUG: NotificationConsumer disconnect called for channel {self.channel_name}") # <--- NEW DEBUG
        print(f"User {self.user.email} (ID: {self.user.id}) disconnecting from Notification WebSocket with code {close_code}.")
        await self.channel_layer.group_discard(
            self.notification_group_name,
            self.channel_name
        )

        # --- NEW LOGIC: Update User's Online Status on Disconnect ---
        if self.user.id in self.notification_online_users:
            self.notification_online_users[self.user.id].discard(self.channel_name) # Remove this channel

            # If this was the LAST notification connection for this user, update is_online
            if not self.notification_online_users[self.user.id]:
                del self.notification_online_users[self.user.id] # Remove user from tracking
                await self.update_user_status(False) # Set is_online = False, update last_seen
                # No need to broadcast here, ChatConsumer already handles global presence updates.
        # --- END NEW LOGIC ---


    async def receive(self, text_data):
        # ... (existing receive method) ...
        print(f"Notification consumer received unexpected message from {self.user.email}: {text_data}")
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'ping':
                # Respond to a ping to keep connection alive
                await self.send(text_data=json.dumps({'type': 'pong'}))
                print(f"DEBUG: Sent pong to {self.user.email}.")
            # Add other client-initiated actions here if needed in the future
            # elif message_type == 'mark_single_read':
            #    notification_id = data.get('notification_id')
            #    await self.mark_single_notification_read(notification_id)
            else:
                print(f"Notification consumer received unknown message type from {self.user.email}: {message_type}")
                await self.send(text_data=json.dumps({'error': 'Unknown message type', 'type_received': message_type}))

        except json.JSONDecodeError:
            print(f"Notification consumer received invalid JSON from {self.user.email}: {text_data}")
            await self.send(text_data=json.dumps({'error': 'Invalid JSON format'}))



    # --- Channel Layer Message Handlers ---

    async def notification_message(self, event):
        # ... (existing notification_message handler) ...
        print(f"DEBUG: Notification consumer received 'notification.message' for user {self.user.email}.")
        await self.send(text_data=json.dumps(event['notification']))

    async def notification_unread_count_update(self, event):
        # ... (existing notification_unread_count_update handler) ...
        print(f"DEBUG: Notification consumer received 'notification.unread_count_update' for user {self.user.email}. New count: {event['count']}.")
        await self.send(text_data=json.dumps({
            'type': 'notification.unread_count_update',
            'count': event['count']
        }))

    # --- Database Operations (Async-safe) ---
    @database_sync_to_async
    def get_user(self, user_id):
        """Fetches a user object from the database, including their profile."""
        try:
            # Select related profile to avoid N+1 when accessing user.profile
            return User.objects.select_related('profile').get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def update_user_status(self, online):
        """Updates a user's is_online status and last_seen timestamp in the database."""
        user = self.user
        user.is_online = online
        if not online:
            user.last_seen = timezone.now()
        user.save(update_fields=['is_online', 'last_seen'])
        print(f"DEBUG: NotificationConsumer updated user {user.email} is_online to {online}.")