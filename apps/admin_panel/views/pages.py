"""
apps/admin_panel/views/pages.py

Admin CMS Pages manager — full CRUD for static custom pages.

Laravel source: app/Http/Controllers/Admin/AdminPageController.php
Routes:
  GET  /admin/pages/                  → pages_index
  GET  /admin/pages/create/           → pages_create
  POST /admin/pages/store/            → pages_store
  GET  /admin/pages/<id>/edit/        → pages_edit
  POST /admin/pages/<id>/update/      → pages_update
  POST /admin/pages/<id>/delete/      → pages_delete  (AJAX-compatible)
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils.text import slugify

from apps.home.models.page import Page
from apps.admin_panel.models.admin_activity_log import AdminActivityLog
from apps.admin_panel.views.dashboard import _get_admin_from_session


def pages_index(request):
    """List all CMS pages ordered by most-recently updated."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    pages = Page.objects.all().order_by('-updated_at')
    return render(request, 'admin/pages/index.html', {'pages': pages})


def pages_create(request):
    """Show the create-page form (empty)."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    return render(request, 'admin/pages/edit.html', {'page': None})


def pages_store(request):
    """Save a new CMS page."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    if request.method == 'POST':
        title   = request.POST.get('title', '').strip()
        slug    = request.POST.get('slug', '').strip()
        content = request.POST.get('content', '').strip()

        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/pages/edit.html', {'page': None})

        slug = slugify(slug) if slug else slugify(title)

        if Page.objects.filter(slug=slug).exists():
            messages.error(request, 'A page with this URL slug already exists.')
            return render(request, 'admin/pages/edit.html', {'page': None})

        page = Page.objects.create(
            title=title,
            slug=slug,
            content=content,
            meta_title=request.POST.get('meta_title', '').strip() or None,
            meta_description=request.POST.get('meta_description', '').strip() or None,
            is_active='is_active' in request.POST,
            is_raw_code='is_raw_code' in request.POST,
        )
        AdminActivityLog.log(f'Created Page #{page.id}: {page.title}', 'Page', request=request)
        messages.success(request, 'Page created successfully.')
        return redirect('admin_pages_index')

    return redirect('admin_pages_index')


def pages_edit(request, page_id):
    """Show the edit-page form pre-filled with existing page data."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    page = get_object_or_404(Page, id=page_id)
    return render(request, 'admin/pages/edit.html', {'page': page})


def pages_update(request, page_id):
    """Update an existing CMS page."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return redirect('admin_login')

    page = get_object_or_404(Page, id=page_id)

    if request.method == 'POST':
        title   = request.POST.get('title', '').strip()
        slug    = request.POST.get('slug', '').strip()
        content = request.POST.get('content', '').strip()

        if not title:
            messages.error(request, 'Title is required.')
            return render(request, 'admin/pages/edit.html', {'page': page})

        slug = slugify(slug) if slug else slugify(title)

        if Page.objects.filter(slug=slug).exclude(id=page.id).exists():
            messages.error(request, 'A page with this URL slug already exists.')
            return render(request, 'admin/pages/edit.html', {'page': page})

        page.title            = title
        page.slug             = slug
        page.content          = content
        page.meta_title       = request.POST.get('meta_title', '').strip() or None
        page.meta_description = request.POST.get('meta_description', '').strip() or None
        page.is_active        = 'is_active' in request.POST
        page.is_raw_code      = 'is_raw_code' in request.POST
        page.save()

        AdminActivityLog.log(f'Updated Page #{page.id}: {page.title}', 'Page', request=request)
        messages.success(request, 'Page updated successfully.')
        return redirect('admin_pages_index')

    return redirect('admin_pages_index')


def pages_delete(request, page_id):
    """Delete a CMS page. Returns JSON if AJAX request, otherwise redirects."""
    admin_id = _get_admin_from_session(request)
    if not admin_id:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
        return redirect('admin_login')

    page = get_object_or_404(Page, id=page_id)

    if request.method == 'POST':
        title = page.title
        page.delete()
        AdminActivityLog.log(f'Deleted Page #{page_id}: {title}', 'Page', request=request)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Page deleted successfully.'})

        messages.success(request, 'Page deleted successfully.')

    return redirect('admin_pages_index')
