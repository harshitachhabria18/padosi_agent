import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

msg = ChatMessage.objects.filter(role="assistant", content__icontains="Since you're looking for term life insurance, I'll need to know where you're located").order_by('-timestamp').first()

if msg:
    print(f"Session: {msg.session.session_id}")
    print(f"Content: {msg.content}")
    # Can we see the raw output before it was stripped? 
    # Unfortunately, the raw output isn't saved.
    # But maybe we can see if it had options? It doesn't save options in the DB.
else:
    print("Not found in DB.")
