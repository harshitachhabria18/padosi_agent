import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.models import ChatMessage

print("Searching for Pranav Shah in assistant messages...")
msgs = ChatMessage.objects.filter(role="assistant", content__icontains="Pranav Shah").order_by('-timestamp')[:5]

for msg in msgs:
    print(f"Session: {msg.session.session_id}")
    print(f"Content snippet: {msg.content[:200]}...")
    
    # Get all previous tool calls for this session
    tool_calls = ChatMessage.objects.filter(session=msg.session, role="assistant", content__startswith="__TOOL_CALLS__:").order_by('timestamp')
    if tool_calls.exists():
        print("Tool calls in this session:")
        for tc in tool_calls:
            print(f"  {tc.content}")
    else:
        # Maybe the tool call format is different
        other_calls = ChatMessage.objects.filter(session=msg.session, role="assistant", content__icontains="find_agents").order_by('timestamp')
        for tc in other_calls:
            if "<function=" in tc.content:
                print(f"  {tc.content}")
    print("-" * 40)
