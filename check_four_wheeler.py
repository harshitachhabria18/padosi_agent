import os
import django
import sys

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

user_msg = ChatMessage.objects.filter(role="user", content__icontains="I want to buy four wheeler insurance please").order_by('-timestamp').first()

if user_msg:
    session = user_msg.session
    print(f"Found Session: {session.session_id}")
    
    msgs = ChatMessage.objects.filter(session=session).order_by('timestamp')
    for m in msgs:
        print(f"\n[{m.timestamp}] {m.role.upper()}:")
        print(m.content)
        if m.role == "tool":
            print(f"  (Tool Call ID: {m.tool_call_id}, Name: {m.tool_name})")
else:
    print("Session not found.")
