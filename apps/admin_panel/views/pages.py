from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils.text import slugify
from apps.home.models.page import Page
from apps.admin_panel.models.admin_activity_log import AdminActivityLog
from apps.admin_panel.decorators import admin_login_required

@admin_login_required
def index(request):
    pages = Page.objects.all().order_by('-updated_at')
    return render(request, 'admin/pages/index.html', {'pages': pages})

@admin_login_required
def create(request):
    return render(request, 'admin/pages/edit.html', {'page': None})

@admin_login_required
def store(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        slug = request.POST.get('slug', '').strip()
        content = request.POST.get('content', '').strip()
        
        if not title:
            messages.error(request, 'Title is required.')
            return redirect('admin_panel:pages_create')
            
        if not slug:
            slug = slugify(title)
        else:
            slug = slugify(slug)
            
        if Page.objects.filter(slug=slug).exists():
            messages.error(request, 'A page with this URL slug already exists.')
            return render(request, 'admin/pages/edit.html', {'page': None, 'errors': True})
            
        page = Page.objects.create(
            title=title,
            slug=slug,
            content=content,
            meta_title=request.POST.get('meta_title', '').strip() or None,
            meta_description=request.POST.get('meta_description', '').strip() or None,
            is_active='is_active' in request.POST,
            is_raw_code='is_raw_code' in request.POST
        )
        AdminActivityLog.log(f'Created Page #{page.id}', 'Page', request=request)
        messages.success(request, 'Page created successfully.')
        return redirect('admin_panel:pages_index')
    return redirect('admin_panel:pages_index')

@admin_login_required
def edit(request, page_id):
    page = get_object_or_404(Page, id=page_id)
    return render(request, 'admin/pages/edit.html', {'page': page})

@admin_login_required
def update(request, page_id):
    page = get_object_or_404(Page, id=page_id)
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        slug = request.POST.get('slug', '').strip()
        content = request.POST.get('content', '').strip()
        
        if not title:
            messages.error(request, 'Title is required.')
            return redirect('admin_panel:pages_edit', page_id=page.id)
            
        if not slug:
            slug = slugify(title)
        else:
            slug = slugify(slug)
            
        if Page.objects.filter(slug=slug).exclude(id=page.id).exists():
            messages.error(request, 'A page with this URL slug already exists.')
            return render(request, 'admin/pages/edit.html', {'page': page, 'errors': True})
            
        page.title = title
        page.slug = slug
        page.content = content
        page.meta_title = request.POST.get('meta_title', '').strip() or None
        page.meta_description = request.POST.get('meta_description', '').strip() or None
        page.is_active = 'is_active' in request.POST
        page.is_raw_code = 'is_raw_code' in request.POST
        page.save()
        
        AdminActivityLog.log(f'Updated Page #{page.id}', 'Page', request=request)
        messages.success(request, 'Page updated successfully.')
        return redirect('admin_panel:pages_index')
    return redirect('admin_panel:pages_index')

@admin_login_required
def delete(request, page_id):
    page = get_object_or_404(Page, id=page_id)
    if request.method == 'POST':
        page.delete()
        AdminActivityLog.log(f'Deleted Page #{page_id}', 'Page', request=request)
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'message': 'Page deleted successfully.'})
            
        messages.success(request, 'Page deleted successfully.')
    return redirect('admin_panel:pages_index')
