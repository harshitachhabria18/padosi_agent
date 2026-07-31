import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

print("Fetching recent tool calls...")
msgs = ChatMessage.objects.filter(role="assistant", content__contains='"380008"').order_by('-timestamp')[:5]

for msg in msgs:
    print(f"Session: {msg.session.session_id}")
    print(f"Tool Call: {msg.content}")
    
    # Try to find the user message right before this
    user_msg = ChatMessage.objects.filter(session=msg.session, role="user", timestamp__lt=msg.timestamp).order_by('-timestamp').first()
    if user_msg:
        print(f"Prior User Message: {user_msg.content}")
    print("-" * 40)
