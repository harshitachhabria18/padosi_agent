from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.core.cache import cache
import json
import logging
from .llm_client import generate_suggestion_chips, get_chat_completion, extract_agent_links, stream_plain_text_completion
from .models import ChatMessage
import uuid

logger = logging.getLogger(__name__)

@require_GET
def get_history(request, session_id):
    messages = ChatMessage.objects.filter(
        session__session_id=session_id,
        role__in=['user', 'assistant']
    ).exclude(content__startswith='__TOOL_CALLS__').order_by('timestamp')
    
    data = []
    for m in messages:
        if m.role == 'assistant':
            cleaned, agent_links = extract_agent_links(m.content)
            data.append({
                "role": m.role,
                "content": cleaned,
                "agent_links": agent_links,
                "agent_cards": m.agent_cards or [],
                "timestamp": m.timestamp.isoformat()
            })
        else:
            data.append({
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat()
            })
        
    return JsonResponse({
        "success": True,
        "data": data
    })

@require_GET
def get_chips(request):
    chips = cache.get("suggestion_chips")
    if not chips:
        chips = generate_suggestion_chips()
        cache.set("suggestion_chips", chips, timeout=46800) # 13 hours
    
    return JsonResponse({
        "success": True,
        "data": chips
    })

@csrf_exempt
@require_POST
def send_message(request):
    client_ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    
    # Rate limit: 20 messages per minute per IP using a rolling window
    rl_key = f"ratelimit_chat_{client_ip}"
    
    # FileBasedCache incr() destroys custom TTLs and lacks atomicity anyway.
    # We use a timestamp list to implement a true rolling window.
    import time
    now = time.time()
    
    timestamps = cache.get(rl_key, [])
    # Prune timestamps older than 60 seconds
    timestamps = [t for t in timestamps if t > now - 60]
    
    if len(timestamps) >= 20:
        return JsonResponse({"success": False, "error": "Too many requests. Please slow down."}, status=429)
        
    timestamps.append(now)
    cache.set(rl_key, timestamps, timeout=60)
    
    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        session_id = data.get("session_id", "").strip()
        
        if not session_id:
            # Fallback to django session
            if not request.session.session_key:
                request.session.create()
            session_id = request.session.session_key
            
        if not user_message:
            return JsonResponse({"success": False, "error": "Message is required."}, status=400)

        def event_stream():
            """SSE generator — wraps stream_plain_text_completion and handles the use_full_flow fallback."""
            try:
                gen = stream_plain_text_completion(session_id, user_message)
                first = next(gen)

                if first.get("type") == "use_full_flow":
                    # LLM wants to make a tool call — use the full non-streaming flow.
                    # The user_message was already saved to DB by stream_plain_text_completion,
                    # so pass user_message=None to get_chat_completion to avoid double-saving.
                    result = get_chat_completion(session_id, user_message=None)
                    payload = {
                        "type": "full_response",
                        "success": result.get("success", True),
                        "session_id": session_id,
                        "reply": result["reply"],
                        "quick_options": result.get("quick_options", []),
                        "quick_option_groups": result.get("quick_option_groups", []),
                        "agent_links": result.get("agent_links", []),
                        "agent_cards": result.get("agent_cards", []),
                        "total_time": result.get("total_time", 0.0)
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    return

                # First event was a chunk or error — stream it and the rest
                yield f"data: {json.dumps(first)}\n\n"
                for event in gen:
                    yield f"data: {json.dumps(event)}\n\n"

            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error(f"Error in SSE event_stream: {e}")
                error_msg = {"type": "error", "message": "I'm here to help you with insurance and investment related questions — finding the right policy, understanding coverage, or connecting you with a licensed agent. What would you like to know?"}
                yield f"data: {json.dumps(error_msg)}\n\n"

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream; charset=utf-8')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'  # Prevent nginx/proxy buffering
        return response

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in send_message view: {e}")
        
        # Graceful handler for MySQL emoji/encoding issues
        if "Incorrect string value" in error_msg or "utf8mb4" in error_msg:
            friendly_reply = "I'm sorry, I couldn't process some of the characters (like emojis) in your message. Could you try sending it again as plain text?"
            return JsonResponse({
                "success": True,
                "session_id": session_id,
                "data": {
                    "reply": friendly_reply,
                    "quick_options": [],
                    "agent_links": []
                }
            })
            
        return JsonResponse({"success": False, "error": "Internal server error"}, status=500)

