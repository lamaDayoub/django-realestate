from django.urls import path 
from .consumers import *
from django.urls import re_path
websocket_urlpatterns=[
    	re_path(r"ws/chat/(?P<conversation_id>\w+)/$", ChatConsumer.as_asgi()),
	]