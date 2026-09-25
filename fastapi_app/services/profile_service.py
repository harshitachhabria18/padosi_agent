from fastapi import HTTPException
import json
import logging
from fastapi_app.repositories.agent_repository import AgentRepository
from fastapi_app.schemas.profile import (
    AgentProfileResponse,
    AgentProfileUpdateRequest,
    BasicProfileUpdateRequest,
    ProfessionalProfileUpdateRequest,
    PortfolioProfileUpdateRequest,
    AdditionalProfileUpdateRequest,
)
from fastapi_app.config import settings
from fastapi_app.services.lock_unlock_service import LockUnlockService

logger = logging.getLogger(__name__)


def clean_investment_types(types):
    if not types:
        return []
    if isinstance(types, str):
        try:
            types = json.loads(types)
        except Exception:
            types = [types]
    if not isinstance(types, list):
        types = [types]
    normalized = []
    has_sip_stp_swp = False
    for t in types:
        if not t:
            continue
        t_lower = str(t).strip().lower()
        if t_lower in ['sip', 'stp', 'swp', 'sip/stp/swp']:
            if not has_sip_stp_swp:
                normalized.append('SIP/STP/SWP')
                has_sip_stp_swp = True
        elif t_lower == 'bonds':
            continue
        else:
            if t_lower == 'lumpsum':
                normalized.append('Lumpsum')
            elif t_lower == 'elss':
                normalized.append('ELSS')
            elif t_lower == 'pms':
                normalized.append('PMS')
            elif t_lower == 'nps':
                normalized.append('NPS')
            elif t_lower == 'aif':
                normalized.append('AIF')
            else:
                normalized.append(str(t).strip())
    return normalized


def _is_own_photo_url(url):
    """True for our own upload targets: local /media/ paths or Cloudinary HTTPS URLs."""
    from urllib.parse import urlparse
    value = str(url or "").strip()
    if value.startswith("/media/") and ".." not in value:
        return True
    parsed = urlparse(value)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "res.cloudinary.com"

# Database models for updates
from fastapi_app.models.agent import Agent
from fastapi_app.models.agent_profile import AgentProfile
from fastapi_app.models.agent_service_pincode import AgentServicePincode
from fastapi_app.models.agent_serviceable_city import AgentServiceableCity
from fastapi_app.models.city import City
from fastapi_app.models.agent_family_license import AgentFamilyLicense
from fastapi_app.models.agent_performance_stat import AgentPerformanceStat
from fastapi_app.models.agent_insurance_segment import AgentInsuranceSegment
from fastapi_app.models.agent_product_expertise import AgentProductExpertise
from fastapi_app.models.agent_portfolio import AgentPortfolio
from fastapi_app.models.agent_achievement_photo import AgentAchievementPhoto
from fastapi_app.models.agent_career_timeline import AgentCareerTimeline
from fastapi_app.models.agent_lead_preference import AgentLeadPreference

class ProfileService:
    def __init__(self, agent_repo: AgentRepository):
        self.agent_repo = agent_repo

    @staticmethod
    def _sync_login_identity(db, previous_email: str, new_email: str, fullname: str) -> None:
        """Keep the credential tables aligned with agents.email.

        Agent login looks the account up by email in Laravel `users` first and
        Django `auth_user` second. Renaming only `agents.email` leaves both
        lookups pointing at the old address, which locks the agent out.
        """
        from sqlalchemy import text

        previous = (previous_email or "").strip()
        new = (new_email or "").strip()
        if not new:
            return

        changed = previous.lower() != new.lower()

        if changed:
            clash = db.execute(
                text("SELECT id FROM users WHERE LOWER(email) = LOWER(:email) LIMIT 1"),
                {"email": new},
            ).fetchone()
            owner = db.execute(
                text("SELECT id FROM users WHERE LOWER(email) = LOWER(:email) LIMIT 1"),
                {"email": previous},
            ).fetchone()
            if clash and (not owner or clash[0] != owner[0]):
                raise HTTPException(status_code=409, detail="The email has already been taken.")
            # auth_user may hold staff/insurance/distributor accounts that have
            # no `users` row; taking their address let an agent log in as them.
            auth_clash = db.execute(
                text(
                    "SELECT id FROM auth_user WHERE LOWER(email) = LOWER(:email) "
                    "AND LOWER(email) <> LOWER(:previous) LIMIT 1"
                ),
                {"email": new, "previous": previous},
            ).fetchone()
            if auth_clash:
                raise HTTPException(status_code=409, detail="The email has already been taken.")

            db.execute(
                text("UPDATE users SET email = :new, fullname = :fullname WHERE LOWER(email) = LOWER(:previous)"),
                {"new": new, "fullname": fullname or new, "previous": previous},
            )
            db.execute(
                text("UPDATE auth_user SET email = :new WHERE LOWER(email) = LOWER(:previous)"),
                {"new": new, "previous": previous},
            )
            # auth_user.username is unique and is seeded from the email on
            # import, so rename it too when it still mirrors the old address.
            username_taken = db.execute(
                text("SELECT id FROM auth_user WHERE username = :username LIMIT 1"),
                {"username": new},
            ).fetchone()
            if not username_taken:
                db.execute(
                    text("UPDATE auth_user SET username = :new WHERE username = :previous"),
                    {"new": new, "previous": previous},
                )
        elif fullname:
            db.execute(
                text("UPDATE users SET fullname = :fullname WHERE LOWER(email) = LOWER(:email)"),
                {"fullname": fullname, "email": new},
            )

    def get_profile(self, agent_id: int) -> AgentProfileResponse:
        agent = self.agent_repo.get_agent_with_full_profile(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        profile = agent.profile
        subs = agent.subscriptions
        active_sub = next((sub for sub in subs if sub.status == 'active'), None)
        perf_stats = agent.performance_stats
        lead_prefs = agent.lead_preferences

        def parse_json_list(val):
            if not val:
                return []
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return []

        def parse_json_dict(val):
            if not val:
                return {}
            if isinstance(val, dict):
                return val
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    pass
            return {}

        from apps.agents.models import resolve_stored_file_url

        def get_media_url(path: str) -> str:
            return resolve_stored_file_url(
                path,
                fallback_subdirs=(
                    'app/public/profile',
                    'agent/profiles',
                    'app/public/achievement',
                    'agent/achievements',
                ),
                missing='',
            )

        def safe_float(val):
            if not val:
                return 0.0
            try:
                clean_val = str(val).replace('%', '').replace('₹', '').replace(',', '').strip()
                return float(clean_val)
            except ValueError:
                return 0.0

        def safe_int(val):
            if not val:
                return 0
            try:
                clean_val = str(val).replace('%', '').replace('₹', '').replace(',', '').strip()
                return int(clean_val)
            except ValueError:
                try:
                    return int(float(clean_val))
                except ValueError:
                    return 0

        social_links = parse_json_dict(profile.social_links) if profile else {}

        response_dict = {
            "agent": {
                "id": agent.id,
                "status": agent.status or "incomplete",
                "badge": agent.badge or "",
                "fullname": agent.fullname or "",
                "email": agent.email or "",
                "mobile": agent.mobile or "",
                "experience_range": agent.experience_range or "",
                "client_base": agent.client_base or "",
                "user_types": parse_json_list(agent.user_types) if agent.user_types else [],
                "activeSubscription": {
                    "selected_plan": active_sub.selected_plan if active_sub else ""
                } if active_sub else None,
                "insuranceSegments": [
                    {"segment_type": s.segment_type} for s in agent.insurance_segments
                ] if agent.insurance_segments else [],
                "productExpertise": [
                    {
                        "segment_type": p.segment_type,
                        "product_name": p.product_name,
                        "expertise_level": p.expertise_level,
                        "is_custom": p.is_custom
                    } for p in agent.product_expertise
                ] if agent.product_expertise else [],
                "serviceableCities": [
                    c.city.name for c in agent.serviceable_cities if c.city
                ] if agent.serviceable_cities else [],
                "familyLicenses": [
                    {
                        "full_name": f.full_name,
                        "member_name": f.full_name,
                        "relationship": f.relationship,
                        "license_number": f.license_number,
                        "license_type": f.license_number
                    } for f in agent.family_licenses
                ] if agent.family_licenses else [],
                "performanceStats": {
                    "claims_processed": safe_int(perf_stats.claims_processed) if perf_stats else 0,
                    "claims_settled": safe_int(perf_stats.claims_settled) if perf_stats else 0,
                    "claims_amount": safe_float(perf_stats.claims_amount) if perf_stats else 0.0,
                    "success_rate": safe_float(perf_stats.success_rate) if perf_stats else 0.0,
                    "response_time": perf_stats.response_time if perf_stats and perf_stats.response_time else "2",
                },
                "portfolios": [
                    {
                        "segment_type": p.segment_type,
                        "primary_companies": parse_json_dict(p.primary_companies),
                        "secondary_companies": parse_json_dict(p.secondary_companies)
                    } for p in agent.portfolios
                ] if agent.portfolios else [],
                "careerTimelines": [
                    {
                        "month": t.month or "",
                        "year": str(t.year) if t.year is not None else "",
                        "type": t.event_type or "",
                        "event_text": t.event_text or "",
                        "title": t.event_text or ""
                    } for t in agent.career_timelines
                ] if agent.career_timelines else [],
                "achievementPhotos": [
                    {
                        "id": p.id,
                        "photo_url": get_media_url(p.photo_path)
                    } for p in agent.achievement_photos
                ] if agent.achievement_photos else [],
                "leadPreferences": {
                    "leads_new_business": lead_prefs.leads_new_business if (lead_prefs and lead_prefs.leads_new_business is not None) else True,
                    "leads_portfolio_analysis": lead_prefs.leads_portfolio_analysis if (lead_prefs and lead_prefs.leads_portfolio_analysis is not None) else True,
                    "portfolio_charging": lead_prefs.portfolio_charging if (lead_prefs and lead_prefs.portfolio_charging is not None) else "free",
                    "portfolio_fee": float(lead_prefs.portfolio_fee) if (lead_prefs and lead_prefs.portfolio_fee is not None) else 0.0,
                    "leads_claims_support": lead_prefs.leads_claims_support if (lead_prefs and lead_prefs.leads_claims_support is not None) else True,
                    "claims_charging": lead_prefs.claims_charging if (lead_prefs and lead_prefs.claims_charging is not None) else "free",
                    "claims_fee_amount": float(lead_prefs.claims_fee_amount) if (lead_prefs and lead_prefs.claims_fee_amount is not None) else 0.0,
                    "claims_percent": float(lead_prefs.claims_percent) if (lead_prefs and lead_prefs.claims_percent is not None) else 0.0
                } if lead_prefs else None
            },
            "profile": {
                "profile_photo_url": get_media_url(profile.profile_photo_path) if profile else None,
                "display_name": profile.display_name if profile else "",
                "whatsapp": profile.whatsapp if profile else "",
                "languages": profile.languages if profile else "",
                "address": profile.address if profile else "",
                "date_of_birth": profile.date_of_birth if profile else None,
                "pan_number": profile.pan_number if profile else "",
                "license_number": profile.license_number if profile else "",
                "license_valid_till": profile.license_valid_till if profile else None,
                "irdai_license_doc": get_media_url(profile.irdai_license_doc) if profile and profile.irdai_license_doc else None,
                "arn_number": profile.arn_number if profile else "",
                "euin_number": profile.euin_number if profile else "",
                "investment_valid_till": profile.investment_valid_till if profile else None,
                "amfi_license_doc": get_media_url(profile.amfi_license_doc) if profile and profile.amfi_license_doc else None,
                "investment_types": clean_investment_types(parse_json_list(profile.investment_types)) if profile else [],
                "agency_name": profile.agency_name if profile else "",
                "office_address": profile.office_address if profile else "",
                "service_pincodes": [
                    {
                        "pincode": sp.service_pincode,
                        "city_name": sp.city_name,
                        "selected_areas": parse_json_list(sp.selected_areas_json),
                        "postal_data": parse_json_list(sp.postal_data_json)
                    } for sp in agent.service_pincodes
                ] if agent.service_pincodes else [],
                "has_pos_license": bool(profile.has_pos_license) if profile and profile.has_pos_license else False,
                "career_highlights": profile.career_highlights if profile else "",
                "website": profile.website_url if profile else "",
                "social_links": {
                    "google_business": social_links.get("google_business", ""),
                    "linkedin_url": social_links.get("linkedin_url", social_links.get("linkedin", "")),
                    "instagram_url": social_links.get("instagram_url", social_links.get("instagram", "")),
                    "facebook_url": social_links.get("facebook_url", social_links.get("facebook", "")),
                    "youtube_url": social_links.get("youtube_url", social_links.get("youtube", ""))
                }
            },
            "features_access": LockUnlockService(self.agent_repo.db).get_feature_access_map(agent)
        }
        
        return AgentProfileResponse(**response_dict)

    def update_profile(self, agent_id: int, payload: AgentProfileUpdateRequest) -> AgentProfileResponse:
        db = self.agent_repo.db
        
        # 1. Validation phase
        agent = self.agent_repo.get_agent_with_full_profile(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
            
        # Email uniqueness
        existing_email = db.query(Agent).filter(Agent.email == payload.agent.email, Agent.id != agent_id).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="The email has already been taken.")
        if any(c in (payload.agent.fullname or "") + (payload.profile.display_name or "") for c in "<>"):
            raise HTTPException(status_code=422, detail="Name contains invalid characters.")
            
        # Pincode validation
        if not payload.profile.service_pincodes:
            raise HTTPException(status_code=422, detail="At least one service pincode is required.")
            
        seen_pincodes = set()
        for p in payload.profile.service_pincodes:
            if p.pincode in seen_pincodes:
                raise HTTPException(status_code=422, detail=f"Duplicate pincode detected: {p.pincode}")
            seen_pincodes.add(p.pincode)
            if not p.selected_areas:
                raise HTTPException(status_code=422, detail=f"Please select at least one area for pincode {p.pincode}.")
                
        # Photo limits
        active_sub = next((s for s in agent.subscriptions if s.status == 'active'), None)
        plan_text = str(active_sub.selected_plan if active_sub else '').lower()
        max_photos = 10 if 'professional' in plan_text else 5
        
        if len(payload.agent.achievementPhotos) > max_photos:
            raise HTTPException(status_code=422, detail=f"Achievement photo limit exceeded. Your current plan allows up to {max_photos} photos.")
            
        lock_service = LockUnlockService(db)
        lock_service.require_feature_unlocked(agent, "edit_profile")

        # Check sub-feature locks when modifying locked sections
        existing_bio = getattr(agent.profile, 'professional_bio', '') if agent.profile else ''
        new_bio = getattr(payload.profile, 'professional_bio', '') or ''
        if new_bio and new_bio.strip() != (existing_bio or '').strip():
            lock_service.require_feature_unlocked(agent, "edit_profile_professional_bio")

        new_socials = payload.profile.social_links.model_dump() if hasattr(payload.profile.social_links, 'model_dump') else (payload.profile.social_links.dict() if hasattr(payload.profile.social_links, 'dict') else {})
        has_new_socials = any(bool(v and str(v).strip()) for v in new_socials.values()) if isinstance(new_socials, dict) else False
        existing_socials = getattr(agent.profile, 'social_links', {}) if agent.profile else {}
        if has_new_socials and new_socials != existing_socials:
            lock_service.require_feature_unlocked(agent, "edit_profile_social_media")

        existing_claims = getattr(agent.profile, 'support_claims', False) if agent.profile else False
        new_claims = getattr(payload.profile, 'support_claims', False)
        if new_claims and not existing_claims:
            lock_service.require_feature_unlocked(agent, "edit_profile_claim_support")

        try:
            # Step 1: Basic Info
            previous_email = agent.email
            agent.fullname = payload.agent.fullname
            agent.email = payload.agent.email
            agent.mobile = payload.agent.mobile

            # Login resolves credentials by email against `users` / `auth_user`,
            # so an email change here must carry over or the agent is locked out.
            self._sync_login_identity(db, previous_email, payload.agent.email, payload.agent.fullname)
            # badge is an admin-assigned trust marker (web: admin edit only);
            # an agent must not be able to set it on themselves.
            agent.user_types = payload.agent.user_types
            
            if not agent.profile:
                agent.profile = AgentProfile(agent_id=agent.id)
                db.add(agent.profile)
                
            agent.profile.display_name = payload.profile.display_name
            agent.profile.whatsapp = payload.profile.whatsapp
            agent.profile.languages = payload.profile.languages
            agent.profile.address = payload.profile.address
            
            if payload.profile.profile_photo_url and _is_own_photo_url(payload.profile.profile_photo_url):
                # Only our own upload targets: the OG-image renderer fetches this
                # URL server-side, so an arbitrary URL was an SSRF vector.
                agent.profile.profile_photo_path = payload.profile.profile_photo_url

            # Step 2: Professional Details
            agent.profile.pan_number = payload.profile.pan_number
            # license_number drives the public "IRDAI verified" flag and is
            # set by admins only (web parity); keep the stored value.
            agent.profile.license_valid_till = payload.profile.license_valid_till
            agent.profile.arn_number = payload.profile.arn_number
            agent.profile.euin_number = payload.profile.euin_number
            agent.profile.investment_valid_till = payload.profile.investment_valid_till
            agent.profile.investment_types = clean_investment_types(payload.profile.investment_types)
            agent.profile.agency_name = payload.profile.agency_name
            agent.profile.office_address = payload.profile.office_address
            agent.profile.has_pos_license = payload.profile.has_pos_license
            
            agent.experience_range = payload.agent.experience_range
            agent.client_base = payload.agent.client_base
            
            # Clear existing pincodes
            db.query(AgentServicePincode).filter(AgentServicePincode.agent_id == agent_id).delete(synchronize_session=False)
            db.query(AgentServiceableCity).filter(AgentServiceableCity.agent_id == agent_id).delete(synchronize_session=False)
            
            unique_cities = set(payload.agent.serviceableCities)
            for p in payload.profile.service_pincodes:
                db.add(AgentServicePincode(
                    agent_id=agent_id,
                    service_pincode=p.pincode,
                    city_name=p.city_name,
                    selected_areas_json=p.selected_areas,
                    postal_data_json=p.postal_data
                ))
                if p.city_name:
                    unique_cities.add(p.city_name)
            
            if payload.profile.service_pincodes:
                agent.agent_pincode = payload.profile.service_pincodes[0].pincode
                    
            # Process cities
            for city_name in unique_cities:
                city = db.query(City).filter(City.name == city_name).first()
                if not city:
                    city_slug = city_name.lower().replace(' ', '-')
                    city = City(name=city_name, slug=city_slug)
                    db.add(city)
                    db.flush()
                db.add(AgentServiceableCity(agent_id=agent_id, city_id=city.id))
                
            # Family licenses
            db.query(AgentFamilyLicense).filter(AgentFamilyLicense.agent_id == agent_id).delete(synchronize_session=False)
            for f in payload.agent.familyLicenses:
                full_name = f.full_name or f.member_name or ""
                license_number = f.license_number or f.license_type or ""
                db.add(AgentFamilyLicense(
                    agent_id=agent_id,
                    full_name=full_name,
                    relationship=f.relationship,
                    license_number=license_number
                ))
                
            # Performance Stats
            perf = payload.agent.performanceStats
            cp = perf.claims_processed
            cs = perf.claims_settled
            success_rate = round((cs / cp) * 100, 2) if cp > 0 else 0.0
            
            stat = db.query(AgentPerformanceStat).filter(AgentPerformanceStat.agent_id == agent_id).first()
            if not stat:
                stat = AgentPerformanceStat(agent_id=agent_id)
                db.add(stat)
            
            stat.claims_processed = str(cp)
            stat.claims_settled = str(cs)
            stat.claims_amount = str(perf.claims_amount)
            resp_time_val = 2
            try:
                import re
                m = re.search(r'\d+', str(perf.response_time))
                if m:
                    resp_time_val = int(m.group())
            except Exception:
                pass
            stat.response_time = resp_time_val
            stat.success_rate = str(success_rate)
            
            # Step 3: Insurance Segments & Expertise
            db.query(AgentInsuranceSegment).filter(AgentInsuranceSegment.agent_id == agent_id).delete(synchronize_session=False)
            for s in payload.agent.insuranceSegments:
                db.add(AgentInsuranceSegment(agent_id=agent_id, segment_type=s.segment_type))
                
            db.query(AgentProductExpertise).filter(AgentProductExpertise.agent_id == agent_id).delete(synchronize_session=False)
            for e in payload.agent.productExpertise:
                segment = e.segment_type
                if not segment:
                    prod_lower = e.product_name.lower() if e.product_name else ""
                    if "term" in prod_lower or "life" in prod_lower:
                        segment = "life"
                    elif "health" in prod_lower or "medical" in prod_lower:
                        segment = "health"
                    elif "car" in prod_lower or "motor" in prod_lower or "bike" in prod_lower:
                        segment = "motor"
                    elif "sme" in prod_lower or "commercial" in prod_lower or "business" in prod_lower:
                        segment = "sme"
                    else:
                        segment = "life"
                db.add(AgentProductExpertise(
                    agent_id=agent_id,
                    segment_type=segment,
                    product_name=e.product_name,
                    expertise_level=e.expertise_level,
                    is_custom=e.is_custom
                ))
                
            # Step 4: Portfolios (JSON serialization for Text columns primary_companies/secondary_companies)
            db.query(AgentPortfolio).filter(AgentPortfolio.agent_id == agent_id).delete(synchronize_session=False)
            for port in payload.agent.portfolios:
                db.add(AgentPortfolio(
                    agent_id=agent_id,
                    segment_type=port.segment_type,
                    primary_companies=json.dumps(port.primary_companies),
                    secondary_companies=json.dumps(port.secondary_companies)
                ))
                
            # Step 5: Additional Info (Save direct dict for JSON column)
            agent.profile.website_url = payload.profile.website
            agent.profile.career_highlights = payload.profile.career_highlights
            agent.profile.social_links = payload.profile.social_links.dict()
            agent.profile.service_pincodes = [sp.pincode for sp in payload.profile.service_pincodes]
            
            existing_photos = db.query(AgentAchievementPhoto).filter(AgentAchievementPhoto.agent_id == agent_id).all()
            existing_photo_ids = {p.id: p for p in existing_photos}
            existing_photo_paths = {p.photo_path: p for p in existing_photos}
            
            payload_photos = payload.agent.achievementPhotos
            payload_photo_ids = {photo.id for photo in payload_photos if photo.id > 0}
            payload_photo_urls = {photo.photo_url for photo in payload_photos}
            
            # Delete photos that are not in the payload
            for p_obj in existing_photos:
                if p_obj.id not in payload_photo_ids and p_obj.photo_path not in payload_photo_urls:
                    try:
                        if "res.cloudinary.com" in p_obj.photo_path:
                            from fastapi_app.services.cloudinary_service import CloudinaryService
                            CloudinaryService.delete_image(p_obj.photo_path)
                        elif "/static/uploads/" in p_obj.photo_path or "/media/uploads/" in p_obj.photo_path:
                            from fastapi_app.services.local_storage_service import LocalStorageService
                            LocalStorageService.delete_file(p_obj.photo_path)
                    except Exception:
                        pass
                    db.delete(p_obj)
                    
            # Insert new photos that are not already in DB
            for photo in payload_photos:
                if photo.id > 0 and photo.id in existing_photo_ids:
                    continue
                if photo.photo_url in existing_photo_paths:
                    continue
                db.add(AgentAchievementPhoto(
                    agent_id=agent_id,
                    photo_path=photo.photo_url
                ))
                
            db.query(AgentCareerTimeline).filter(AgentCareerTimeline.agent_id == agent_id).delete(synchronize_session=False)
            for t in payload.agent.careerTimelines:
                event_text = t.event_text or t.title or ""
                db.add(AgentCareerTimeline(
                    agent_id=agent_id,
                    month=t.month,
                    year=int(t.year) if str(t.year).isdigit() else 2024,
                    event_type=t.type,
                    event_text=event_text
                ))
                
            # Step 6: Lead Preferences
            prefs = payload.agent.leadPreferences
            if prefs:
                lead = db.query(AgentLeadPreference).filter(AgentLeadPreference.agent_id == agent_id).first()
                if not lead:
                    lead = AgentLeadPreference(agent_id=agent_id)
                    db.add(lead)
                
                # Enforce experience-gating rules
                # 1. Parse experience_range
                exp_years = 0
                exp_str = payload.agent.experience_range
                if exp_str:
                    import re
                    match = re.search(r'\d+', exp_str)
                    if match:
                        try:
                            exp_years = int(match.group())
                        except ValueError:
                            pass
                
                # Apply rules
                leads_new_business = prefs.leads_new_business
                leads_portfolio_analysis = prefs.leads_portfolio_analysis
                portfolio_charging = prefs.portfolio_charging
                portfolio_fee = prefs.portfolio_fee
                leads_claims_support = prefs.leads_claims_support
                claims_charging = prefs.claims_charging
                claims_fee_amount = prefs.claims_fee_amount
                claims_percent = prefs.claims_percent
                
                if exp_years < 5:
                    leads_portfolio_analysis = False
                    portfolio_charging = "free"
                    portfolio_fee = 0.0
                    leads_claims_support = False
                    claims_charging = "free"
                    claims_fee_amount = 0.0
                    claims_percent = 0.0
                elif exp_years < 10:
                    leads_claims_support = False
                    claims_charging = "free"
                    claims_fee_amount = 0.0
                    claims_percent = 0.0
                
                lead.leads_new_business = leads_new_business
                lead.leads_portfolio_analysis = leads_portfolio_analysis
                lead.portfolio_charging = portfolio_charging
                lead.portfolio_fee = portfolio_fee
                lead.leads_claims_support = leads_claims_support
                lead.claims_charging = claims_charging
                lead.claims_fee_amount = claims_fee_amount
                lead.claims_percent = claims_percent
                
            # Step 7: Submission status update.
            # Mirrors apps/agents/views/dashboard.py apply_profile_update: a full
            # profile submission goes back into the admin approval queue. Agents
            # in this state can still sign in (see AuthService.login).
            if agent.status not in ('suspended', 'blacklisted', 'rejected'):
                agent.status = 'pending_approval'

            db.commit()

        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.exception("Profile update failed for agent_id=%s", agent_id)
            raise HTTPException(status_code=500, detail="An error occurred while updating the profile.")

        return self.get_profile(agent_id)

    def _get_agent_or_404(self, agent_id: int):
        agent = self.agent_repo.get_agent_with_full_profile(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    def _ensure_profile(self, db, agent):
        if not agent.profile:
            agent.profile = AgentProfile(agent_id=agent.id)
            db.add(agent.profile)
            db.flush()
        return agent.profile

    def _mark_pending_approval(self, agent):
        if agent.status not in ('suspended', 'blacklisted', 'rejected'):
            agent.status = 'pending_approval'

    @staticmethod
    def _socials_as_dict(social_links) -> dict:
        if not social_links:
            return {}
        if hasattr(social_links, 'model_dump'):
            return social_links.model_dump()
        if hasattr(social_links, 'dict'):
            return social_links.dict()
        return social_links if isinstance(social_links, dict) else {}

    def _validate_service_pincodes(self, service_pincodes):
        if not service_pincodes:
            raise HTTPException(status_code=422, detail="At least one service pincode is required.")
        seen_pincodes = set()
        for p in service_pincodes:
            if p.pincode in seen_pincodes:
                raise HTTPException(status_code=422, detail=f"Duplicate pincode detected: {p.pincode}")
            seen_pincodes.add(p.pincode)
            if not p.selected_areas:
                raise HTTPException(status_code=422, detail=f"Please select at least one area for pincode {p.pincode}.")

    def _save_service_pincodes_and_cities(self, db, agent, agent_id, service_pincodes, serviceable_cities):
        db.query(AgentServicePincode).filter(AgentServicePincode.agent_id == agent_id).delete(synchronize_session=False)
        db.query(AgentServiceableCity).filter(AgentServiceableCity.agent_id == agent_id).delete(synchronize_session=False)

        unique_cities = set(serviceable_cities or [])
        for p in service_pincodes:
            db.add(AgentServicePincode(
                agent_id=agent_id,
                service_pincode=p.pincode,
                city_name=p.city_name,
                selected_areas_json=p.selected_areas,
                postal_data_json=p.postal_data
            ))
            if p.city_name:
                unique_cities.add(p.city_name)

        if service_pincodes:
            agent.agent_pincode = service_pincodes[0].pincode
            agent.profile.service_pincodes = [sp.pincode for sp in service_pincodes]

        for city_name in unique_cities:
            city = db.query(City).filter(City.name == city_name).first()
            if not city:
                city_slug = city_name.lower().replace(' ', '-')
                city = City(name=city_name, slug=city_slug)
                db.add(city)
                db.flush()
            db.add(AgentServiceableCity(agent_id=agent_id, city_id=city.id))

    def _apply_lead_preferences(self, db, agent_id, prefs, experience_range):
        lead = db.query(AgentLeadPreference).filter(AgentLeadPreference.agent_id == agent_id).first()
        if not lead:
            lead = AgentLeadPreference(agent_id=agent_id)
            db.add(lead)

        exp_years = 0
        if experience_range:
            import re
            match = re.search(r'\d+', experience_range)
            if match:
                try:
                    exp_years = int(match.group())
                except ValueError:
                    pass

        leads_new_business = prefs.leads_new_business
        leads_portfolio_analysis = prefs.leads_portfolio_analysis
        portfolio_charging = prefs.portfolio_charging
        portfolio_fee = prefs.portfolio_fee
        leads_claims_support = prefs.leads_claims_support
        claims_charging = prefs.claims_charging
        claims_fee_amount = prefs.claims_fee_amount
        claims_percent = prefs.claims_percent

        if exp_years < 5:
            leads_portfolio_analysis = False
            portfolio_charging = "free"
            portfolio_fee = 0.0
            leads_claims_support = False
            claims_charging = "free"
            claims_fee_amount = 0.0
            claims_percent = 0.0
        elif exp_years < 10:
            leads_claims_support = False
            claims_charging = "free"
            claims_fee_amount = 0.0
            claims_percent = 0.0

        lead.leads_new_business = leads_new_business
        lead.leads_portfolio_analysis = leads_portfolio_analysis
        lead.portfolio_charging = portfolio_charging
        lead.portfolio_fee = portfolio_fee
        lead.leads_claims_support = leads_claims_support
        lead.claims_charging = claims_charging
        lead.claims_fee_amount = claims_fee_amount
        lead.claims_percent = claims_percent

    def _save_performance_stats(self, db, agent_id, perf):
        cp = perf.claims_processed
        cs = perf.claims_settled
        success_rate = round((cs / cp) * 100, 2) if cp > 0 else 0.0

        stat = db.query(AgentPerformanceStat).filter(AgentPerformanceStat.agent_id == agent_id).first()
        if not stat:
            stat = AgentPerformanceStat(agent_id=agent_id)
            db.add(stat)

        stat.claims_processed = str(cp)
        stat.claims_settled = str(cs)
        stat.claims_amount = str(perf.claims_amount)
        resp_time_val = 2
        try:
            import re
            m = re.search(r'\d+', str(perf.response_time))
            if m:
                resp_time_val = int(m.group())
        except Exception:
            pass
        stat.response_time = resp_time_val
        stat.success_rate = str(success_rate)

    def update_basic_profile(self, agent_id: int, payload: BasicProfileUpdateRequest) -> AgentProfileResponse:
        db = self.agent_repo.db
        agent = self._get_agent_or_404(agent_id)

        fullname = (payload.agent.fullname or "").strip()
        email = (payload.agent.email or "").strip()
        mobile = (payload.agent.mobile or "").strip()
        languages = (payload.profile.languages or "").strip()
        address = (payload.profile.address or "").strip()

        if not fullname:
            raise HTTPException(status_code=422, detail="Full name is required.")
        if any(c in fullname + (payload.profile.display_name or "") for c in "<>"):
            # Names render on public pages / JS-built HTML (web parity).
            raise HTTPException(status_code=422, detail="Name contains invalid characters.")
        if not email:
            raise HTTPException(status_code=422, detail="Email is required.")
        if not mobile:
            raise HTTPException(status_code=422, detail="Mobile number is required.")
        if not languages:
            raise HTTPException(status_code=422, detail="Languages are required.")
        if not address:
            raise HTTPException(status_code=422, detail="Residence address is required.")

        existing_email = db.query(Agent).filter(Agent.email == email, Agent.id != agent_id).first()
        if existing_email:
            raise HTTPException(status_code=409, detail="The email has already been taken.")

        lock_service = LockUnlockService(db)
        lock_service.require_feature_unlocked(agent, "edit_profile_basic")

        try:
            previous_email = agent.email
            agent.fullname = fullname
            agent.email = email
            agent.mobile = mobile
            self._sync_login_identity(db, previous_email, email, fullname)

            profile = self._ensure_profile(db, agent)
            profile.display_name = payload.profile.display_name
            profile.whatsapp = payload.profile.whatsapp
            profile.languages = languages
            profile.address = address
            profile.date_of_birth = payload.profile.date_of_birth or None

            self._mark_pending_approval(agent)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Basic profile update failed for agent_id=%s", agent_id)
            raise HTTPException(status_code=500, detail="An error occurred while updating the profile.")

        return self.get_profile(agent_id)

    def update_professional_profile(self, agent_id: int, payload: ProfessionalProfileUpdateRequest) -> AgentProfileResponse:
        db = self.agent_repo.db
        agent = self._get_agent_or_404(agent_id)

        self._validate_service_pincodes(payload.profile.service_pincodes)

        lock_service = LockUnlockService(db)
        lock_service.require_feature_unlocked(agent, "edit_profile_professional")
        if payload.agent.performanceStats is not None:
            lock_service.require_feature_unlocked(agent, "edit_profile_claim_support")
        if payload.agent.leadPreferences is not None:
            lock_service.require_feature_unlocked(agent, "lead_preferences")

        try:
            profile = self._ensure_profile(db, agent)
            profile.pan_number = payload.profile.pan_number
            # license_number (public "IRDAI verified" flag) is admin-set only.
            profile.license_valid_till = payload.profile.license_valid_till
            profile.arn_number = payload.profile.arn_number
            profile.euin_number = payload.profile.euin_number
            profile.investment_valid_till = payload.profile.investment_valid_till
            profile.agency_name = payload.profile.agency_name
            profile.office_address = payload.profile.office_address
            profile.has_pos_license = payload.profile.has_pos_license

            agent.experience_range = payload.agent.experience_range
            agent.client_base = payload.agent.client_base

            self._save_service_pincodes_and_cities(
                db,
                agent,
                agent_id,
                payload.profile.service_pincodes,
                payload.agent.serviceableCities,
            )

            db.query(AgentFamilyLicense).filter(AgentFamilyLicense.agent_id == agent_id).delete(synchronize_session=False)
            for f in payload.agent.familyLicenses:
                full_name = f.full_name or f.member_name or ""
                license_number = f.license_number or f.license_type or ""
                db.add(AgentFamilyLicense(
                    agent_id=agent_id,
                    full_name=full_name,
                    relationship=f.relationship,
                    license_number=license_number
                ))

            if payload.agent.performanceStats is not None:
                self._save_performance_stats(db, agent_id, payload.agent.performanceStats)

            if payload.agent.leadPreferences is not None:
                self._apply_lead_preferences(
                    db,
                    agent_id,
                    payload.agent.leadPreferences,
                    payload.agent.experience_range or agent.experience_range,
                )

            self._mark_pending_approval(agent)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Professional profile update failed for agent_id=%s", agent_id)
            raise HTTPException(status_code=500, detail="An error occurred while updating the profile.")

        return self.get_profile(agent_id)

    def update_portfolio_profile(self, agent_id: int, payload: PortfolioProfileUpdateRequest) -> AgentProfileResponse:
        db = self.agent_repo.db
        agent = self._get_agent_or_404(agent_id)

        lock_service = LockUnlockService(db)
        lock_service.require_feature_unlocked(agent, "edit_profile_portfolio")
        if payload.agent.portfolios:
            lock_service.require_feature_unlocked(agent, "manage_portfolio")
            has_companies = any(
                bool(port.primary_companies) or bool(port.secondary_companies)
                for port in payload.agent.portfolios
            )
            if has_companies:
                lock_service.require_feature_unlocked(agent, "edit_profile_companies")

        try:
            profile = self._ensure_profile(db, agent)
            if payload.profile is not None:
                profile.investment_types = clean_investment_types(payload.profile.investment_types)

            db.query(AgentInsuranceSegment).filter(AgentInsuranceSegment.agent_id == agent_id).delete(synchronize_session=False)
            for s in payload.agent.insuranceSegments:
                db.add(AgentInsuranceSegment(agent_id=agent_id, segment_type=s.segment_type))

            db.query(AgentProductExpertise).filter(AgentProductExpertise.agent_id == agent_id).delete(synchronize_session=False)
            for e in payload.agent.productExpertise:
                segment = e.segment_type
                if not segment:
                    prod_lower = e.product_name.lower() if e.product_name else ""
                    if "term" in prod_lower or "life" in prod_lower:
                        segment = "life"
                    elif "health" in prod_lower or "medical" in prod_lower:
                        segment = "health"
                    elif "car" in prod_lower or "motor" in prod_lower or "bike" in prod_lower:
                        segment = "motor"
                    elif "sme" in prod_lower or "commercial" in prod_lower or "business" in prod_lower:
                        segment = "sme"
                    else:
                        segment = "life"
                db.add(AgentProductExpertise(
                    agent_id=agent_id,
                    segment_type=segment,
                    product_name=e.product_name,
                    expertise_level=e.expertise_level,
                    is_custom=e.is_custom
                ))

            db.query(AgentPortfolio).filter(AgentPortfolio.agent_id == agent_id).delete(synchronize_session=False)
            for port in payload.agent.portfolios:
                db.add(AgentPortfolio(
                    agent_id=agent_id,
                    segment_type=port.segment_type,
                    primary_companies=json.dumps(port.primary_companies),
                    secondary_companies=json.dumps(port.secondary_companies)
                ))

            self._mark_pending_approval(agent)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Portfolio profile update failed for agent_id=%s", agent_id)
            raise HTTPException(status_code=500, detail="An error occurred while updating the profile.")

        return self.get_profile(agent_id)

    def update_additional_profile(self, agent_id: int, payload: AdditionalProfileUpdateRequest) -> AgentProfileResponse:
        db = self.agent_repo.db
        agent = self._get_agent_or_404(agent_id)

        lock_service = LockUnlockService(db)
        lock_service.require_feature_unlocked(agent, "edit_profile_additional")

        existing_bio = (agent.profile.career_highlights or "") if agent.profile else ""
        new_bio = payload.profile.career_highlights or ""
        if new_bio.strip() != existing_bio.strip():
            lock_service.require_feature_unlocked(agent, "edit_profile_professional_bio")

        new_socials = self._socials_as_dict(payload.profile.social_links)
        existing_socials = getattr(agent.profile, 'social_links', {}) if agent.profile else {}
        if not isinstance(existing_socials, dict):
            existing_socials = {}
        existing_website = (agent.profile.website_url or "") if agent.profile else ""
        new_website = payload.profile.website or ""
        if new_website.strip() != existing_website.strip() or new_socials != existing_socials:
            lock_service.require_feature_unlocked(agent, "edit_profile_social_media")

        try:
            profile = self._ensure_profile(db, agent)
            profile.website_url = payload.profile.website
            profile.career_highlights = payload.profile.career_highlights
            profile.social_links = new_socials

            self._mark_pending_approval(agent)
            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.exception("Additional profile update failed for agent_id=%s", agent_id)
            raise HTTPException(status_code=500, detail="An error occurred while updating the profile.")

        return self.get_profile(agent_id)

    def update_profile_photo(self, agent_id: int, secure_url: str) -> dict:
        db = self.agent_repo.db
        try:
            profile = db.query(AgentProfile).filter(AgentProfile.agent_id == agent_id).first()
            if not profile:
                raise HTTPException(status_code=404, detail="Agent profile not found.")
            profile.profile_photo_path = secure_url
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if agent:
                self._mark_pending_approval(agent)
            db.commit()
            response_url = f"/media/{secure_url}" if not secure_url.startswith("http") else secure_url
            return {"success": True, "profile_photo_url": response_url}
        except Exception as e:
            db.rollback()
            raise e

    def save_achievement_photos(self, agent_id: int, processed_files: list, existing_photos_map: dict) -> list:
        db = self.agent_repo.db
        uploaded_results = []
        try:
            for pf in processed_files:
                if pf["hash"] in existing_photos_map:
                    existing = existing_photos_map[pf["hash"]]
                    response_url = f"/media/{existing.photo_path}" if not existing.photo_path.startswith("http") else existing.photo_path
                    uploaded_results.append({
                        "id": existing.id,
                        "photo_url": response_url
                    })
                    continue

                new_photo = AgentAchievementPhoto(
                    agent_id=agent_id,
                    photo_path=pf["photo_url"],
                    file_hash=pf["hash"]
                )
                db.add(new_photo)
                db.flush()
                
                response_url = f"/media/{new_photo.photo_path}" if not new_photo.photo_path.startswith("http") else new_photo.photo_path
                uploaded_results.append({
                    "id": new_photo.id,
                    "photo_url": response_url
                })
            db.commit()
            return uploaded_results
        except Exception as e:
            db.rollback()
            raise e

    def delete_achievement_photo(self, agent_id: int, photo_id: int) -> bool:
        db = self.agent_repo.db
        photo = db.query(AgentAchievementPhoto).filter(
            AgentAchievementPhoto.id == photo_id,
            AgentAchievementPhoto.agent_id == agent_id
        ).first()
        if not photo:
            raise HTTPException(status_code=404, detail="Achievement photo not found.")
        db.delete(photo)
        db.commit()
        return True

    def get_career_timelines(self, agent_id: int) -> list:
        db = self.agent_repo.db
        timelines = db.query(AgentCareerTimeline).filter(
            AgentCareerTimeline.agent_id == agent_id
        ).order_by(AgentCareerTimeline.year.desc()).all()
        return [
            {
                "id": t.id,
                "year": str(t.year),
                "month": t.month or "",
                "type": t.event_type or "Career Event",
                "event_text": t.event_text or "",
                "title": t.event_text or ""
            } for t in timelines
        ]

    def add_career_timeline(self, agent: Agent, data: dict) -> dict:
        db = self.agent_repo.db
        from fastapi_app.services.lock_unlock_service import LockUnlockService
        LockUnlockService(db).require_feature_unlocked(agent, "edit_profile_career_timeline")

        timeline = AgentCareerTimeline(
            agent_id=agent.id,
            year=str(data.get("year", "")),
            month=data.get("month", ""),
            event_type=data.get("type", "Career Event"),
            event_text=data.get("title") or data.get("event_text", ""),
            suggestion_key=(data.get("suggestion_key") or data.get("key") or None),
        )
        db.add(timeline)
        db.commit()
        db.refresh(timeline)
        return {
            "id": timeline.id,
            "year": str(timeline.year),
            "month": timeline.month or "",
            "type": timeline.event_type,
            "event_text": timeline.event_text,
            "title": timeline.event_text
        }

    def update_career_timeline(self, agent: Agent, timeline_id: int, data: dict) -> dict:
        db = self.agent_repo.db
        from fastapi_app.services.lock_unlock_service import LockUnlockService
        LockUnlockService(db).require_feature_unlocked(agent, "edit_profile_career_timeline")

        timeline = db.query(AgentCareerTimeline).filter(
            AgentCareerTimeline.id == timeline_id,
            AgentCareerTimeline.agent_id == agent.id
        ).first()
        if not timeline:
            raise HTTPException(status_code=404, detail="Career timeline event not found.")

        if "year" in data:
            timeline.year = str(data["year"])
        if "month" in data:
            timeline.month = data["month"]
        if "type" in data:
            timeline.event_type = data["type"]
        if "title" in data or "event_text" in data:
            timeline.event_text = data.get("title") or data.get("event_text", "")

        db.commit()
        db.refresh(timeline)
        return {
            "id": timeline.id,
            "year": str(timeline.year),
            "month": timeline.month or "",
            "type": timeline.event_type,
            "event_text": timeline.event_text,
            "title": timeline.event_text
        }

    def delete_career_timeline(self, agent: Agent, timeline_id: int) -> bool:
        db = self.agent_repo.db
        timeline = db.query(AgentCareerTimeline).filter(
            AgentCareerTimeline.id == timeline_id,
            AgentCareerTimeline.agent_id == agent.id
        ).first()
        if not timeline:
            raise HTTPException(status_code=404, detail="Career timeline event not found.")
        db.delete(timeline)
        db.commit()
        return True

