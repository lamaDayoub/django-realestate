# chat/consumers.py
import json
import urllib.parse
import os
import uuid

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    # This in-memory dictionary stores active connections for presence tracking
    # Key: user_id (str), Value: channel_name (str)
    # This works for single Daphne process. For multiple processes, a shared backend (like Redis) is needed for this as well.
    online_users = {} 

    async def connect(self):
        """
        Handles new WebSocket connections.
        Authenticates the user using a JWT token provided in the URL query string.
        Sets user as online and adds them to relevant Channel groups.
        """
        # 1. Extract and Validate JWT Token
        query_string = self.scope['query_string'].decode('utf-8')
        params = urllib.parse.parse_qs(query_string)
        token = params.get('token', [None])[0]

        if not token:
            print("Authentication failed: No token provided.")
            await self.close(code=4001) # 4001: Unauthorized - No token
            return

        try:
            # Validate and decode JWT access token
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            # Fetch user details from database (async operation)
            self.user = await self.get_user(user_id)

            if not self.user or not self.user.is_active:
                print(f"Authentication failed: User {user_id} not found or inactive.")
                await self.close(code=4002) # 4002: User not found or inactive
                return

        except (InvalidToken, TokenError, KeyError) as e:
            print(f"Authentication failed: Invalid or expired token. Error: {e}")
            await self.close(code=4003) # 4003: Invalid or expired token
            return
        except Exception as e:
            print(f"Authentication failed: General error - {e}")
            await self.close(code=4004) # 4004: General authentication error
            return

        # Attach the authenticated user to the scope for later use in consumer methods
        self.scope['user'] = self.user

        # 2. Get Conversation ID from URL Route
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation_group_name = f'chat_{self.conversation_id}'
        self.user_presence_group_name = 'user_presence' # Global group for user online status updates

        # 3. Add User to Channel Groups
        # Add user to their specific conversation group
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )
        
        # Add user to the global presence group
        await self.channel_layer.group_add(
            self.user_presence_group_name,
            self.channel_name
        )

        # 4. Update User's Online Status in Database and Broadcast
        # Check if this is the first connection for this user (to avoid redundant updates/broadcasts)
        if self.user.id not in self.online_users:
            self.online_users[self.user.id] = self.channel_name # Store channel name for this user
            await self.update_user_status(True) # Set is_online = True, last_seen = None
            # Broadcast online status to all clients in the user_presence group
            await self.channel_layer.group_send(
                self.user_presence_group_name,
                {
                    'type': 'user_status_update', # This calls the user_status_update method below
                    'user_id': str(self.user.id),
                    'is_online': True,
                    'last_seen': None # No last_seen when online
                }
            )
        else:
            # If user is already "online" (connected on another channel/device), just update this connection
            self.online_users[self.user.id] = self.channel_name

        # 5. Accept the WebSocket connection
        await self.accept()
        print(f"User {self.user.email} (ID: {self.user.id}) connected to conversation {self.conversation_id}")

    async def disconnect(self, close_code):
        """
        Handles WebSocket disconnections.
        Removes user from Channel groups and updates user's online status to offline.
        """
        print(f"User {self.user.email} (ID: {self.user.id}) disconnecting from conversation {self.conversation_id} with code {close_code}")

        # 1. Remove User from Channel Groups
        await self.channel_layer.group_discard(
            self.conversation_group_name,
            self.channel_name
        )
        await self.channel_layer.group_discard(
            self.user_presence_group_name,
            self.channel_name
        )

        # 2. Update User's Offline Status in Database and Broadcast
        # Only set offline if this was the last active connection for the user
        if self.user.id in self.online_users and self.online_users[self.user.id] == self.channel_name:
            del self.online_users[self.user.id] # Remove from tracking
            await self.update_user_status(False) # Set is_online = False, update last_seen
            # Broadcast offline status to all clients in the user_presence group
            await self.channel_layer.group_send(
                self.user_presence_group_name,
                {
                    'type': 'user_status_update', # This calls the user_status_update method below
                    'user_id': str(self.user.id),
                    'is_online': False,
                    # Convert last_seen to ISO format for consistent sending (Damascus time)
                    'last_seen': timezone.localtime(self.user.last_seen).isoformat() if self.user.last_seen else None
                }
            )
        else:
            # If the user has other active connections, they remain "online"
            print(f"User {self.user.email} still has other active connections.")


    async def receive(self, text_data):
        """
        Receives messages from the WebSocket connection and routes them based on 'type'.
        """
        data = json.loads(text_data)
        message_type = data.get('type') # e.g., "chat_message", "mark_as_read", "typing"

        if message_type == 'chat_message':
            content = data.get('content')
            file_url = data.get('file_url')
            msg_type = data.get('message_type', 'text') # default to 'text'

            if not (content or file_url):
                print("Received empty message or file_url for 'chat_message' type.")
                return

            # Save message to database
            message_obj = await self.save_message(content, file_url, msg_type)
            if not message_obj:
                # Error saving message, perhaps conversation doesn't exist
                return

            # Prepare message data to be sent to clients (using a simplified serialization)
            # This mimics the data format of your MessageSerializer
            message_data = {
                'id': str(message_obj.id),
                'sender_id': str(self.user.id),
                'sender_first_name': self.user.profile.first_name if self.user.profile else '',
                'sender_last_name': self.user.profile.last_name if self.user.profile else '',
                'sender_photo': self.get_sender_photo_url(self.user),
                'content': message_obj.content,
                'file_url': self.get_file_url(message_obj),
                'message_type': message_obj.message_type,
                'created_at': timezone.localtime(message_obj.created_at).isoformat(), # Format to ISO 8601
                'is_read': message_obj.is_read,
            }

            # Send message data to all members of the conversation group
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'chat_message', # This will call the chat_message method on consumers
                    'message': message_data
                }
            )
            
        elif message_type == 'mark_as_read':
            message_ids_to_mark = data.get('message_ids', [])
            if message_ids_to_mark:
                await self.mark_messages_as_read(message_ids_to_mark)
                
                # Optionally, broadcast message read confirmation to the conversation group
                # This helps the sender know their messages were read
                await self.channel_layer.group_send(
                    self.conversation_group_name,
                    {
                        'type': 'messages_read_confirmation',
                        'reader_user_id': str(self.user.id),
                        'message_ids': [str(mid) for mid in message_ids_to_mark] # Ensure IDs are strings
                    }
                )
            
        elif message_type == 'typing':
            is_typing = data.get('is_typing', False)
            # Broadcast typing status to the conversation group (excluding sender)
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'typing_status',
                    'user_id': str(self.user.id),
                    'is_typing': is_typing
                }
            )
        else:
            print(f"Unknown message type received: {message_type}")


    # --- Channel Layer Message Handlers ---
    # These methods are called when a message is sent to a group the consumer is in.

    async def chat_message(self, event):
        """Receives a chat message from the channel layer and sends it to the WebSocket."""
        # The 'message' key contains the serialized message data
        print(f"DEBUG: chat_message handler called for user {self.user.email} in conv {self.conversation_id}. Message: {event['message']['content']}")
        await self.send(text_data=json.dumps(event['message']))

    async def user_status_update(self, event):
        """Receives user status updates and sends them to the WebSocket."""
        # Only send if the update is NOT for the current user, or if it's for this user
        # but indicates they're going offline (useful for other devices)
        if str(event['user_id']) != str(self.user.id) or not event['is_online']:
            await self.send(text_data=json.dumps({
                'type': 'user_status_update',
                'user_id': event['user_id'],
                'is_online': event['is_online'],
                'last_seen': event['last_seen']
            }))

    async def messages_read_confirmation(self, event):
        """Receives read confirmations and sends them to the WebSocket."""
        # This is useful for the sender to know their messages were read
        await self.send(text_data=json.dumps({
            'type': 'messages_read_confirmation',
            'reader_user_id': event['reader_user_id'],
            'message_ids': event['message_ids']
        }))
        
    async def typing_status(self, event):
        """Receives typing status updates and sends them to the WebSocket."""
        # Do not send typing status back to the user who is typing
        if str(event['user_id']) != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'typing_status',
                'user_id': event['user_id'],
                'is_typing': event['is_typing']
            }))

    # --- Database Operations (Async-safe) ---
    # These methods interact with the Django ORM and must be wrapped with database_sync_to_async

    @database_sync_to_async
    def get_user(self, user_id):
        """Fetches a user object from the database, including their profile."""
        try:
            return User.objects.select_related('profile').get(id=user_id)
        except User.DoesNotExist:
            return None

    @database_sync_to_async
    def update_user_status(self, online):
        """Updates a user's online status and last_seen timestamp."""
        user = self.user
        user.is_online = online
        if not online:
            user.last_seen = timezone.now()
        user.save(update_fields=['is_online', 'last_seen'])
        
    @database_sync_to_async
    def save_message(self, content, file_url, message_type):
        """Saves a new message to the database."""
        from chat.models import Message, Conversation # Import models locally
        from django.core.files.storage import default_storage
        
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
        except Conversation.DoesNotExist:
            print(f"Error: Conversation {self.conversation_id} does not exist when saving message.")
            return None

        message = Message(
            conversation=conversation,
            sender=self.user,
            content=content, # Initial content (text or file_url temporarily)
            message_type=message_type
        )
        
        if file_url:
            # If a file_url is provided, it means the file was already uploaded via HTTP API.
            # We need to correctly link this pre-uploaded file to the Message model's FileField.
            # The file_url should be an absolute URL pointing to a file within MEDIA_ROOT.
            
            # Example file_url: "http://localhost:8000/media/messages/uploads/some_file.jpg"
            # We need to extract the path relative to MEDIA_ROOT: "messages/uploads/some_file.jpg"
            
            # Construct the expected base path for MEDIA_URL
            media_path_prefix = settings.MEDIA_URL 
            
            # Check if the file_url starts with the expected host and media URL prefix
            # This is to ensure we're dealing with a file hosted by our Django app
            expected_prefix = f"{self.scope['scheme']}://{self.scope['host']}{media_path_prefix}"

            if file_url.startswith(expected_prefix):
                relative_path = file_url.split(expected_prefix, 1)[1]
                # Assign the relative path to the FileField. Django will handle the rest.
                # It does not re-upload the file, but points the FileField to the existing one.
                message.file.name = relative_path
                # Clear content if it was only holding the file_url
                message.content = None 
            else:
                print(f"Warning: File URL {file_url} does not match expected MEDIA_URL pattern. Storing URL in content field.")
                # If the URL is not from our media system, store it directly in content
                # This could be for external links, but for internal files, the above is preferred.
                message.content = file_url 
                
        message.save()
        return message

    @database_sync_to_async
    def mark_messages_as_read(self, message_ids):
        """Marks a list of messages as read for the current user in a conversation."""
        from chat.models import Message, Conversation # Import models locally
        
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
        except Conversation.DoesNotExist:
            print(f"Error: Conversation {self.conversation_id} not found when marking messages as read.")
            return

        # Identify the other participant in this conversation
        # Only mark messages SENT BY THE OTHER PARTICIPANT as read by the CURRENT USER
        other_participant = conversation.get_other_participant(self.user)

        messages_to_mark = Message.objects.filter(
            conversation=conversation,
            sender=other_participant, # Only messages from the other person
            id__in=message_ids,      # Only messages in the provided list
            is_read=False            # Only unread messages
        )
        updated_count = messages_to_mark.update(is_read=True)
        print(f"Marked {updated_count} messages as read for conversation {self.conversation_id}.")

    # --- Helper Functions (not async, do not touch DB directly) ---
            
    def get_sender_photo_url(self, user):
        """Constructs the absolute URL for a user's profile photo."""
        if user.profile and user.profile.photo:
            base_url = f"{self.scope['scheme']}://{self.scope['host']}"
            # user.profile.photo.url already starts with MEDIA_URL, e.g., '/media/userphotos/...'
            return f"{base_url}{user.profile.photo.url}" 
        return None
    
    def get_file_url(self, message_obj):
        """Constructs the absolute URL for a message file."""
        if message_obj.file:
            base_url = f"{self.scope['scheme']}://{self.scope['host']}"
            # message_obj.file.url already starts with MEDIA_URL, e.g., '/media/messages/...'
            return f"{base_url}{message_obj.file.url}"
        return None