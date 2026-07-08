from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from apps.admin_panel.views.dashboard import _get_admin_from_session

def admin_login_required(view_func):
    """
    Decorator for views that checks that the user is logged in as an admin via session guard.
    Redirects to the admin login page if not.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        admin_id = _get_admin_from_session(request)
        if not admin_id:
            messages.error(request, "Please sign in to access the admin panel.")
            return redirect('admin_login_page')
        # Inject admin_id in request so the view can access it
        request.admin_id = admin_id
        return view_func(request, *args, **kwargs)
    return _wrapped_view
