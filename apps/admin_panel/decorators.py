from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def admin_login_required(view_func):
    """
    Decorator for views that checks that the user is logged in as an admin via session guard.
    Redirects to the admin login page if not.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.session.get('admin_id'):
            messages.error(request, "Please sign in to access the admin panel.")
            return redirect('admin_panel:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
