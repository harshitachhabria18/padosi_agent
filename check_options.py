import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

msg = ChatMessage.objects.filter(session__session_id='msjuregfsnm27zwwrli4ocffqqccxzad', role='assistant').order_by('timestamp').first()
if msg:
    print(repr(msg.content))
