
# chat/consumers.py
import json
import urllib.parse
import os
import uuid
import asyncio
import collections # Import collections for defaultdict

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from channels.layers import get_channel_layer
from django.db.models import Q, Count # Import Count for get_aggregation

# Import all necessary serializers and models from your app
from .tasks import send_new_message_email
from .serializers import MessageSerializer, ChatParticipantSerializer, ConversationListSerializer
from .models import Message, Conversation

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    # This dictionary now stores a SET of channel_names for each user_id.
    # This allows tracking multiple active connections for the same user.
    # Using defaultdict ensures that each user_id automatically gets an empty set if not present.
    online_users = collections.defaultdict(set)

    async def connect(self):
        """
        Handles new WebSocket connections.
        Authenticates the user using a JWT token provided in the URL query string.
        Sets user as online and adds them to relevant Channel groups.
        """
        self.user = None # Initialize user to None
        print(f"DEBUG: [CONNECT] New connection attempt from {self.scope['client']}")

        # 1. Extract and Validate JWT Token
        query_string = self.scope['query_string'].decode('utf-8')
        params = urllib.parse.parse_qs(query_string)
        token = params.get('token', [None])[0]

        if not token:
            print("ERROR: [CONNECT] Authentication failed: No token provided in query string.")
            await self.close(code=4001) # 4001: Unauthorized - No token
            return

        try:
            print(f"DEBUG: [CONNECT] Attempting to validate token: {token[:30]}...") # Print first 30 chars
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            print(f"DEBUG: [CONNECT] Token validated. User ID: {user_id}")

            # Fetch user details from database (async operation)
            self.user = await self.get_user(user_id)

            if not self.user or not self.user.is_active:
                print(f"ERROR: [CONNECT] Authentication failed: User {user_id} not found or inactive.")
                await self.close(code=4002) # 4002: User not found or inactive
                return

            print(f"DEBUG: [CONNECT] User {self.user.email} (ID: {self.user.id}) fetched successfully.")

        except (InvalidToken, TokenError, KeyError) as e:
            print(f"ERROR: [CONNECT] Authentication failed: Invalid or expired token. Error: {type(e).__name__}: {e}")
            await self.close(code=4003) # 4003: Invalid or expired token
            return
        except Exception as e:
            print(f"ERROR: [CONNECT] Authentication failed: General error during token validation or user fetch - {type(e).__name__}: {e}")
            await self.close(code=4004) # 4004: General authentication error
            return

        # Attach the authenticated user to the scope for later use in consumer methods
        self.scope['user'] = self.user

        # 2. Get Conversation ID from URL Route
        try:
            self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
            self.conversation_group_name = f'chat_{self.conversation_id}'
            self.user_presence_group_name = 'user_presence' # Global group for user online status updates
            self.user_conversation_list_group_name = f'user_{self.user.id}_conversation_list'
            print(f"DEBUG: [CONNECT] Conversation ID: {self.conversation_id}, Conversation Group: {self.conversation_group_name}")
        except KeyError as e:
            print(f"ERROR: [CONNECT] Missing conversation_id in URL route kwargs: {e}")
            await self.close(code=4005) # Invalid URL parameter
            return
        except Exception as e:
            print(f"ERROR: [CONNECT] Unexpected error getting conversation ID: {type(e).__name__}: {e}")
            await self.close(code=4006)
            return

        # 3. Add User to Channels Groups
        try:
            print(f"DEBUG: [CONNECT] Adding user {self.user.id} to groups...")
            await self.channel_layer.group_add(
                self.user_conversation_list_group_name,
                self.channel_name
            )
            print(f"DEBUG: [CONNECT] User {self.user.email} added to conversation list group: {self.user_conversation_list_group_name}")

            await self.channel_layer.group_add(
                self.conversation_group_name,
                self.channel_name
            )
            print(f"DEBUG: [CONNECT] User {self.user.email} added to conversation group: {self.conversation_group_name}")

            await self.channel_layer.group_add(
                self.user_presence_group_name,
                self.channel_name
            )
            print(f"DEBUG: [CONNECT] User {self.user.email} added to user presence group: {self.user_presence_group_name}")

        except Exception as e:
            print(f"ERROR: [CONNECT] Failed to add user to channel groups: {type(e).__name__}: {e}")
            await self.close(code=4007) # Failed to join groups
            return

        # 4. Update User's Online Status in Database and Broadcast (Multi-connection aware)
        try:
            # Check if this is the first connection for this user
            was_offline = not self.online_users[self.user.id] # True if set was empty
            self.online_users[self.user.id].add(self.channel_name) # Add current channel to the set

            if was_offline:
                print(f"DEBUG: [CONNECT] User {self.user.id} was offline, now connecting. Setting status to online.")
                await self.update_user_status(True) # Set is_online = True, last_seen = None
                # Broadcast online status to all clients in the user_presence group
                await self.channel_layer.group_send(
                    self.user_presence_group_name,
                    {
                        'type': 'user_status_update',
                        'user_id': str(self.user.id),
                        'is_online': True,
                        'last_seen': None # No last_seen when online
                    }
                )
                print(f"DEBUG: [CONNECT] Broadcasted online status for user {self.user.email}.")
            else:
                print(f"DEBUG: [CONNECT] User {self.user.id} already has active connections. Not changing global status.")
            print(f"DEBUG: [CONNECT] User {self.user.id} now has {len(self.online_users[self.user.id])} active connections.")

        except Exception as e:
            print(f"ERROR: [CONNECT] Failed to update/broadcast user status: {type(e).__name__}: {e}")
            # Do not close connection here, as it might still be usable for chat, just status update failed.

        # 5. Accept the WebSocket connection
        await self.accept()
        print(f"DEBUG: [CONNECT] WebSocket connection accepted for User {self.user.email} (ID: {self.user.id}) to conversation {self.conversation_id}")

    async def disconnect(self, close_code):
        """
        Handles WebSocket disconnections.
        Removes user from Channel groups and updates user's online status to offline.
        """
        if not hasattr(self, 'user') or not self.user:
            print(f"WARNING: [DISCONNECT] Disconnect called for unauthenticated or missing user. Close code: {close_code}")
            return

        print(f"DEBUG: [DISCONNECT] User {self.user.email} (ID: {self.user.id}) disconnecting from conversation {self.conversation_id} with code {close_code}")

        # 1. Remove User from Channel Groups
        try:
            print(f"DEBUG: [DISCONNECT] Removing user {self.user.id} from groups...")
            await self.channel_layer.group_discard(
                self.conversation_group_name,
                self.channel_name
            )
            print(f"DEBUG: [DISCONNECT] User {self.user.email} removed from conversation group: {self.conversation_group_name}")

            await self.channel_layer.group_discard(
                self.user_presence_group_name,
                self.channel_name
            )
            print(f"DEBUG: [DISCONNECT] User {self.user.email} removed from user presence group: {self.user_presence_group_name}")

            await self.channel_layer.group_discard(
                self.user_conversation_list_group_name,
                self.channel_name
            )
            print(f"DEBUG: [DISCONNECT] User {self.user.email} removed from conversation list group: {self.user_conversation_list_group_name}")
        except Exception as e:
            print(f"ERROR: [DISCONNECT] Failed to remove user from channel groups: {type(e).__name__}: {e}")

        # 2. Update User's Offline Status in Database and Broadcast (Multi-connection aware)
        try:
            # Remove this specific channel from the user's active connections set
            if self.channel_name in self.online_users[self.user.id]:
                self.online_users[self.user.id].remove(self.channel_name)
                print(f"DEBUG: [DISCONNECT] Removed channel {self.channel_name} for user {self.user.id}.")

            # If the set becomes empty, the user is truly offline
            if not self.online_users[self.user.id]:
                print(f"DEBUG: [DISCONNECT] User {self.user.id} has no more active connections. Setting status to offline.")
                # Clean up the empty set entry to prevent defaultdict from growing indefinitely with old user IDs
                del self.online_users[self.user.id]
                await self.update_user_status(False) # Set is_online = False, update last_seen
                # Broadcast offline status to all clients in the user_presence group
                await self.channel_layer.group_send(
                    self.user_presence_group_name,
                    {
                        'type': 'user_status_update',
                        'user_id': str(self.user.id),
                        'is_online': False,
                        'last_seen': timezone.localtime(self.user.last_seen).isoformat() if self.user.last_seen else None
                    }
                )
                print(f"DEBUG: [DISCONNECT] Broadcasted offline status for user {self.user.email}.")
            else:
                print(f"DEBUG: [DISCONNECT] User {self.user.email} still has {len(self.online_users[self.user.id])} other active connections. Not setting offline.")
        except Exception as e:
            print(f"ERROR: [DISCONNECT] Failed to update/broadcast user offline status: {type(e).__name__}: {e}")


    async def receive(self, text_data):
        """
        Receives messages from the WebSocket connection and routes them based on 'type'.
        """
        if not hasattr(self, 'user') or not self.user:
            print(f"ERROR: [RECEIVE] Received message from unauthenticated user. Closing connection.")
            await self.close(code=4003) # Unauthorized
            return

        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            print(f"DEBUG: [RECEIVE] Received message of type '{message_type}' from user {self.user.email}.")
        except json.JSONDecodeError as e:
            print(f"ERROR: [RECEIVE] Invalid JSON received from {self.user.email}: {e}. Data: {text_data[:100]}...")
            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Invalid JSON format.'}))
            return
        except Exception as e:
            print(f"ERROR: [RECEIVE] Unexpected error parsing message from {self.user.email}: {type(e).__name__}: {e}. Data: {text_data[:100]}...")
            await self.send(text_data=json.dumps({'type': 'error', 'message': 'Internal server error processing message.'}))
            return

        if message_type == 'chat_message':
            content = data.get('content')
            file_url = data.get('file_url')
            msg_type = data.get('message_type', 'text') # default to 'text'

            print(f"DEBUG: [RECEIVE - chat_message] Content: '{content[:50] if content else 'N/A'}', File URL: '{file_url}', Type: '{msg_type}'")

            if not (content or file_url):
                print("WARNING: [RECEIVE - chat_message] Received empty message or file_url for 'chat_message' type.")
                await self.send(text_data=json.dumps({'type': 'error', 'message': 'Message content or file URL is required.'}))
                return

            try:
                # _save_message_to_db no longer needs scheme and host as arguments
                db_data = await self._save_message_to_db(content, file_url, msg_type)

                if not db_data:
                    print(f"ERROR: [RECEIVE - chat_message] _save_message_to_db returned None. Likely conversation not found or DB error. User: {self.user.email}, Conv ID: {self.conversation_id}")
                    await self.send(text_data=json.dumps({'type': 'error', 'message': 'Failed to save message. Conversation not found or internal error.'}))
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
                    'sender_first_name': self.user.profile.first_name if hasattr(self.user, 'profile') and self.user.profile else '',
                    'sender_last_name': self.user.profile.last_name if hasattr(self.user, 'profile') and self.user.profile else '',
                    # Use consumer's helper methods to get absolute URLs
                    'sender_photo': self.get_sender_photo_url(self.user),
                    'content': message_obj.content,
                    'file_url': self.get_file_url(message_obj),
                    'message_type': message_obj.message_type,
                    'created_at': timezone.localtime(message_obj.created_at).isoformat(),
                    'is_read': message_obj.is_read,
                }
                print(f"DEBUG: [RECEIVE - chat_message] Message data prepared: {message_data_for_chat['id']}")

                # Send message data to all members of the conversation group (both sender and recipient if in chat)
                print(f"DEBUG: [RECEIVE - chat_message] Sending message to conversation group: {self.conversation_group_name}")
                await self.channel_layer.group_send(
                    self.conversation_group_name,
                    {
                        'type': 'chat_message', # This will call the chat_message method on consumers
                        'message': message_data_for_chat
                    }
                )
                print(f"DEBUG: [RECEIVE - chat_message] Message broadcasted to conversation group.")

                # --- Prepare data for real-time conversation list update for both sender and recipient ---
                recipient_profile_for_sender_view = await self.get_user(recipient_user.id)
                sender_profile_for_recipient_view = await self.get_user(self.user.id)

                # Manually prepare data for ChatParticipantSerializer, including photo_url
                other_participant_details_for_sender = {
                    'id': str(recipient_profile_for_sender_view.id),
                    'email': recipient_profile_for_sender_view.email,
                    'first_name': recipient_profile_for_sender_view.profile.first_name if hasattr(recipient_profile_for_sender_view, 'profile') and recipient_profile_for_sender_view.profile else '',
                    'last_name': recipient_profile_for_sender_view.profile.last_name if hasattr(recipient_profile_for_sender_view, 'profile') and recipient_profile_for_sender_view.profile else '',
                    'photo_url': self.get_sender_photo_url(recipient_profile_for_sender_view), # Use consumer's helper
                    'is_online': recipient_profile_for_sender_view.is_online,
                    'last_seen': timezone.localtime(recipient_profile_for_sender_view.last_seen).isoformat() if recipient_profile_for_sender_view.last_seen else None,
                }

                other_participant_details_for_recipient = {
                    'id': str(sender_profile_for_recipient_view.id),
                    'email': sender_profile_for_recipient_view.email,
                    'first_name': sender_profile_for_recipient_view.profile.first_name if hasattr(sender_profile_for_recipient_view, 'profile') and sender_profile_for_recipient_view.profile else '',
                    'last_name': sender_profile_for_recipient_view.profile.last_name if hasattr(sender_profile_for_recipient_view, 'profile') and sender_profile_for_recipient_view.profile else '',
                    'photo_url': self.get_sender_photo_url(sender_profile_for_recipient_view), # Use consumer's helper
                    'is_online': sender_profile_for_recipient_view.is_online,
                    'last_seen': timezone.localtime(sender_profile_for_recipient_view.last_seen).isoformat() if sender_profile_for_recipient_view.last_seen else None,
                }

                conv_created_at = timezone.localtime(conversation.created_at).isoformat()
                conv_updated_at = timezone.localtime(conversation.updated_at).isoformat()

                payload_data_base = {
                    'type': 'chat.conversation_update',
                    'conversation_id': conversation.id,
                    'last_message_data': message_data_for_chat,
                    'is_new_conversation': False,
                    'created_at': conv_created_at,
                    'updated_at': conv_updated_at,
                }

                # Dispatch update for the SENDER's conversation list
                payload_p1 = payload_data_base.copy()
                payload_p1['unread_count_for_this_conversation'] = 0 # Sender's side will show 0 unread for this message
                payload_p1['other_participant_details'] = other_participant_details_for_sender
                print(f"DEBUG: [RECEIVE - chat_message] Dispatching update to sender's ({self.user.email}) conversation list group: {self.user_conversation_list_group_name}")
                await self.channel_layer.group_send(
                    self.user_conversation_list_group_name,
                    payload_p1
                )
                print(f"DEBUG: [RECEIVE - chat_message] Dispatched message update to sender's ({self.user.email}) conversation list.")

                # Dispatch update for the RECIPIENT's conversation list
                payload_p2 = payload_data_base.copy()
                payload_p2['unread_count_for_this_conversation'] = unread_count_for_recipient
                payload_p2['other_participant_details'] = other_participant_details_for_recipient
                print(f"DEBUG: [RECEIVE - chat_message] Dispatching update to recipient's ({recipient_user.email}) conversation list group: {f'user_{recipient_user.id}_conversation_list'}")
                await self.channel_layer.group_send(
                    f'user_{recipient_user.id}_conversation_list',
                    payload_p2
                )
                print(f"DEBUG: [RECEIVE - chat_message] Dispatched message update to recipient's ({recipient_user.email}) conversation list.")

                # Update total unread count for the recipient (global badge)
                print(f"DEBUG: [RECEIVE - chat_message] Dispatching total unread count update for recipient ({recipient_user.email}): {total_unread_for_recipient}.")
                await self.channel_layer.group_send(
                    f'user_{recipient_user.id}_conversation_list',
                    {
                        'type': 'chat.total_unread_count_update',
                        'count': total_unread_for_recipient
                    }
                )
                print(f"DEBUG: [RECEIVE - chat_message] Dispatched total unread count update for recipient.")

                # Existing email dispatch logic (for offline recipients)
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

                    print(f"DEBUG: [RECEIVE - chat_message] Recipient {recipient_user.email} is offline. Dispatching email task.")
                    send_new_message_email.delay(
                        recipient_user.id,
                        self.user.id,
                        preview_content
                    )
                    print(f"DEBUG: [RECEIVE - chat_message] Dispatched email task to {recipient_user.email}.")
                else:
                    print(f"DEBUG: [RECEIVE - chat_message] Recipient {recipient_user.email} is online. No email dispatched.")

                print(f"DEBUG: [RECEIVE - chat_message] Message saved. Message ID: {message_obj.id}, File field: '{message_obj.file.name}' (empty if no file)")

            except Exception as e:
                print(f"CRITICAL ERROR: [RECEIVE - chat_message] Unhandled exception during message processing for user {self.user.email} in conv {self.conversation_id}: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc() # Print full traceback to logs
                await self.send(text_data=json.dumps({'type': 'error', 'message': 'Internal server error during message processing.'}))
                # It's possible this error causes the disconnect. The traceback is key.

        elif message_type == 'mark_as_read':
            message_ids_to_mark = data.get('message_ids', [])
            print(f"DEBUG: [RECEIVE - mark_as_read] Received request to mark messages as read: {message_ids_to_mark}")

            if message_ids_to_mark:
                try:
                    updated_data = await self._mark_messages_as_read_in_db(message_ids_to_mark)

                    if updated_data:
                        conversation_id = updated_data['conversation_id']
                        conversation = updated_data['conversation']
                        reader_user = updated_data['reader_user']
                        other_participant = updated_data['other_participant'] # This is the sender of the messages being read
                        total_unread_for_reader = updated_data['total_unread_for_reader']
                        last_msg_obj = updated_data['last_msg_obj']

                        print(f"DEBUG: [RECEIVE - mark_as_read] Messages marked as read in DB. Updated count: {updated_data.get('updated_count')}")

                        # Broadcast message read confirmation to the conversation group (for sender's "read" receipt within chat)
                        print(f"DEBUG: [RECEIVE - mark_as_read] Broadcasting read confirmation to conversation group: {self.conversation_group_name}")
                        await self.channel_layer.group_send(
                            self.conversation_group_name,
                            {
                                'type': 'messages_read_confirmation',
                                'reader_user_id': str(reader_user.id),
                                'message_ids': [str(mid) for mid in message_ids_to_mark]
                            }
                        )
                        print(f"DEBUG: [RECEIVE - mark_as_read] Read confirmation broadcasted.")

                        # --- Update the conversation list for the current user (reader) ---
                        last_message_data_for_reader = None
                        if last_msg_obj:
                            last_message_data_for_reader = {
                                'id': str(last_msg_obj.id),
                                'sender_id': str(last_msg_obj.sender.id),
                                'sender_first_name': last_msg_obj.sender.profile.first_name if hasattr(last_msg_obj.sender, 'profile') and last_msg_obj.sender.profile else '',
                                'sender_last_name': last_msg_obj.sender.profile.last_name if hasattr(last_msg_obj.sender, 'profile') and last_msg_obj.sender.profile else '',
                                'sender_photo': self.get_sender_photo_url(last_msg_obj.sender),
                                'content': last_msg_obj.content,
                                'file_url': self.get_file_url(last_msg_obj),
                                'message_type': last_msg_obj.message_type,
                                'created_at': timezone.localtime(last_msg_obj.created_at).isoformat(),
                                'is_read': last_msg_obj.is_read, # This will be True if it was read
                            }

                        other_participant_details_for_reader_list = {
                            'id': str(other_participant.id),
                            'email': other_participant.email,
                            'first_name': other_participant.profile.first_name if hasattr(other_participant, 'profile') and other_participant.profile else '',
                            'last_name': other_participant.profile.last_name if hasattr(other_participant, 'profile') and other_participant.profile else '',
                            'photo_url': self.get_sender_photo_url(other_participant),
                            'is_online': other_participant.is_online,
                            'last_seen': timezone.localtime(other_participant.last_seen).isoformat() if other_participant.last_seen else None,
                        }

                        print(f"DEBUG: [RECEIVE - mark_as_read] Dispatching conversation update to reader's ({reader_user.email}) conversation list group: {f'user_{reader_user.id}_conversation_list'}")
                        await self.channel_layer.group_send(
                            f'user_{reader_user.id}_conversation_list',
                            {
                                'type': 'chat.conversation_update',
                                'conversation_id': conversation_id,
                                'last_message_data': last_message_data_for_reader,
                                'unread_count_for_this_conversation': 0, # Now 0 unread for this conversation for the reader
                                'other_participant_details': other_participant_details_for_reader_list,
                                'is_new_conversation': False,
                                'created_at': timezone.localtime(conversation.created_at).isoformat(),
                                'updated_at': timezone.localtime(conversation.updated_at).isoformat(),
                            }
                        )
                        print(f"DEBUG: [RECEIVE - mark_as_read] Conversation update dispatched for reader.")

                        # --- Update the GLOBAL chat unread count for the current user (reader) ---
                        print(f"DEBUG: [RECEIVE - mark_as_read] Dispatching global unread count update for reader ({reader_user.email}): {total_unread_for_reader}.")
                        await self.channel_layer.group_send(
                            f'user_{reader_user.id}_conversation_list',
                            {
                                'type': 'chat.total_unread_count_update',
                                'count': total_unread_for_reader
                            }
                        )
                        print(f"DEBUG: [RECEIVE - mark_as_read] Global unread count update dispatched for reader.")

                        # --- NEW: Update the conversation list for the SENDER of the messages that were read ---
                        # The 'other_participant' is the sender whose messages were just marked as read.
                        # The 'reader_user' is the other participant from the sender's perspective.
                        sender_of_read_messages = other_participant # Renaming for clarity
                        reader_of_messages = reader_user

                        # Calculate new unread count for the sender in this specific conversation (should be 0 for them)
                        # This is the count of messages *from* the reader *to* the sender that are unread.
                        unread_count_for_sender_in_this_conv = await database_sync_to_async(
                            lambda: Message.objects.filter(
                                conversation=conversation,
                                sender=reader_of_messages,
                                is_read=False
                            ).count()
                        )()
                        print(f"DEBUG: [RECEIVE - mark_as_read] Unread count for sender in this conv: {unread_count_for_sender_in_this_conv}")


                        # Get the last message for the sender's list view. It should now show 'is_read=True' if it was read.
                        # We need to fetch this message with its sender's profile
                        last_message_for_sender_list_qs = await database_sync_to_async(
                            lambda: conversation.messages.select_related('sender__profile').order_by('-created_at').first()
                        )()
                        last_message_data_for_sender_list = None
                        if last_message_for_sender_list_qs: # last_msg_obj is the overall last message in the conversation
                            last_message_data_for_sender_list = {
                                'id': str(last_message_for_sender_list_qs.id),
                                'sender_id': str(last_message_for_sender_list_qs.sender.id),
                                'sender_first_name': last_message_for_sender_list_qs.sender.profile.first_name if hasattr(last_message_for_sender_list_qs.sender, 'profile') and last_message_for_sender_list_qs.sender.profile else '',
                                'sender_last_name': last_message_for_sender_list_qs.sender.profile.last_name if hasattr(last_message_for_sender_list_qs.sender, 'profile') and last_message_for_sender_list_qs.sender.profile else '',
                                'sender_photo': self.get_sender_photo_url(last_message_for_sender_list_qs.sender),
                                'content': last_message_for_sender_list_qs.content,
                                'file_url': self.get_file_url(last_message_for_sender_list_qs),
                                'message_type': last_message_for_sender_list_qs.message_type,
                                'created_at': timezone.localtime(last_message_for_sender_list_qs.created_at).isoformat(),
                                'is_read': last_message_for_sender_list_qs.is_read, # This will be True if this message was among those just read
                            }

                        # Ensure reader_of_messages has its profile selected if not already
                        reader_of_messages_with_profile = await self.get_user(reader_of_messages.id)

                        other_participant_details_for_sender_list = {
                            'id': str(reader_of_messages_with_profile.id),
                            'email': reader_of_messages_with_profile.email,
                            'first_name': reader_of_messages_with_profile.profile.first_name if hasattr(reader_of_messages_with_profile, 'profile') and reader_of_messages_with_profile.profile else '',
                            'last_name': reader_of_messages_with_profile.profile.last_name if hasattr(reader_of_messages_with_profile, 'profile') and reader_of_messages_with_profile.profile else '',
                            'photo_url': self.get_sender_photo_url(reader_of_messages_with_profile),
                            'is_online': reader_of_messages_with_profile.is_online,
                            'last_seen': timezone.localtime(reader_of_messages_with_profile.last_seen).isoformat() if reader_of_messages_with_profile.last_seen else None,
                        }

                        print(f"DEBUG: [RECEIVE - mark_as_read] Dispatching conversation update to sender's ({sender_of_read_messages.email}) conversation list group: {f'user_{sender_of_read_messages.id}_conversation_list'}")
                        await self.channel_layer.group_send(
                            f'user_{sender_of_read_messages.id}_conversation_list',
                            {
                                'type': 'chat.conversation_update',
                                'conversation_id': conversation_id,
                                'last_message_data': last_message_data_for_sender_list,
                                'unread_count_for_this_conversation': unread_count_for_sender_in_this_conv, # Unread count from reader's messages
                                'other_participant_details': other_participant_details_for_sender_list,
                                'is_new_conversation': False,
                                'created_at': timezone.localtime(conversation.created_at).isoformat(),
                                'updated_at': timezone.localtime(conversation.updated_at).isoformat(),
                            }
                        )
                        print(f"DEBUG: [RECEIVE - mark_as_read] Conversation update dispatched for sender of read messages.")

                        # Also update total unread count for the sender of the messages (global badge)
                        total_unread_for_sender = await database_sync_to_async(
                            lambda: Message.objects.filter(
                                Q(conversation__participant1=sender_of_read_messages) | Q(conversation__participant2=sender_of_read_messages),
                                is_read=False
                            ).exclude(sender=sender_of_read_messages).count()
                        )()
                        print(f"DEBUG: [RECEIVE - mark_as_read] Dispatching total unread count update for sender ({sender_of_read_messages.email}): {total_unread_for_sender}.")
                        await self.channel_layer.group_send(
                            f'user_{sender_of_read_messages.id}_conversation_list',
                            {
                                'type': 'chat.total_unread_count_update',
                                'count': total_unread_for_sender
                            }
                        )
                        print(f"DEBUG: [RECEIVE - mark_as_read] Global unread count update dispatched for sender.")

                    else:
                        print(f"WARNING: [RECEIVE - mark_as_read] _mark_messages_as_read_in_db returned None. No messages were marked or an error occurred.")
                except Exception as e:
                    print(f"ERROR: [RECEIVE - mark_as_read] Unhandled exception during mark_as_read processing for user {self.user.email}: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    await self.send(text_data=json.dumps({'type': 'error', 'message': 'Internal server error during mark as read processing.'}))
            else:
                print("WARNING: [RECEIVE - mark_as_read] No message IDs provided to mark as read.")
                await self.send(text_data=json.dumps({'type': 'error', 'message': 'No message IDs provided to mark as read.'}))

        elif message_type == 'typing':
            is_typing = data.get('is_typing', False)
            print(f"DEBUG: [RECEIVE - typing] User {self.user.id} typing status: {is_typing}")
            try:
                # Get the conversation to find the other participant, ensuring participants and their profiles are selected
                conversation = await database_sync_to_async(
                    lambda: Conversation.objects.select_related('participant1__profile', 'participant2__profile').get(id=self.conversation_id)
                )()

                # Get the other participant from the conversation object
                # This call itself is synchronous, but the related objects are now prefetched.
                other_participant = conversation.get_other_participant(self.user)

                # Broadcast typing status to the conversation group (excluding sender)
                print(f"DEBUG: [RECEIVE - typing] Broadcasting typing status to conversation group: {self.conversation_group_name}")
                await self.channel_layer.group_send(
                    self.conversation_group_name,
                    {
                        'type': 'typing_status',
                        'user_id': str(self.user.id),
                        'is_typing': is_typing
                    }
                )
                print(f"DEBUG: [RECEIVE - typing] Typing status broadcasted to conversation group.")

                # --- NEW: Broadcast typing status to the recipient's conversation list group ---
                # Ensure the current user (who is typing) has their profile selected if not already
                typing_user_with_profile = await self.get_user(self.user.id)

                print(f"DEBUG: [RECEIVE - typing] Broadcasting typing status to recipient's ({other_participant.email}) conversation list group: {f'user_{other_participant.id}_conversation_list'}")
                await self.channel_layer.group_send(
                    f'user_{other_participant.id}_conversation_list',
                    {
                        'type': 'chat.typing_status_list_update', # Custom type for list updates
                        'conversation_id': self.conversation_id,
                        'user_id': str(self.user.id),
                        'is_typing': is_typing,
                        'other_participant_details': { # Details of the user who is typing (from recipient's perspective)
                            'id': str(typing_user_with_profile.id),
                            'email': typing_user_with_profile.email,
                            'first_name': typing_user_with_profile.profile.first_name if hasattr(typing_user_with_profile, 'profile') and typing_user_with_profile.profile else '',
                            'last_name': typing_user_with_profile.profile.last_name if hasattr(typing_user_with_profile, 'profile') and typing_user_with_profile.profile else '',
                            'photo_url': self.get_sender_photo_url(typing_user_with_profile),
                            'is_online': typing_user_with_profile.is_online,
                            'last_seen': timezone.localtime(typing_user_with_profile.last_seen).isoformat() if typing_user_with_profile.last_seen else None,
                        }
                    }
                )
                print(f"DEBUG: [RECEIVE - typing] Typing status broadcasted to recipient's conversation list.")

            except Exception as e:
                print(f"ERROR: [RECEIVE - typing] Failed to broadcast typing status for user {self.user.email}: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                await self.send(text_data=json.dumps({'type': 'error', 'message': 'Internal server error broadcasting typing status.'}))
        else:
            print(f"WARNING: [RECEIVE] Unknown message type received from {self.user.email}: '{message_type}'. Data: {text_data}")
            await self.send(text_data=json.dumps({'type': 'error', 'message': f"Unknown message type: {message_type}"}))


    # --- Channel Layer Message Handlers ---
    async def chat_message(self, event):
        """Receives a chat message from the channel layer and sends it to the WebSocket."""
        print(f"DEBUG: [HANDLER - chat_message] Called for user {self.user.email} in conv {self.conversation_id}. Message ID: {event['message'].get('id')}")
        try:
            await self.send(text_data=json.dumps(event['message']))
            print(f"DEBUG: [HANDLER - chat_message] Message sent to WebSocket for {self.user.email}.")
        except Exception as e:
            print(f"ERROR: [HANDLER - chat_message] Failed to send chat message to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")

    async def user_status_update(self, event):
        """Receives user status updates and sends them to the WebSocket."""
        print(f"DEBUG: [HANDLER - user_status_update] Called for user {self.user.email}. Event user ID: {event['user_id']}, Is Online: {event['is_online']}")
        if str(event['user_id']) != str(self.user.id) or not event['is_online']:
            try:
                await self.send(text_data=json.dumps({
                    'type': 'user_status_update',
                    'user_id': event['user_id'],
                    'is_online': event['is_online'],
                    'last_seen': event['last_seen']
                }))
                print(f"DEBUG: [HANDLER - user_status_update] Status update sent to WebSocket for {self.user.email}.")
            except Exception as e:
                print(f"ERROR: [HANDLER - user_status_update] Failed to send user status update to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")
        else:
            print(f"DEBUG: [HANDLER - user_status_update] Skipping send for self-update (online) for user {self.user.email}.")


    async def messages_read_confirmation(self, event):
        """Receives read confirmations and sends them to the WebSocket."""
        print(f"DEBUG: [HANDLER - messages_read_confirmation] Called for user {self.user.email}. Reader ID: {event['reader_user_id']}")
        try:
            await self.send(text_data=json.dumps({
                'type': 'messages_read_confirmation',
                'reader_user_id': event['reader_user_id'],
                'message_ids': event['message_ids']
            }))
            print(f"DEBUG: [HANDLER - messages_read_confirmation] Read confirmation sent to WebSocket for {self.user.email}.")
        except Exception as e:
            print(f"ERROR: [HANDLER - messages_read_confirmation] Failed to send read confirmation to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")

    async def typing_status(self, event):
        """Receives typing status updates and sends them to the WebSocket."""
        print(f"DEBUG: [HANDLER - typing_status] Called for user {self.user.email}. Typing user ID: {event['user_id']}, Is Typing: {event['is_typing']}")
        if str(event['user_id']) != str(self.user.id):
            try:
                await self.send(text_data=json.dumps({
                    'type': 'typing_status',
                    'user_id': event['user_id'],
                    'is_typing': event['is_typing']
                }))
                print(f"DEBUG: [HANDLER - typing_status] Typing status sent to WebSocket for {self.user.email}.")
            except Exception as e:
                print(f"ERROR: [HANDLER - typing_status] Failed to send typing status to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")
        else:
            print(f"DEBUG: [HANDLER - typing_status] Skipping send for self-typing status for user {self.user.email}.")

    async def chat_conversation_update(self, event):
        """
        Receives updates for a user's conversation list and sends them to the WebSocket.
        """
        print(f"DEBUG: [HANDLER - chat_conversation_update] Called for user {self.user.email} for conv {event['conversation_id']}. Type: {event['type']}")
        try:
            await self.send(text_data=json.dumps({
                'type': 'conversation_list_update', # Use a clear type for Flutter
                'conversation_id': event['conversation_id'],
                'last_message_data': event['last_message_data'],
                'unread_count_for_this_conversation': event['unread_count_for_this_conversation'],
                'other_participant_details': event['other_participant_details'],
                'is_new_conversation': event['is_new_conversation'],
                'created_at': event['created_at'],
                'updated_at': event['updated_at'],
            }))
            print(f"DEBUG: [HANDLER - chat_conversation_update] Conversation list update sent to WebSocket for {self.user.email}.")
        except Exception as e:
            print(f"ERROR: [HANDLER - chat_conversation_update] Failed to send conversation update to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")

    async def chat_typing_status_list_update(self, event):
        """
        Receives typing status updates for the conversation list and sends them to the WebSocket.
        """
        print(f"DEBUG: [HANDLER - chat_typing_status_list_update] Called for user {self.user.email} for conv {event['conversation_id']}. Typing user ID: {event['user_id']}, Is Typing: {event['is_typing']}")
        try:
            await self.send(text_data=json.dumps({
                'type': 'typing_status_list_update', # Custom type for Flutter to handle on list screen
                'conversation_id': event['conversation_id'],
                'user_id': event['user_id'],
                'is_typing': event['is_typing'],
                'other_participant_details': event['other_participant_details'],
            }))
            print(f"DEBUG: [HANDLER - chat_typing_status_list_update] Typing status list update sent to WebSocket for {self.user.email}.")
        except Exception as e:
            print(f"ERROR: [HANDLER - chat_typing_status_list_update] Failed to send typing status list update to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")


    async def chat_total_unread_count_update(self, event):
        """
        Receives updates for a user's total unread chat message count and sends it to the WebSocket.
        """
        print(f"DEBUG: [HANDLER - chat_total_unread_count_update] Called for user {self.user.email}. Count: {event['count']}")
        try:
            await self.send(text_data=json.dumps({
                'type': 'total_unread_chat_count', # Use a clear type for Flutter
                'count': event['count']
            }))
            print(f"DEBUG: [HANDLER - chat_total_unread_count_update] Total unread count sent to WebSocket for {self.user.email}.")
        except Exception as e:
            print(f"ERROR: [HANDLER - chat_total_unread_count_update] Failed to send total unread count update to WebSocket for user {self.user.email}: {type(e).__name__}: {e}")


    # --- Database Operations (Async-safe) ---
    @database_sync_to_async
    def get_user(self, user_id):
        """Fetches a user object from the database, including their profile."""
        print(f"DEBUG: [DB - get_user] Attempting to fetch user with ID: {user_id}")
        try:
            # Always select_related('profile') when fetching user in consumer
            user = User.objects.select_related('profile').get(id=user_id)
            print(f"DEBUG: [DB - get_user] User {user.email} (ID: {user_id}) fetched successfully.")
            return user
        except User.DoesNotExist:
            print(f"ERROR: [DB - get_user] User with ID {user_id} does not exist.")
            return None
        except Exception as e:
            print(f"ERROR: [DB - get_user] Unexpected error fetching user {user_id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def update_user_status(self, online):
        """Updates a user's online status and last_seen timestamp."""
        print(f"DEBUG: [DB - update_user_status] Updating status for user {self.user.id} to online={online}")
        try:
            user = self.user
            user.is_online = online
            if not online:
                user.last_seen = timezone.now()
            user.save(update_fields=['is_online', 'last_seen'])
            print(f"DEBUG: [DB - update_user_status] User {user.id} status updated successfully.")
        except Exception as e:
            print(f"ERROR: [DB - update_user_status] Failed to update status for user {self.user.id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    @database_sync_to_async
    def _save_message_to_db(self, content, file_url, message_type):
        """
        Synchronous function to save a new message to the database and
        fetch related data needed for subsequent async operations.
        It now correctly derives the expected media URL prefix from the file_url itself.
        """
        print(f"DEBUG: [DB - _save_message_to_db] Attempting to save message for conv {self.conversation_id}, sender {self.user.id}")
        try:
            # Ensure participants and their profiles are selected here
            conversation = Conversation.objects.select_related('participant1__profile', 'participant2__profile').get(id=self.conversation_id)
            print(f"DEBUG: [DB - _save_message_to_db] Conversation {self.conversation_id} found.")
        except Conversation.DoesNotExist:
            print(f"ERROR: [DB - _save_message_to_db] Conversation {self.conversation_id} does not exist when saving message.")
            return None
        except Exception as e:
            print(f"ERROR: [DB - _save_message_to_db] Unexpected error fetching conversation {self.conversation_id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

        try:
            message = Message(
                conversation=conversation,
                sender=self.user,
                content=content,
                message_type=message_type
            )

            if file_url:
                # Parse the file_url to get its scheme and netloc (host:port)
                parsed_file_url = urllib.parse.urlparse(file_url)
                # Construct the expected prefix using the scheme and netloc from the file_url
                expected_prefix_for_media = f"{parsed_file_url.scheme}://{parsed_file_url.netloc}{settings.MEDIA_URL}"
                print(f"DEBUG: [DB - _save_message_to_db] File URL provided: {file_url}. Expected prefix for media: {expected_prefix_for_media}")

                if file_url.startswith(expected_prefix_for_media):
                    # If the file_url is from our media system, store its relative path
                    relative_path = file_url.split(expected_prefix_for_media, 1)[1]
                    message.file.name = relative_path
                    message.content = None # Clear content if it was only holding the file_url
                    print(f"DEBUG: [DB - _save_message_to_db] File URL is internal. Storing relative path: {relative_path}")
                else:
                    # If the URL is not from our media system, store it directly in content
                    message.content = file_url
                    message.file.name = None # Ensure file field is null if content holds the URL
                    print(f"DEBUG: [DB - _save_message_to_db] File URL is external. Storing in content field.")

            message.save()
            print(f"DEBUG: [DB - _save_message_to_db] Message saved to DB. ID: {message.id}")

            # Update conversation's updated_at to ensure it bubbles to the top of lists
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            print(f"DEBUG: [DB - _save_message_to_db] Conversation {conversation.id} updated_at field updated.")

            # get_other_participant now works without triggering new DB queries
            recipient_user = conversation.get_other_participant(self.user)
            print(f"DEBUG: [DB - _save_message_to_db] Recipient user: {recipient_user.id}")

            # Calculate unread count for the recipient from this sender's messages in this conversation
            # This is a synchronous operation within a database_sync_to_async function, so NO await here.
            unread_count_for_recipient = Message.objects.filter(
                conversation=conversation,
                sender=self.user,
                is_read=False
            ).count()
            print(f"DEBUG: [DB - _save_message_to_db] Unread count for recipient in this conversation: {unread_count_for_recipient}")

            # Calculate total unread count for the recipient across all their conversations
            # This is a synchronous operation within a database_sync_to_async function, so NO await here.
            total_unread_for_recipient = Message.objects.filter(
                Q(conversation__participant1=recipient_user) | Q(conversation__participant2=recipient_user),
                is_read=False
            ).exclude(sender=recipient_user).count()
            print(f"DEBUG: [DB - _save_message_to_db] Total unread count for recipient across all conversations: {total_unread_for_recipient}")

            return {
                'message_obj': message,
                'conversation': conversation,
                'recipient_user': recipient_user,
                'unread_count_for_recipient': unread_count_for_recipient,
                'total_unread_for_recipient': total_unread_for_recipient,
            }
        except Exception as e:
            print(f"ERROR: [DB - _save_message_to_db] Unhandled exception during message save or data calculation: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def _mark_messages_as_read_in_db(self, message_ids):
        """
        Synchronous function to mark a list of messages as read for the current user in a conversation.
        """
        print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Attempting to mark messages {message_ids} as read for user {self.user.id}")
        try:
            # Ensure participants and their profiles are selected here
            conversation = Conversation.objects.select_related('participant1__profile', 'participant2__profile').get(id=self.conversation_id)
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Conversation {self.conversation_id} found.")
        except Conversation.DoesNotExist:
            print(f"ERROR: [DB - _mark_messages_as_read_in_db] Conversation {self.conversation_id} does not exist when marking messages as read.")
            return None
        except Exception as e:
            print(f"ERROR: [DB - _mark_messages_as_read_in_db] Unexpected error fetching conversation {self.conversation_id}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

        try:
            # get_other_participant now works without triggering new DB queries
            other_participant = conversation.get_other_participant(self.user)
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Other participant: {other_participant.id}")

            messages_to_mark = Message.objects.filter(
                conversation=conversation,
                sender=other_participant,
                id__in=message_ids,
                is_read=False
            )
            updated_count = messages_to_mark.update(is_read=True)
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Marked {updated_count} messages as read for conversation {self.conversation_id}.")

            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Conversation {conversation.id} updated_at field updated after marking messages.")

            # Use .count() directly as this entire function is wrapped by database_sync_to_async
            total_unread_for_reader = Message.objects.filter(
                Q(conversation__participant1=self.user) | Q(conversation__participant2=self.user),
                is_read=False
            ).exclude(sender=self.user).count()
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Total unread count for reader across all conversations: {total_unread_for_reader}")

            # Get the last message for the conversation to update the list view.
            # Ensure sender and sender's profile are selected for last_msg_obj
            last_msg_obj = conversation.messages.select_related('sender__profile').order_by('-created_at').first()
            print(f"DEBUG: [DB - _mark_messages_as_read_in_db] Latest message in conversation: {last_msg_obj.id if last_msg_obj else 'None'}")

            return {
                'conversation_id': self.conversation_id,
                'conversation': conversation,
                'reader_user': self.user,
                'other_participant': other_participant,
                'total_unread_for_reader': total_unread_for_reader,
                'last_msg_obj': last_msg_obj,
                'updated_count': updated_count
            }
        except Exception as e:
            print(f"ERROR: [DB - _mark_messages_as_read_in_db] Unhandled exception during mark as read operation or data calculation: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    # --- Helper Functions (not async, do not touch DB directly) ---
    def get_base_url(self):
        """Constructs the base URL for media/static files using scope."""
        scheme = self.scope.get('scheme', 'http') # Default to http

        # The 'host' header usually includes the port, e.g., 'localhost:9998'
        # Headers are a list of (bytes_key, bytes_value) tuples
        host_header = None
        for header_name, header_value in self.scope.get('headers', []):
            if header_name == b'host':
                host_header = header_value.decode('utf-8')
                break

        if not host_header:
            # Fallback if 'host' header is missing (unlikely for a valid WS connection)
            # Use the server address from scope, which is (host, port)
            server_host, server_port = self.scope.get('server', ('localhost', 8889))
            host_header = f"{server_host}:{server_port}"
            print(f"WARNING: [HELPER - get_base_url] 'host' header not found in scope. Falling back to server tuple: {host_header}")

        return f"{scheme}://{host_header}"

    def get_sender_photo_url(self, user):
        """Constructs the absolute URL for a user's profile photo."""
        base_url = self.get_base_url()
        if hasattr(user, 'profile') and user.profile and user.profile.photo:
            # user.profile.photo.url already starts with MEDIA_URL, e.g., '/media/userphotos/...'
            url = f"{base_url}{user.profile.photo.url}"
            print(f"DEBUG: [HELPER - get_sender_photo_url] Generated URL: {url}")
            return url
        # Provide a default image URL if no photo or profile exists
        # Make sure this path exists in your static/media files
        default_url = f"{base_url}{settings.STATIC_URL}images/default-profile.png" # Example default path
        print(f"DEBUG: [HELPER - get_sender_photo_url] No profile photo found for user {user.id}. Using default: {default_url}")
        return default_url

    def get_file_url(self, message_obj):
        """Constructs the absolute URL for a message file."""
        base_url = self.get_base_url()
        if message_obj.file:
            # message_obj.file.url already starts with MEDIA_URL, e.g., '/media/messages/...'
            url = f"{base_url}{message_obj.file.url}"
            print(f"DEBUG: [HELPER - get_file_url] Generated URL: {url}")
            return url
        print(f"DEBUG: [HELPER - get_file_url] No file found for message {message_obj.id}. Returning None.")
        return None
