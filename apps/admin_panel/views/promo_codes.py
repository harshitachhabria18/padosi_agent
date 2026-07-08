import json
from django.shortcuts import render, redirect
from django.http import JsonResponse, Http404
from django.db import connection
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .dashboard import _get_admin_from_session

@require_http_methods(["GET"])
def promo_code_list(request):
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, code, discount_type, discount_value, applicable_plan, 
                   times_used, max_uses, expires_at, is_active
            FROM promo_codes
            ORDER BY id DESC
        """)
        
        columns = [col[0] for col in cursor.description]
        promo_codes = []
        for row in cursor.fetchall():
            promo = dict(zip(columns, row))
            promo_codes.append(promo)

    context = {
        'admin': admin,
        'promo_codes': promo_codes,
    }

    return render(request, "admin/promo_codes/index.html", context)

@csrf_exempt
@require_http_methods(["POST"])
def toggle_promo_code_status(request, promo_id):
    admin = _get_admin_from_session(request)
    if not admin:
        return JsonResponse({"success": False, "message": "Unauthorized"}, status=401)

    with connection.cursor() as cursor:
        cursor.execute("SELECT is_active FROM promo_codes WHERE id = %s", [promo_id])
        row = cursor.fetchone()
        if not row:
            return JsonResponse({"success": False, "message": "Promo code not found."}, status=404)

        current_status = row[0]
        new_status = 0 if current_status else 1

        cursor.execute("UPDATE promo_codes SET is_active = %s WHERE id = %s", [new_status, promo_id])
        
    return JsonResponse({
        "success": True,
        "is_active": bool(new_status),
        "message": "Status updated successfully."
    })

@require_http_methods(["POST"])
def store_promo_code(request):
    from django.contrib import messages
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    code = request.POST.get("code", "").strip()
    discount_type = request.POST.get("discount_type")
    discount_value = request.POST.get("discount_value")
    applicable_plan = request.POST.get("applicable_plan") or None
    max_uses = request.POST.get("max_uses") or None
    expires_at = request.POST.get("expires_at") or None

    if not code or discount_type not in ["percentage", "fixed"] or not discount_value:
        messages.error(request, "Invalid input data.")
        return redirect("admin_promo_codes")
        
    if applicable_plan and applicable_plan not in ["basic", "professional"]:
        messages.error(request, "Invalid applicable plan.")
        return redirect("admin_promo_codes")
        
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM promo_codes WHERE code = %s", [code])
        if cursor.fetchone():
            messages.error(request, "The code has already been taken.")
            return redirect("admin_promo_codes")
            
        cursor.execute("""
            INSERT INTO promo_codes (
                code, discount_type, discount_value, applicable_plan, 
                max_uses, expires_at, is_active, times_used, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 1, 0, NOW(), NOW())
        """, [code, discount_type, discount_value, applicable_plan, max_uses, expires_at])

    messages.success(request, "Promo Code created successfully.")
    return redirect("admin_promo_codes")

@require_http_methods(["POST"])
def update_promo_code(request, promo_id):
    from django.contrib import messages
    admin = _get_admin_from_session(request)
    if not admin:
        return redirect("admin_login_page")

    code = request.POST.get("code", "").strip()
    discount_type = request.POST.get("discount_type")
    discount_value = request.POST.get("discount_value")
    applicable_plan = request.POST.get("applicable_plan") or None
    max_uses = request.POST.get("max_uses") or None
    expires_at = request.POST.get("expires_at") or None

    if not code or discount_type not in ["percentage", "fixed"] or not discount_value:
        messages.error(request, "Invalid input data.")
        return redirect("admin_promo_codes")

    if applicable_plan and applicable_plan not in ["basic", "professional"]:
        messages.error(request, "Invalid applicable plan.")
        return redirect("admin_promo_codes")

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM promo_codes WHERE code = %s AND id != %s", [code, promo_id])
        if cursor.fetchone():
            messages.error(request, "The code has already been taken.")
            return redirect("admin_promo_codes")
            
        cursor.execute("""
            UPDATE promo_codes SET
                code = %s, discount_type = %s, discount_value = %s, applicable_plan = %s,
                max_uses = %s, expires_at = %s, updated_at = NOW()
            WHERE id = %s
        """, [code, discount_type, discount_value, applicable_plan, max_uses, expires_at, promo_id])

    messages.success(request, "Promo Code updated successfully.")
    return redirect("admin_promo_codes")
