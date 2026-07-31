from django.contrib import admin
from .models import ChatSession, ChatMessage, LatencyLog

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'is_test_traffic', 'created_at')
    list_editable = ('is_test_traffic',)
    list_filter = ('is_test_traffic',)
    search_fields = ('session_id',)

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('session', 'role', 'timestamp')
    list_filter = ('role', 'timestamp')
    search_fields = ('session__session_id', 'content')

@admin.register(LatencyLog)
class LatencyLogAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'total_time', 'created_at')
    list_filter = ('endpoint',)
