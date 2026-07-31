import os
import django
import sys
import json

sys.path.append(r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padosi_agent.settings")
django.setup()

from apps.home.views.pages import build_agent_query

# 1. Chatbot args (Based on log: "insurance_type":"Health","pincode":"380008","service_type":"New Policy", location="area" then retried with location="")
agents_chat, _, _, _ = build_agent_query(
    pincode="380008", location="", lat="", lng="", detected_area="",
    service_type_input=["New Policy"], insurance_type_input=["Health"],
    insurance_company_input=[], claim_company_input="", search_val="", sort_by=""
)

# 2. UI args (Based on URL: pincode=380008, lat="", lng="", location="", sort_by="distance", ServiceType="Buying new insurance", InsuranceType="Health Insurance")
agents_ui, _, _, _ = build_agent_query(
    pincode="380008", location="", lat="", lng="", detected_area="",
    service_type_input=["Buying new insurance"], insurance_type_input=["Health Insurance"],
    insurance_company_input=[], claim_company_input="", search_val="", sort_by="match"
)

print("--- Chatbot Agents ---")
for i, a in enumerate(agents_chat[:50]):
    print(f"{i+1}. {a.fullname} (ID: {a.id}, Dist: {getattr(a, 'distance', 'N/A')}, Rank: {getattr(a, 'padosi_smart_rank', 'N/A')})")

print("\n--- UI Agents ---")
for i, a in enumerate(agents_ui[:50]):
    print(f"{i+1}. {a.fullname} (ID: {a.id}, Dist: {getattr(a, 'distance', 'N/A')}, Rank: {getattr(a, 'padosi_smart_rank', 'N/A')})")

if agents_chat[:5] == agents_ui[:5]:
    print("\nRESULTS ARE EXACTLY THE SAME!")
else:
    print("\nRESULTS DIFFER!")
