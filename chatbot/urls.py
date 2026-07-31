from django.urls import path
from . import views

app_name = 'chatbot'

urlpatterns = [
    path('chips/', views.get_chips, name='chips'),
    path('history/<str:session_id>/', views.get_history, name='history'),
    path('message/', views.send_message, name='message'),
]
