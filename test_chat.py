import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from chatbot.llm_client import stream_plain_text_completion, get_chat_completion
import uuid

session_id = "test_session_term_life"
user_message = "I need term life insurance"

print("Testing chat completion...")
# Using full flow to see the full raw result, or we can just iterate stream
res = get_chat_completion(session_id, user_message)

print(json.dumps(res, indent=2))
