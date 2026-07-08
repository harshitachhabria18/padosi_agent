import logging
import json
from django.db import connection
from django.http import JsonResponse
from .dashboard import _get_admin_from_session

logger = logging.getLogger(__name__)

def admin_delete(request):
    """
    Phase 6B.5: Generic admin delete handler
    Replaces delete_agent() and supports multiple models matching Laravel's AdminDeleteController.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

    admin_id = _get_admin_from_session(request)
    if not admin_id:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body)
            record_id = data.get('id')
            model = data.get('model')
        else:
            record_id = request.POST.get('id')
            model = request.POST.get('model')
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid data format'}, status=400)

    if not model or not record_id:
        return JsonResponse({'success': False, 'message': 'Missing model or id'}, status=400)

    try:
        with connection.cursor() as cursor:
            if model == 'agent':
                # 1. Fetch user_id from agents
                cursor.execute("SELECT user_id FROM agents WHERE id = %s", [record_id])
                agent_row = cursor.fetchone()
                if not agent_row:
                    return JsonResponse({'success': False, 'message': 'Record not found'}, status=404)
                user_id = agent_row[0]
                
                # 2. Suspend the linked user account
                if user_id:
                    cursor.execute("UPDATE users SET status = 'suspended' WHERE id = %s", [user_id])
                
                # 3. Delete the agent record
                cursor.execute("DELETE FROM agents WHERE id = %s", [record_id])

            elif model == 'user':
                cursor.execute("SELECT id, role FROM users WHERE id = %s", [record_id])
                user_row = cursor.fetchone()
                if not user_row:
                    return JsonResponse({'success': False, 'message': 'Record not found'}, status=404)
                
                user_role = user_row[1]
                
                if user_role == 'distributor':
                    # Distributor Deletion: Suspend the user and remove from Distributors module
                    # by changing the role, ensuring they remain in the Users module.
                    cursor.execute("UPDATE users SET status = 'suspended' WHERE id = %s", [record_id])
                    cursor.execute("UPDATE users SET role = 'client' WHERE id = %s", [record_id])
                else:
                    # Generic User hard-delete behavior
                    cursor.execute("DELETE FROM users WHERE id = %s", [record_id])

            elif model == 'lead':
                cursor.execute("DELETE FROM agent_leads WHERE id = %s", [record_id])

            elif model == 'promo_code':
                cursor.execute("DELETE FROM promo_codes WHERE id = %s", [record_id])

            elif model == 'Faq':
                cursor.execute("DELETE FROM faqs WHERE id = %s", [record_id])

            else:
                return JsonResponse({'success': False, 'message': 'Invalid model type'}, status=400)

        # Log the deletion
        logger.info(f"Admin deleted record: model={model}, record_id={record_id}, admin_id={admin_id}, ip={request.META.get('REMOTE_ADDR')}")

        return JsonResponse({
            'success': True,
            'message': 'Record deleted successfully'
        })
    except Exception as e:
        logger.error(f"Admin delete failed: {e}")
        return JsonResponse({
            'success': False,
            'message': 'Failed to delete record: ' + str(e)
        }, status=500)
