import os
import django
import sys
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from chatbot.models import ChatMessage, LatencyLog, ChatSession

msg = ChatMessage.objects.filter(role="user", content__icontains="SUV insurance").order_by('-timestamp').first()
session_id = msg.session.session_id
print(f"Found session: {session_id}")

msgs = ChatMessage.objects.filter(session__session_id=session_id).order_by('timestamp')
for m in msgs:
    print(f"[{m.timestamp}] {m.role.upper()}: {m.content}")
        
print("\n--- Latency Logs ---")
logs = LatencyLog.objects.filter(session__session_id=session_id).order_by('timestamp')
for l in logs:
    print(f"[{l.timestamp}] Model: {l.model_name}, Time: {l.total_time}, Tokens: {l.total_tokens}, Input: {l.user_message[:50]}")
