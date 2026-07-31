import os
import django
import sys
import uuid
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from chatbot.llm_client import get_chat_completion
from chatbot.models import ChatMessage

def test_query(message):
    session_id = uuid.uuid4().hex
    print(f"\n--- Testing: {message} ---")
    
    # Send user message
    result = get_chat_completion(session_id, user_message=message)
    
    # Fetch tool calls logged to DB
    tool_calls_msg = ChatMessage.objects.filter(
        session__session_id=session_id, 
        role="assistant", 
        content__startswith="__TOOL_CALLS__:"
    ).first()
    
    if tool_calls_msg:
        print("TOOL CALLS:", tool_calls_msg.content.replace("__TOOL_CALLS__:", ""))
    else:
        print("TOOL CALLS: None")
        
    print("BOT REPLY:", result.get("reply", ""))
    
    options = result.get("quick_options", [])
    if options:
        print("OPTIONS:", options)

queries = [
    "I want four wheeler insurance please",
    "I need bike insurance",
    "I want term life",
    "I need cyber security insurance",
    "Do you have pet insurance?"
]

for q in queries:
    test_query(q)
