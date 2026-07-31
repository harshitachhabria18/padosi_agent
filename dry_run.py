import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from apps.home.views.pages import build_agent_query
from apps.home.services.distance import DistanceService

scenarios = [
    {
        "name": "Scenario 1: Cyber (SME) at 380002",
        "params": {
            "search_query": "",
            "insurance_type": "SME",
            "insurance_company": "Cyber",
            "location_name": "",
            "pincode": "380002",
            "db_types": ["cyber"],
            "sort_by": "distance"
        }
    },
    {
        "name": "Scenario 2: Mediclaim (Health) at 380002",
        "params": {
            "search_query": "",
            "insurance_type": "Health",
            "insurance_company": "Mediclaim",
            "location_name": "",
            "pincode": "380002",
            "db_types": ["mediclaim"],
            "sort_by": "distance"
        }
    },
    {
        "name": "Scenario 3: Private Car (Motor) at 380015",
        "params": {
            "search_query": "",
            "insurance_type": "Motor",
            "insurance_company": "Private Car",
            "location_name": "",
            "pincode": "380015",
            "db_types": ["private car"],
            "sort_by": "distance"
        }
    }
]

def calculate_composite(agent, max_smart_rank):
    dist = agent.distance if agent.distance is not None else 50.0
    distance_score = max(0.0, 100.0 - (dist * 2.0))
    
    rank = agent.padosi_smart_rank or 0
    smart_rank_score = min(100.0, (rank / 165.0) * 100.0)
    
    rating = getattr(agent, 'average_rating', 0.0)
    rating_score = (rating / 5.0) * 100.0 if rating > 0 else 80.0
    
    exp = getattr(agent, 'experience_years', 0)
    exp_score = min(100.0, (exp / 15.0) * 100.0) if exp > 0 else 50.0
    
    composite = (distance_score * 0.45) + (smart_rank_score * 0.25) + (rating_score * 0.15) + (exp_score * 0.15)
    return composite, distance_score, smart_rank_score, rating_score, exp_score

for scenario in scenarios:
    print(f"\n{'='*50}\n{scenario['name']}\n{'='*50}")
    params = scenario["params"]
    
    user_coords = DistanceService.get_pincode_coordinates(params['pincode'])
    user_lat, user_lng = (user_coords['lat'], user_coords['lng']) if user_coords else (None, None)
    
    agents, max_smart_rank, invalid_pincode, detected_area_out = build_agent_query(
        pincode=params['pincode'],
        location=params.get('location_name', ''),
        lat=user_lat,
        lng=user_lng,
        detected_area='',
        service_type_input=['New Policy'],
        insurance_type_input=[params['insurance_type']],
        insurance_company_input=[params['insurance_company']] if params['insurance_company'] else [],
        claim_company_input='',
        search_val=params.get('search_query', ''),
        sort_by=params['sort_by']
    )
    
    print("\n--- OLD SORT (Top 3 by Distance) ---")
    for i, a in enumerate(agents[:3]):
        print(f"{i+1}. {a.fullname[:20]:<20} | Dist: {a.distance:>5.1f}km | Match%: {a.match_percent:>3}% | Exp: {getattr(a, 'experience_years', 0):>2} | Rate: {getattr(a, 'average_rating', 0.0):>3.1f}")
        
    print("\n--- NEW SORT (Top 3 by Composite) ---")
    
    # Calculate and attach composite score
    for a in agents:
        comp, d_s, sr_s, r_s, e_s = calculate_composite(a, max_smart_rank)
        a.composite_score = comp
        a._debug_scores = f"(D:{d_s:.1f} R:{sr_s:.1f} Rt:{r_s:.1f} E:{e_s:.1f})"
        
    # Sort by composite desc, then exact distance asc, then smart rank desc
    composite_agents = sorted(agents, key=lambda x: (
        -x.composite_score,
        x.distance if x.distance is not None else 999999,
        -(x.padosi_smart_rank or 0)
    ))
    
    for i, a in enumerate(composite_agents[:3]):
        print(f"{i+1}. {a.fullname[:20]:<20} | Comp: {a.composite_score:>5.1f} | Dist: {a.distance:>5.1f}km | Match%: {a.match_percent:>3}% | Exp: {getattr(a, 'experience_years', 0):>2} | Rate: {getattr(a, 'average_rating', 0.0):>3.1f}")
