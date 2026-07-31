import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

print("Searching for user message 'I need term life insurance'...")
user_msgs = ChatMessage.objects.filter(role="user", content__icontains="I need term life insurance").order_by('-timestamp')[:5]

for u_msg in user_msgs:
    print(f"\nSession: {u_msg.session.session_id}")
    print(f"User Message: {u_msg.content}")
    
    # Get all assistant messages in this session after this user message
    assistant_msgs = ChatMessage.objects.filter(session=u_msg.session, role="assistant", timestamp__gt=u_msg.timestamp).order_by('timestamp')
    for a_msg in assistant_msgs:
        if a_msg.content.startswith("__TOOL_CALLS__:"):
            print(f"  Tool Call: {a_msg.content}")
        else:
            print(f"  Assistant Reply: {a_msg.content}")
