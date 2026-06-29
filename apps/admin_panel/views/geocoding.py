import json
import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q

from apps.admin_panel.decorators import admin_login_required
from apps.agents.models import Agent
from apps.home.models.pincode import PincodeCache
from apps.home.services.geocoding import GeocodingService

logger = logging.getLogger(__name__)

@admin_login_required
def index(request):
    total = Agent.objects.filter(status='active').count()
    geocoded = Agent.objects.filter(status='active', latitude__isnull=False, longitude__isnull=False).count()
    missing = total - geocoded
    
    has_pin_no_coords = Agent.objects.filter(status='active', latitude__isnull=True).exclude(agent_pincode=None).exclude(agent_pincode='').count()
    cached = PincodeCache.objects.count()
    
    recent_geocoded = Agent.objects.filter(status='active', latitude__isnull=False, longitude__isnull=False).order_by('-updated_at')[:50]
    
    # Fetch active agents missing coords
    missing_geo_raw = Agent.objects.filter(status='active', latitude__isnull=True).order_by('-created_at')[:100]
    
    # Filter list to only show agents that have a valid effective pincode (either direct or profile service pincodes)
    missing_geo = []
    for ag in missing_geo_raw:
        eff_pin = ag.get_effective_pincode()
        if eff_pin:
            ag.eff_pincode = eff_pin
            missing_geo.append(ag)
            
    # Calculate percentage
    pct = round((geocoded / total) * 100) if total > 0 else 0
    
    context = {
        'totalAgents': total,
        'geocodedAgents': geocoded,
        'missingAgents': missing,
        'hasPincodeNoCoords': has_pin_no_coords,
        'cachedPincodes': cached,
        'recentGeocodedAgents': recent_geocoded,
        'missingGeoAgents': missing_geo,
        'pct': pct,
    }
    return render(request, 'admin/geocoding_manager.html', context)

@admin_login_required
def geocode_single(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed.'}, status=405)
        
    try:
        body = json.loads(request.body)
        agent_id = body.get('agent_id')
    except Exception:
        # Fallback to POST parameters
        agent_id = request.POST.get('agent_id')
        
    if not agent_id:
        return JsonResponse({'success': False, 'message': 'Agent ID is required.'}, status=400)
        
    try:
        agent = Agent.objects.get(status='active', id=agent_id)
    except Agent.DoesNotExist:
        return JsonResponse({'success': False, 'message': f'Active agent #{agent_id} not found.'}, status=404)
        
    pincode = agent.get_effective_pincode()
    if not pincode:
        return JsonResponse({
            'success': False,
            'message': f"Agent #{agent.id} has no valid pincode set. Please set a pincode first."
        }, status=422)
        
    try:
        geo = GeocodingService()
        coords = geo.resolve_coordinates(pincode)
        
        if not coords:
            return JsonResponse({
                'success': False,
                'message': f"Could not resolve coordinates for pincode {pincode}."
            }, status=422)
            
        agent.save_location(pincode, coords['lat'], coords['lng'])
        logger.info(f"[Admin GeoManager] Single geocode: Agent #{agent.id} ({pincode}) -> {coords['lat']},{coords['lng']}")
        
        return JsonResponse({
            'success': True,
            'message': f"✅ Agent #{agent.id} geocoded: {pincode} -> {coords['lat']}, {coords['lng']}",
            'lat': coords['lat'],
            'lng': coords['lng'],
            'display': coords.get('display_name') or pincode,
        })
    except Exception as e:
        logger.error(f"[Admin GeoManager] Single geocode failed: Agent #{agent.id} - {str(e)}")
        return JsonResponse({'success': False, 'message': f"Error: {str(e)}"}, status=500)

@admin_login_required
def geocode_batch(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed.'}, status=405)
        
    try:
        body = json.loads(request.body)
        offset = int(body.get('offset', 0))
    except Exception:
        offset = int(request.POST.get('offset', 0))
        
    batch_size = 5
    
    # Active agents missing coords (prefer those with agent_pincode set)
    # We order by whether agent_pincode is empty/null, then by id
    agents = Agent.objects.filter(status='active', latitude__isnull=True)
    
    # To prefer those with agent_pincode set, we can sort them
    # agent_pincode="" or null will be last. In Django we can use Q or order_by
    agents = list(agents.order_by('id'))
    # Let's sort in python: has pincode first, then no pincode
    agents.sort(key=lambda a: 1 if not a.agent_pincode else 0)
    
    # Slice using offset
    agents_slice = agents[offset:offset+batch_size]
    
    if not agents_slice:
        return JsonResponse({
            'success': True,
            'done': True,
            'message': 'All agents have been processed.',
            'processed': 0,
            'results': [],
        })
        
    geo = GeocodingService()
    results = []
    
    for agent in agents_slice:
        pincode = agent.get_effective_pincode()
        if not pincode:
            results.append({
                'agent_id': agent.id,
                'name': agent.fullname,
                'pincode': '—',
                'status': 'skipped',
                'message': 'No valid pincode',
            })
            continue
            
        try:
            coords = geo.resolve_coordinates(pincode)
            if coords:
                agent.save_location(pincode, coords['lat'], coords['lng'])
                results.append({
                    'agent_id': agent.id,
                    'name': agent.fullname,
                    'email': agent.email,
                    'pincode': pincode,
                    'status': 'success',
                    'message': f"{coords['lat']}, {coords['lng']} ({coords.get('display_name', '')})",
                    'lat': coords['lat'],
                    'lng': coords['lng'],
                })
            else:
                results.append({
                    'agent_id': agent.id,
                    'name': agent.fullname,
                    'pincode': pincode,
                    'status': 'failed',
                    'message': 'Could not resolve coordinates',
                })
        except Exception as e:
            results.append({
                'agent_id': agent.id,
                'name': agent.fullname,
                'pincode': pincode,
                'status': 'error',
                'message': str(e),
            })
            
    # Check how many remain
    remaining = Agent.objects.filter(status='active', latitude__isnull=True).count()
    logger.info(f"[Admin GeoManager] Batch offset={offset}, processed={len(results)}, remaining={remaining}")
    
    return JsonResponse({
        'success': True,
        'done': remaining == 0,
        'remaining': remaining,
        'processed': len(results),
        'results': results,
    })

@admin_login_required
def stats(request):
    total = Agent.objects.filter(status='active').count()
    geocoded = Agent.objects.filter(status='active', latitude__isnull=False, longitude__isnull=False).count()
    missing = total - geocoded
    cached = PincodeCache.objects.count()
    has_pin_no_coords = Agent.objects.filter(status='active', latitude__isnull=True).exclude(agent_pincode=None).exclude(agent_pincode='').count()
    
    pct = round((geocoded / total) * 100) if total > 0 else 0
    
    return JsonResponse({
        'total': total,
        'geocoded': geocoded,
        'missing': missing,
        'cached': cached,
        'hasPinNoCoords': has_pin_no_coords,
        'pct': pct,
    })
