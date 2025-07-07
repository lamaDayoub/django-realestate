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
from channels.layers import get_channel_layer 
from django.db.models import Q # Needed for queries in _save_message_to_db and _mark_messages_as_read_in_db

# Import all necessary serializers and models from your app
# Ensure these imports are correct based on your project structure
from .tasks import send_new_message_email 
from .serializers import MessageSerializer, ChatParticipantSerializer, ConversationListSerializer # Explicitly import what's used
from .models import Message, Conversation # Explicitly import what's used

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
        # This consumer is designed to be connected to a specific conversation URL
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation_group_name = f'chat_{self.conversation_id}'
        self.user_presence_group_name = 'user_presence' # Global group for user online status updates
        
        # --- NEW: Add user to their personal conversation list group ---
        # This group is used for sending updates to the user's overall conversation list screen
        self.user_conversation_list_group_name = f'user_{self.user.id}_conversation_list'
        await self.channel_layer.group_add(
            self.user_conversation_list_group_name,
            self.channel_name
        )
        print(f"User {self.user.email} added to conversation list group: {self.user_conversation_list_group_name}")
        # --- END NEW ---

        # 3. Add User to Channels Groups
        # Add user to their specific conversation group (for messages within this chat)
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )
        
        # Add user to the global presence group (for online/offline status updates)
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
        # --- NEW: Remove user from their personal conversation list group ---
        await self.channel_layer.group_discard(
            self.user_conversation_list_group_name,
            self.channel_name
        )
        print(f"User {self.user.email} removed from conversation list group: {self.user_conversation_list_group_name}")
        # --- END NEW ---

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

            # Call the synchronous DB save function. This returns the message object and other DB-derived data.
            # The _save_message_to_db function itself is synchronous, but we await its execution
            # because database_sync_to_async makes it awaitable.
            db_data = await self._save_message_to_db(content, file_url, msg_type)

            if not db_data:
                # Error occurred during DB save, likely conversation not found
                return

            message_obj = db_data['message_obj']
            conversation = db_data['conversation']
            recipient_user = db_data['recipient_user']
            unread_count_for_recipient = db_data['unread_count_for_recipient']
            total_unread_for_recipient = db_data['total_unread_for_recipient']
            
            # --- Prepare message data for direct chat update (already exists) ---
            # This is the message payload sent to the specific chat group
            message_data_for_chat = {
                'id': str(message_obj.id),
                'sender_id': str(self.user.id),
                'sender_first_name': self.user.profile.first_name if self.user.profile else '',
                'sender_last_name': self.user.profile.last_name if self.user.profile else '',
                'sender_photo': self.get_sender_photo_url(self.user),
                'content': message_obj.content,
                'file_url': self.get_file_url(message_obj),
                'message_type': message_obj.message_type,
                'created_at': timezone.localtime(message_obj.created_at).isoformat(),
                'is_read': message_obj.is_read,
            }

            # Send message data to all members of the conversation group (both sender and recipient if in chat)
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'chat_message', # This will call the chat_message method on consumers
                    'message': message_data_for_chat
                }
            )

            # --- Prepare data for real-time conversation list update for both sender and recipient ---
            # Get other participant details for the sender's view (i.e., the recipient's details)
            recipient_profile_for_sender_view = await self.get_user(recipient_user.id) 
            other_participant_details_for_sender = ChatParticipantSerializer(recipient_profile_for_sender_view, context={'request': self.scope}).data

            # Get other participant details for the recipient's view (i.e., the sender's details)
            sender_profile_for_recipient_view = await self.get_user(self.user.id)
            other_participant_details_for_recipient = ChatParticipantSerializer(sender_profile_for_recipient_view, context={'request': self.scope}).data

            # Get conversation's created_at and updated_at for the list update
            conv_created_at = timezone.localtime(conversation.created_at).isoformat()
            conv_updated_at = timezone.localtime(conversation.updated_at).isoformat()

            # Dispatch update for the SENDER's conversation list (last message changed, unread count might be 0)
            await self.channel_layer.group_send(
                f'user_{self.user.id}_conversation_list',
                {
                    'type': 'chat.conversation_update', # Custom type for Flutter to handle
                    'conversation_id': conversation.id,
                    'last_message_data': message_data_for_chat, # The full message data
                    'unread_count_for_this_conversation': 0, # Sender's side will show 0 unread for this message
                    'other_participant_details': other_participant_details_for_sender,
                    'is_new_conversation': False, # Not a new conversation, just an update
                    'created_at': conv_created_at, 
                    'updated_at': conv_updated_at,
                }
            )
            print(f"DEBUG: Dispatched message update to sender's ({self.user.email}) conversation list.")

            # Dispatch update for the RECIPIENT's conversation list (new last message, unread count incremented)
            await self.channel_layer.group_send(
                f'user_{recipient_user.id}_conversation_list',
                {
                    'type': 'chat.conversation_update', # Custom type for Flutter to handle
                    'conversation_id': conversation.id,
                    'last_message_data': message_data_for_chat, # The full message data
                    'unread_count_for_this_conversation': unread_count_for_recipient, # This is the key change for recipient
                    'other_participant_details': other_participant_details_for_recipient,
                    'is_new_conversation': False,
                    'created_at': conv_created_at, 
                    'updated_at': conv_updated_at,
                }
            )
            print(f"DEBUG: Dispatched message update to recipient's ({recipient_user.email}) conversation list.")

            # Update total unread count for the recipient (global badge)
            await self.channel_layer.group_send(
                f'user_{recipient_user.id}_conversation_list',
                {
                    'type': 'chat.total_unread_count_update',
                    'count': total_unread_for_recipient
                }
            )
            print(f"DEBUG: Dispatched total unread count update for recipient ({recipient_user.email}): {total_unread_for_recipient}.")

            # --- Existing email dispatch logic (for offline recipients) ---
            if not recipient_user.is_online: 
                preview_content = ""
                if message_obj.message_type == Message.MessageType.TEXT:
                    preview_content = message_obj.content[:100] + ('...' if len(message_obj.content) > 100 else '') 
                elif message_obj.message_type == Message.MessageType.IMAGE:
                    preview_content = "an image attachment"
                elif message_obj.message_type == Message.MessageType.PDF:
                    preview_content = "a PDF attachment"
                else:
                    preview_content = "an attachment"

                send_new_message_email.delay(
                    recipient_user.id,
                    self.user.id,
                    preview_content
                )
                print(f"Dispatched email task to {recipient_user.email} (offline).")
            # --- END email dispatch ---

            print(f"DEBUG: Message saved. Message ID: {message_obj.id}, File field: '{message_obj.file.name}' (empty if no file)")
        
        elif message_type == 'mark_as_read':
            message_ids_to_mark = data.get('message_ids', [])
            if message_ids_to_mark:
                # Call the synchronous DB mark as read function
                updated_data = await self._mark_messages_as_read_in_db(message_ids_to_mark)
                
                if updated_data:
                    conversation_id = updated_data['conversation_id']
                    conversation = updated_data['conversation'] # Get the conversation object
                    reader_user = updated_data['reader_user']
                    other_participant = updated_data['other_participant']
                    total_unread_for_reader = updated_data['total_unread_for_reader']
                    last_msg_obj = updated_data['last_msg_obj']

                    # Broadcast message read confirmation to the conversation group (for sender's "read" receipt)
                    await self.channel_layer.group_send(
                        self.conversation_group_name,
                        {
                            'type': 'messages_read_confirmation',
                            'reader_user_id': str(reader_user.id),
                            'message_ids': [str(mid) for mid in message_ids_to_mark]
                        }
                    )
                    
                    # Update the conversation list for the current user (reader)
                    last_message_data = MessageSerializer(last_msg_obj, context={'request': self.scope}).data if last_msg_obj else None
                    
                    await self.channel_layer.group_send(
                        f'user_{reader_user.id}_conversation_list',
                        {
                            'type': 'chat.conversation_update',
                            'conversation_id': conversation_id,
                            'last_message_data': last_message_data,
                            'unread_count_for_this_conversation': 0, # Now 0 unread for this conversation for the reader
                            'other_participant_details': ChatParticipantSerializer(other_participant, context={'request': self.scope}).data,
                            'is_new_conversation': False,
                            'created_at': timezone.localtime(conversation.created_at).isoformat(),
                            'updated_at': timezone.localtime(conversation.updated_at).isoformat(),
                        }
                    )
                    print(f"DEBUG: Dispatched real-time conversation update (unread 0) for conv {conversation_id} to {reader_user.email}.")

                    # Update the GLOBAL chat unread count for the current user (reader)
                    await self.channel_layer.group_send(
                        f'user_{reader_user.id}_conversation_list',
                        {
                            'type': 'chat.total_unread_count_update',
                            'count': total_unread_for_reader
                        }
                    )
                    print(f"DEBUG: Dispatched real-time global unread chat count update ({total_unread_for_reader}) to {reader_user.email}.")
        
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
            
    async def chat_conversation_update(self, event):
        """
        Receives updates for a user's conversation list and sends them to the WebSocket.
        This handles:
        - When a new message arrives (updates last_message, unread_count, reorders)
        - When a conversation is created (adds new entry)
        - When messages in a conversation are marked as read (resets unread_count, might reorder)
        """
        await self.send(text_data=json.dumps({
            'type': 'conversation_list_update', # Use a clear type for Flutter
            'conversation_id': event['conversation_id'],
            'last_message_data': event['last_message_data'],
            'unread_count_for_this_conversation': event['unread_count_for_this_conversation'],
            'other_participant_details': event['other_participant_details'],
            'is_new_conversation': event['is_new_conversation'],
            'created_at': event['created_at'], # Pass through created_at
            'updated_at': event['updated_at'], # Pass through updated_at
        }))
        print(f"DEBUG: Sent conversation_list_update to {self.user.email} for conv {event['conversation_id']}.")

    async def chat_total_unread_count_update(self, event):
        """
        Receives updates for a user's total unread chat message count and sends it to the WebSocket.
        """
        await self.send(text_data=json.dumps({
            'type': 'total_unread_chat_count', # Use a clear type for Flutter
            'count': event['count']
        }))
        print(f"DEBUG: Sent total_unread_chat_count to {self.user.email}: {event['count']}.")


    # --- Database Operations (Async-safe) ---
    # These methods interact with the Django ORM and must be wrapped with database_sync_to_async
    # They are synchronous functions that are called from an async context using `await`

    @database_sync_to_async
    def get_user(self, user_id):
        """Fetches a user object from the database, including their profile."""
        try:
            # .select_related('profile') is important to avoid N+1 queries when accessing profile data
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
    def _save_message_to_db(self, content, file_url, message_type):
        """
        Synchronous function to save a new message to the database and
        fetch related data needed for subsequent async operations.
        This function is called by `receive` using `await self._save_message_to_db(...)`.
        """
        # No 'await' calls inside this function, as it's run in a synchronous thread.
        # All ORM operations are synchronous.

        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
        except Conversation.DoesNotExist:
            print(f"Error: Conversation {self.conversation_id} does not exist when saving message.")
            return None

        message = Message(
            conversation=conversation,
            sender=self.user,
            content=content,
            message_type=message_type
        )
        
        if file_url:
            # self.scope is available here because it's part of the consumer instance state
            media_path_prefix = settings.MEDIA_URL 
            expected_prefix = f"{self.scope['scheme']}://{self.scope['host']}{media_path_prefix}"

            if file_url.startswith(expected_prefix):
                relative_path = file_url.split(expected_prefix, 1)[1]
                message.file.name = relative_path
                message.content = None # Clear content if it was only holding the file_url
            else:
                # If the URL is not from our media system, store it directly in content
                message.content = file_url 
                
        message.save()
        
        # Update conversation's updated_at to ensure it bubbles to the top of lists
        conversation.updated_at = timezone.now()
        conversation.save(update_fields=['updated_at'])

        recipient_user = conversation.get_other_participant(self.user)

        # Calculate unread count for the recipient from this sender's messages in this conversation
        unread_count_for_recipient = Message.objects.filter(
            conversation=conversation,
            sender=self.user, # Messages *from* the sender (current user) to the recipient
            is_read=False
        ).count()
        
        # Calculate total unread count for the recipient across all their conversations
        total_unread_for_recipient = Message.objects.filter(
            Q(conversation__participant1=recipient_user) | Q(conversation__participant2=recipient_user),
            is_read=False
        ).exclude(sender=recipient_user).count()

        # Return all necessary data to the calling async function (`receive`)
        return {
            'message_obj': message,
            'conversation': conversation,
            'recipient_user': recipient_user,
            'unread_count_for_recipient': unread_count_for_recipient,
            'total_unread_for_recipient': total_unread_for_recipient,
        }

    @database_sync_to_async
    def _mark_messages_as_read_in_db(self, message_ids):
        """
        Synchronous function to mark a list of messages as read for the current user in a conversation.
        This function is called by `receive` using `await self._mark_messages_as_read_in_db(...)`.
        """
        # No 'await' calls inside this function.

        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
        except Conversation.DoesNotExist:
            print(f"Error: Conversation {self.conversation_id} not found when marking messages as read.")
            return None

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
        
        # Update conversation's updated_at to ensure it bubbles to the top of lists
        conversation.updated_at = timezone.now()
        conversation.save(update_fields=['updated_at'])

        # Get total unread count for the current user (reader) across all their conversations
        total_unread_for_reader = Message.objects.filter(
            Q(conversation__participant1=self.user) | Q(conversation__participant2=self.user),
            is_read=False
        ).exclude(sender=self.user).count()

        # Get the latest message for the conversation to update the list view
        last_msg_obj = conversation.messages.order_by('-created_at').first()

        # Return all necessary data to the calling async function (`receive`)
        return {
            'conversation_id': self.conversation_id,
            'conversation': conversation, # Pass the conversation object as well
            'reader_user': self.user,
            'other_participant': other_participant,
            'total_unread_for_reader': total_unread_for_reader,
            'last_msg_obj': last_msg_obj,
            'updated_count': updated_count # Optional, for logging
        }

    # --- Helper Functions (not async, do not touch DB directly) ---
    # These functions are synchronous and do not interact with the database directly.
    # They are safe to call from both async and sync contexts (e.g., from _save_message_to_db or receive).
            
    def get_sender_photo_url(self, user):
        """Constructs the absolute URL for a user's profile photo."""
        # self.scope is available here as it's part of the consumer instance
        if user.profile and user.profile.photo:
            base_url = f"{self.scope['scheme']}://{self.scope['host']}"
            # user.profile.photo.url already starts with MEDIA_URL, e.g., '/media/userphotos/...'
            return f"{base_url}{user.profile.photo.url}" 
        return None
    
    def get_file_url(self, message_obj):
        """Constructs the absolute URL for a message file."""
        # self.scope is available here as it's part of the consumer instance
        if message_obj.file:
            base_url = f"{self.scope['scheme']}://{self.scope['host']}"
            # message_obj.file.url already starts with MEDIA_URL, e.g., '/media/messages/...'
            return f"{base_url}{message_obj.file.url}"
        return None
