import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.agents.models import Agent
from apps.home.services.distance import DistanceService
from django.db.models.expressions import RawSQL

def test():
    # Coordinates of Ahmedabad (Vejalpur/Ahmedabad is ~ 23.0222732, 72.5279775)
    user_lat = 23.0222732
    user_lng = 72.5279775
    db_types = []
    
    # 1. Base Query without select_related('user')
    query = Agent.objects.filter(status='active', user__isnull=False)
    query = query.select_related('profile', 'performanceStats').prefetch_related(
        'insuranceSegments', 'reviews', 'serviceableCities', 'productExpertise'
    )
    print("Base count:", query.count())
    
    filter_match_sql = "(SELECT COUNT(*) FROM agent_insurance_segments WHERE agent_insurance_segments.agent_id = agents.id AND 1=0)"
    
    # Updated smart_rank_expr checking both users and auth_user
    smart_rank_expr = f"""
        (CASE 
            WHEN CAST(COALESCE(NULLIF(agents.experience_range, ''), NULLIF((SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id), 0), 0) AS UNSIGNED) >= 15 THEN 20 
            ELSE (CAST(COALESCE(NULLIF(agents.experience_range, ''), NULLIF((SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id), 0), 0) AS UNSIGNED) / 15) * 20 
        END) +
        (CASE WHEN agents.client_base >= 500 THEN 20 ELSE (IFNULL(agents.client_base, 0) / 500) * 20 END) +
        (CASE 
            WHEN (SELECT IFNULL(claims_processed, 0) FROM agent_performance_stats WHERE agent_performance_stats.agent_id = agents.id) >= 100 THEN 20 
            ELSE (SELECT IFNULL(claims_processed, 0) FROM agent_performance_stats WHERE agent_performance_stats.agent_id = agents.id) / 100 * 20 
        END) +
        (CASE WHEN agents.badge IS NOT NULL AND agents.badge != 'none' AND agents.badge != '' THEN 15 ELSE 0 END) +
        (CASE WHEN (SELECT AVG(rating) FROM agent_reviews WHERE agent_reviews.agent_id = agents.id AND agent_reviews.is_approved = 1) >= 4.5 THEN 10 ELSE 0 END) +
        (CASE 
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 3 DAY) THEN 50
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 14 DAY) THEN 25
            WHEN COALESCE(
                (SELECT last_login_at FROM users WHERE users.id = agents.user_id),
                (SELECT last_login FROM auth_user WHERE auth_user.id = agents.user_id)
            ) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY) THEN 10
            ELSE 0
        END) +
        ((
            (CASE WHEN (SELECT profile_photo_path FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT profile_photo_path FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT address FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT address FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (agents.experience_range IS NOT NULL AND agents.experience_range != '') OR (SELECT experience_years FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) > 0 THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT whatsapp FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT whatsapp FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT license_number FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT license_number FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END) +
            (CASE WHEN (SELECT languages FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) IS NOT NULL AND (SELECT languages FROM agent_profiles WHERE agent_profiles.agent_id = agents.id) != '' THEN 1 ELSE 0 END)
        ) * 5) +
        ({filter_match_sql} * 30)
    """

    query = query.annotate(padosi_smart_rank=RawSQL(smart_rank_expr, []))
    
    try:
        all_agents = list(query)
        print("Successfully fetched agents. Count:", len(all_agents))
    except Exception as e:
        print("ERROR running query:", e)
        return

    # Calculate proximity
    in_50km = []
    for agent in all_agents:
        agent.distance = None
        agent_coords = None
        if agent.latitude and agent.longitude:
            agent_coords = {'lat': float(agent.latitude), 'lng': float(agent.longitude)}
        
        if not agent_coords and agent.profile:
            agent_pincodes = agent.profile.service_pincodes
            if agent_pincodes and isinstance(agent_pincodes, list):
                agent_pincode = agent_pincodes[0]
                agent_coords = DistanceService.get_pincode_coordinates(agent_pincode)
        
        if not agent_coords and agent.profile and agent.profile.office_address:
            # Let's try office address or state
            pass

        if agent_coords:
            agent.distance = DistanceService.calculate(user_lat, user_lng, agent_coords['lat'], agent_coords['lng'])
            if agent.distance is not None and agent.distance <= 50:
                in_50km.append(agent)
                print(f"Agent {agent.fullname} matched: coordinates={agent_coords}, distance={agent.distance} km")
        else:
            agent.distance = 999999
            
    print(f"Total agents within 50km: {len(in_50km)}")

if __name__ == '__main__':
    test()
