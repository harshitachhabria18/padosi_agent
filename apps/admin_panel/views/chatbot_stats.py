"""
apps/admin_panel/views/chatbot_stats.py

Chatbot Analytics admin page.
Reads from three existing ORM models (no migrations needed):
  - apps.chatbot.models.ChatSession
  - apps.chatbot.models.ChatMessage
  - apps.chatbot.models.LatencyLog

Auth: same _get_admin_from_session pattern as all other admin views.
"""

import json
import logging
from datetime import datetime, timedelta

from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate, TruncHour, TruncMinute

from apps.chatbot.models import ChatMessage, ChatSession, LatencyLog
from .dashboard import _get_admin_from_session

logger = logging.getLogger(__name__)


def chatbot_stats(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    # Timeframe filter — supports presets (e.g. '30d', '60m') and 'custom' range
    PRESETS = {
        '60m':  timedelta(minutes=60),
        '12h':  timedelta(hours=12),
        '24h':  timedelta(hours=24),
        '7d':   timedelta(days=7),
        '30d':  timedelta(days=30),
        '90d':  timedelta(days=90),
        '365d': timedelta(days=365),
    }
    timeframe_str = request.GET.get('timeframe', '30d')
    timeframe = timeframe_str

    now = timezone.now()
    end_date = now

    if timeframe_str == 'custom':
        # Parse exact start/end from URL params; fall back to 30 days on error
        try:
            from django.conf import settings
            raw_start = request.GET.get('start_date', '')
            raw_end   = request.GET.get('end_date', '')
            start_date = datetime.fromisoformat(raw_start)
            end_date   = datetime.fromisoformat(raw_end)
            
            # Only make timezone aware if the Django settings require it
            if settings.USE_TZ:
                start_date = timezone.make_aware(start_date)
                end_date   = timezone.make_aware(end_date)

            if end_date <= start_date:
                raise ValueError("end_date must be after start_date")
        except Exception:
            start_date = now - timedelta(days=30)
            end_date   = now
    else:
        delta      = PRESETS.get(timeframe_str, timedelta(days=30))
        start_date = now - delta

    # Decide how to group chart buckets based on the selected duration
    duration = end_date - start_date
    if duration <= timedelta(hours=2):
        chart_trunc_msg     = lambda field: TruncMinute(field)
        chart_trunc_latency = lambda field: TruncMinute(field)
        chart_label_format  = "%H:%M"
    elif duration <= timedelta(days=3):
        chart_trunc_msg     = lambda field: TruncHour(field)
        chart_trunc_latency = lambda field: TruncHour(field)
        chart_label_format  = "%b %d %H:00"
    else:
        chart_trunc_msg     = lambda field: TruncDate(field)
        chart_trunc_latency = lambda field: TruncDate(field)
        chart_label_format  = "%b %d"

    # Base querysets — always exclude test traffic, filtered by selected range
    sessions_qs = ChatSession.objects.filter(is_test_traffic=False, created_at__range=(start_date, end_date))
    messages_qs = ChatMessage.objects.filter(session__is_test_traffic=False, timestamp__range=(start_date, end_date))
    latency_qs  = LatencyLog.objects.filter(created_at__range=(start_date, end_date))

    # Overview stat cards
    try:
        total_sessions       = sessions_qs.count()
        sessions_today       = ChatSession.objects.filter(
            is_test_traffic=False, created_at__date=now.date()
        ).count()
        total_questions      = messages_qs.filter(role='user').count()
        total_answers        = messages_qs.filter(role='assistant').exclude(
            content__startswith='__TOOL_CALLS__'
        ).count()
        total_agent_searches = messages_qs.filter(role='tool').count()
        total_api_calls      = latency_qs.count()
        avg_latency = latency_qs.aggregate(v=Avg('total_time'))['v'] or 0.0
        avg_ttft    = latency_qs.exclude(
            time_to_first_token__isnull=True
        ).aggregate(v=Avg('time_to_first_token'))['v'] or 0.0
        total_prompt_tokens     = latency_qs.aggregate(v=Sum('used_prompt_tokens'))['v'] or 0
        total_completion_tokens = latency_qs.aggregate(v=Sum('used_completion_tokens'))['v'] or 0
        total_tokens            = total_prompt_tokens + total_completion_tokens
        
        live_sessions_count = ChatMessage.objects.filter(
            timestamp__gte=now - timedelta(minutes=15)
        ).values('session').distinct().count()
    except Exception as exc:
        logger.error("chatbot_stats overview error: %s", exc)
        total_sessions = sessions_today = total_questions = total_answers = 0
        total_agent_searches = total_api_calls = 0
        avg_latency = avg_ttft = 0.0
        total_prompt_tokens = total_completion_tokens = total_tokens = 0
        live_sessions_count = 0

    # Provider breakdown table
    try:
        provider_stats = list(
            latency_qs
            .exclude(provider_name__isnull=True)
            .values('provider_name')
            .annotate(
                calls=Count('id'),
                prompt_tokens=Sum('used_prompt_tokens'),
                completion_tokens=Sum('used_completion_tokens'),
                avg_latency_s=Avg('total_time'),
                avg_ttft_s=Avg('time_to_first_token'),
            )
            .order_by('-calls')
        )
        for p in provider_stats:
            p['avg_latency_s']     = round(p['avg_latency_s']  or 0, 3)
            p['avg_ttft_s']        = round(p['avg_ttft_s']     or 0, 3)
            p['prompt_tokens']     = p['prompt_tokens']         or 0
            p['completion_tokens'] = p['completion_tokens']     or 0
            p['total_tokens_used'] = p['prompt_tokens'] + p['completion_tokens']
    except Exception as exc:
        logger.error("chatbot_stats provider_stats error: %s", exc)
        provider_stats = []

    # Latest Groq rate-limit snapshot (most recent entry per Groq provider key)
    groq_details = []
    try:
        seen = set()
        for entry in latency_qs.filter(
            provider_name__icontains='groq'
        ).exclude(groq_remaining_tokens__isnull=True).order_by('-created_at'):
            if entry.provider_name not in seen:
                seen.add(entry.provider_name)
                pct = round(
                    (entry.groq_remaining_tokens / entry.groq_limit_tokens * 100)
                    if entry.groq_limit_tokens else 0
                )
                groq_details.append({
                    'provider_name':   entry.provider_name,
                    'groq_remaining':  entry.groq_remaining_tokens,
                    'groq_limit':      entry.groq_limit_tokens,
                    'groq_reset_time': entry.groq_reset_time,
                    'pct_remaining':   pct,
                })
        
        # Sort sequentially so the UI always shows Groq-1, Groq-2, etc. in order
        groq_details.sort(key=lambda x: x['provider_name'])
    except Exception as exc:
        logger.error("chatbot_stats groq_details error: %s", exc)

    # Questions chart data — grouped dynamically by minute/hour/day
    try:
        daily_raw    = (
            messages_qs.filter(role='user')
            .annotate(period=chart_trunc_msg('timestamp'))
            .values('period').annotate(count=Count('id')).order_by('period')
        )
        chart_labels = [r['period'].strftime(chart_label_format) if r['period'] else '' for r in daily_raw]
        chart_values = [r['count'] for r in daily_raw]
    except Exception as exc:
        logger.error("chatbot_stats daily chart error: %s", exc)
        chart_labels = []
        chart_values = []

    # Token usage chart data — grouped dynamically by minute/hour/day
    try:
        token_daily_raw = (
            latency_qs
            .annotate(period=chart_trunc_latency('created_at'))
            .values('period')
            .annotate(prompt=Sum('used_prompt_tokens'), completion=Sum('used_completion_tokens'))
            .order_by('period')
        )
        token_chart_labels     = [r['period'].strftime(chart_label_format) if r['period'] else '' for r in token_daily_raw]
        token_chart_prompt     = [r['prompt']     or 0 for r in token_daily_raw]
        token_chart_completion = [r['completion'] or 0 for r in token_daily_raw]
    except Exception as exc:
        logger.error("chatbot_stats token chart error: %s", exc)
        token_chart_labels = token_chart_prompt = token_chart_completion = []

    # Recent API calls (latest 50 LatencyLog rows)
    try:
        recent_calls = list(
            latency_qs.order_by('-created_at')[:50].values(
                'created_at', 'provider_name', 'endpoint',
                'used_prompt_tokens', 'used_completion_tokens',
                'time_to_first_token', 'total_time',
                'groq_remaining_tokens', 'groq_limit_tokens',
            )
        )
        for c in recent_calls:
            c['total_tokens'] = (c['used_prompt_tokens'] or 0) + (c['used_completion_tokens'] or 0)
            c['total_time']   = round(c['total_time'] or 0, 3)
            c['ttft']         = round(c['time_to_first_token'] or 0, 3)
    except Exception as exc:
        logger.error("chatbot_stats recent_calls error: %s", exc)
        recent_calls = []

    # Recent sessions (latest 20)
    try:
        recent_sessions = list(
            sessions_qs.order_by('-created_at')[:20].values('session_id', 'created_at', 'updated_at')
        )
        for s in recent_sessions:
            s['message_count'] = ChatMessage.objects.filter(
                session__session_id=s['session_id']
            ).count()
    except Exception as exc:
        logger.error("chatbot_stats recent_sessions error: %s", exc)
        recent_sessions = []

    # Recent messages — actual Q&A content (last 30 user + assistant messages)
    try:
        recent_messages = list(
            messages_qs
            .filter(role__in=['user', 'assistant'])
            .exclude(content__startswith='__TOOL_CALLS__')
            .order_by('-timestamp')[:30]
            .values('timestamp', 'role', 'content', 'session__session_id')
        )
    except Exception as exc:
        logger.error("chatbot_stats recent_messages error: %s", exc)
        recent_messages = []

    context = {
        'admin':                   admin,
        'timeframe':               timeframe,
        'total_sessions':          total_sessions,
        'sessions_today':          sessions_today,
        'total_questions':         total_questions,
        'total_answers':           total_answers,
        'total_agent_searches':    total_agent_searches,
        'total_api_calls':         total_api_calls,
        'avg_latency':             round(avg_latency, 3),
        'avg_ttft':                round(avg_ttft, 3),
        'live_sessions_count':     live_sessions_count,
        'total_completion_tokens': total_completion_tokens,
        'total_tokens':            total_tokens,
        'provider_stats':          provider_stats,
        'groq_details':            groq_details,
        'recent_calls':            recent_calls,
        'recent_sessions':         recent_sessions,
        'recent_messages':         recent_messages,
        'chart_labels_json':           json.dumps(chart_labels),
        'chart_values_json':           json.dumps(chart_values),
        'token_chart_labels_json':     json.dumps(token_chart_labels),
        'token_chart_prompt_json':     json.dumps(token_chart_prompt),
        'token_chart_completion_json': json.dumps(token_chart_completion),
        'timeframe':               timeframe,
    }

    return render(request, 'admin/chatbot/stats.html', context)


from django.http import JsonResponse

def load_more_messages(request):
    """AJAX endpoint to load older messages for the Recent Conversations table."""
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        offset = int(request.GET.get('offset', 30))
        limit = 30
    except ValueError:
        return JsonResponse({'error': 'Invalid offset'}, status=400)

    # Use the same base queryset constraints as the main stats page
    now = timezone.now()
    days = 30  # Default timeframe
    start_date = now - timedelta(days=days)
    
    messages = list(
        ChatMessage.objects.filter(session__is_test_traffic=False, timestamp__gte=start_date)
        .filter(role__in=['user', 'assistant'])
        .exclude(content__startswith='__TOOL_CALLS__')
        .order_by('-timestamp')[offset:offset+limit]
        .values('timestamp', 'role', 'content', 'session__session_id')
    )

    # Format data for JSON response
    data = []
    for m in messages:
        timestamp_str = m['timestamp'].strftime("%d %b %H:%M:%S") if m['timestamp'] else ""
        content = m['content'] or ""
        content_trunc = (content[:117] + '...') if len(content) > 120 else content
        
        data.append({
            'timestamp_str': timestamp_str,
            'role': m['role'],
            'content': content,
            'content_trunc': content_trunc,
            'session_id': m['session__session_id']
        })

    return JsonResponse({'messages': data})


def chatbot_session_detail(request, session_id):
    """Full conversation thread for a single chat session."""
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect('admin_login')

    try:
        session = ChatSession.objects.get(session_id=session_id)
    except ChatSession.DoesNotExist:
        from django.http import Http404
        raise Http404("Session not found")

    import re

    def strip_markdown(text):
        """Remove markdown syntax so the admin panel shows clean readable text."""
        if not text:
            return ''
        # **bold** or __bold__ → plain text
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        # *italic* or _italic_ → plain text
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        # [link text](url) → link text
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        return text

    # Use 'chat_messages' NOT 'messages' — avoids clash with Django's
    # built-in messages framework which base.html renders as alert boxes
    chat_messages = list(
        ChatMessage.objects.filter(session=session)
        .order_by('timestamp')
        .values('role', 'content', 'timestamp', 'tool_name', 'agent_cards')
    )

    for m in chat_messages:
        m['is_user']      = m['role'] == 'user'
        m['is_assistant'] = m['role'] == 'assistant' and not (m['content'] or '').startswith('__TOOL_CALLS__')
        m['is_tool']      = m['role'] == 'tool'
        m['is_tool_call'] = m['role'] == 'assistant' and (m['content'] or '').startswith('__TOOL_CALLS__')

        if m['is_tool_call']:
            m['display_content'] = '[Tool call: find_agents]'
        elif m['is_tool']:
            raw = m['content'] or ''
            m['display_content'] = (raw[:300] + '…') if len(raw) > 300 else raw
        else:
            # Strip markdown so **Health** shows as Health, not **Health**
            m['display_content'] = strip_markdown(m['content'] or '')

    context = {
        'admin':         admin,
        'session':       session,
        'session_id':    session_id,
        'chat_messages': chat_messages,   # safe name — no clash with Django messages
    }
    return render(request, 'admin/chatbot/session_detail.html', context)

