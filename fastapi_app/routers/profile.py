from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status, Request
from typing import List, Optional, Union, Any, Annotated
from pydantic import BeforeValidator, WithJsonSchema
from sqlalchemy.orm import Session

def validate_upload_or_str(v: Any) -> Any:
    return v

FlexibleUploadFile = Annotated[
    Union[UploadFile, str],
    BeforeValidator(validate_upload_or_str),
    WithJsonSchema({"type": "string", "format": "binary"})
]
from fastapi_app.config import settings
from fastapi_app.database import get_db
from fastapi_app.dependencies.auth import get_current_agent
from fastapi_app.models.agent import Agent
from fastapi_app.schemas.profile import (
    AgentProfileResponse,
    BasicProfileUpdateRequest,
    ProfessionalProfileUpdateRequest,
    PortfolioProfileUpdateRequest,
    AdditionalProfileUpdateRequest,
)
from fastapi_app.repositories.agent_repository import AgentRepository
from fastapi_app.services.profile_service import ProfileService
from fastapi_app.services.cloudinary_service import CloudinaryService
from fastapi_app.utils.image_validation import validate_image_file, validate_document_file
from fastapi_app.models.agent_profile import AgentProfile
from fastapi_app.models.agent_achievement_photo import AgentAchievementPhoto
import logging
import hashlib

from starlette.concurrency import run_in_threadpool
from fastapi_app.services.local_storage_service import LocalStorageService
from fastapi_app.services.lock_unlock_service import LockUnlockService
from fastapi_app.utils.companies import INSURANCE_COMPANIES

logger = logging.getLogger(__name__)

def _upload_image_with_fallback(file_bytes: bytes, folder: str, filename: str, fallback_relative_path: str) -> str:
    """Synchronous worker that uploads to Cloudinary with local fallback, meant for threadpool execution."""
    try:
        secure_url = CloudinaryService.upload_image(
            file_bytes,
            folder=folder,
            filename=filename
        )
        logger.info(f"Cloudinary success: URL={secure_url}")
        return secure_url
    except Exception as e:
        logger.warning(f"Cloudinary upload failed ({type(e).__name__}): {str(e)}. Fallback to local storage initiated.")
        try:
            secure_url = LocalStorageService.save_django_path_file(file_bytes, fallback_relative_path)
            logger.info(f"Local storage success: URL={secure_url}")
            return secure_url
        except Exception as local_err:
            logger.error(f"Local storage failure: {str(local_err)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Both Cloudinary and local fallback storage failed."
            )

router = APIRouter(prefix="/v1/agents", tags=["Profile"])

@router.get("/profile", response_model=AgentProfileResponse)
def get_agent_profile(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Get the complete agent profile for the authenticated agent.
    This endpoint serves as the single source of truth for the Edit Profile UI.
    """
    agent_repo = AgentRepository(db)
    profile_service = ProfileService(agent_repo)
    
    return profile_service.get_profile(current_agent.id)


@router.put("/profile/basic", response_model=AgentProfileResponse)
def update_agent_profile_basic(
    payload: BasicProfileUpdateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Update Step 1 basic details only. Does not touch professional, portfolio, or additional data.
    Profile photo stays on POST /profile/image.
    """
    agent_repo = AgentRepository(db)
    profile_service = ProfileService(agent_repo)
    return profile_service.update_basic_profile(current_agent.id, payload)


@router.put("/profile/professional", response_model=AgentProfileResponse)
def update_agent_profile_professional(
    payload: ProfessionalProfileUpdateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Update Step 2 professional details only. License documents stay on the license upload APIs.
    """
    agent_repo = AgentRepository(db)
    profile_service = ProfileService(agent_repo)
    return profile_service.update_professional_profile(current_agent.id, payload)


@router.put("/profile/portfolio", response_model=AgentProfileResponse)
def update_agent_profile_portfolio(
    payload: PortfolioProfileUpdateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Update Step 3 product portfolio only: segments, investment types, expertise, and companies.
    """
    agent_repo = AgentRepository(db)
    profile_service = ProfileService(agent_repo)
    return profile_service.update_portfolio_profile(current_agent.id, payload)


@router.put("/profile/additional", response_model=AgentProfileResponse)
def update_agent_profile_additional(
    payload: AdditionalProfileUpdateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Update Step 4 additional info only: website, social links, and saved professional bio.
    Bio generation stays on GET /profile/generate-bio.
    Achievement photos and career timeline stay on their existing APIs.
    """
    agent_repo = AgentRepository(db)
    profile_service = ProfileService(agent_repo)
    return profile_service.update_additional_profile(current_agent.id, payload)


@router.post("/profile/image")
async def upload_profile_image(
    request: Request,
    file: UploadFile = File(...),
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Upload or update a single profile image for the authenticated agent.
    Uploads to Cloudinary, with local fallback if Cloudinary fails.
    """
    # 1. Read file and compute hash/size
    sha256 = hashlib.sha256()
    file_content = bytearray()
    while True:
        chunk = await file.read(8192)
        if not chunk:
            break
        sha256.update(chunk)
        file_content.extend(chunk)
    file_bytes = bytes(file_content)
    
    # 2. Validate and sanitize
    file_bytes = validate_image_file(file_bytes, file.filename or "image.jpg", file.content_type or "image/jpeg")
    
    # 3. Get profile
    profile = db.query(AgentProfile).filter(AgentProfile.agent_id == current_agent.id).first()
    if not profile:
        profile = AgentProfile(agent_id=current_agent.id)
        db.add(profile)
        db.flush()
        
    old_path = profile.profile_photo_path
    
    # 4. Upload with Fallback (run off the asyncio event loop)
    import time, os
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"
    relative_path = f"app/public/profile/agent_{current_agent.id}_{int(time.time())}{ext}"
    secure_url = await run_in_threadpool(
        _upload_image_with_fallback,
        file_bytes,
        f"agent_profiles/{current_agent.id}",
        "profile",
        relative_path
    )
        
    # 5. Delete old image
    if old_path:
        if "res.cloudinary.com" in old_path:
            try:
                CloudinaryService.delete_image(old_path)
            except Exception as e:
                logger.error(f"Failed to delete old image from Cloudinary: {str(e)}")
        elif "/static/uploads/" in old_path or "/media/uploads/" in old_path:
            try:
                LocalStorageService.delete_file(old_path)
            except Exception as e:
                logger.error(f"Failed to delete old local file: {str(e)}")
            
    # 6. Update DB via service layer
    profile_service = ProfileService(AgentRepository(db))
    return profile_service.update_profile_photo(current_agent.id, secure_url)

@router.post("/profile/achievement")
async def upload_achievement_image(
    request: Request,
    file: Optional[FlexibleUploadFile] = File(None),
    files: Optional[List[FlexibleUploadFile]] = File(None),
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Upload one or more achievement images for the authenticated agent.
    Guarded by upload_achievements feature lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "upload_achievements")
    # 1. Combine inputs and filter out empty placeholders
    raw_uploaded_files = []
    if file:
        raw_uploaded_files.append(file)
    if files:
        raw_uploaded_files.extend(files)

    uploaded_files = []
    for f in raw_uploaded_files:
        if isinstance(f, str):
            if f.strip() != "":
                uploaded_files.append(f)
        else:
            if f.filename and f.filename.strip() != "":
                uploaded_files.append(f)

    if not uploaded_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded."
        )

    if len(uploaded_files) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot upload more than 10 files in a single request."
        )

    # 2. Process all uploaded files (read, validate/sanitize, compute hash)
    processed_files = []
    batch_hashes = set()
    
    for f in uploaded_files:
        if isinstance(f, str):
            import base64
            import re
            filename = "achievement.jpg"
            content_type = "image/jpeg"
            
            if f.startswith("data:image"):
                match = re.match(r'data:(?P<mime>image/[a-zA-Z0-9]+);base64,(?P<data>.*)', f)
                if match:
                    content_type = match.group('mime')
                    b64_data = match.group('data')
                    ext = content_type.split('/')[-1]
                    filename = f"achievement.{ext}"
                    try:
                        raw_bytes = base64.b64decode(b64_data)
                    except Exception:
                        raise HTTPException(status_code=400, detail="Invalid base64 image data.")
                else:
                    raise HTTPException(status_code=400, detail="Invalid base64 data URI format.")
            else:
                try:
                    # Attempt base64 decoding if no prefix
                    raw_bytes = base64.b64decode(f)
                except Exception:
                    try:
                        raw_bytes = f.encode('latin-1')
                    except Exception:
                        raw_bytes = f.encode('utf-8')
        else:
            filename = f.filename or "achievement.jpg"
            content_type = f.content_type or "image/jpeg"
            sha256 = hashlib.sha256()
            file_content = bytearray()
            while True:
                chunk = await f.read(8192)
                if not chunk:
                    break
                sha256.update(chunk)
                file_content.extend(chunk)
            raw_bytes = bytes(file_content)
        
        # Validate, get sanitized bytes, and compute secure hash
        sanitized_bytes = validate_image_file(raw_bytes, filename, content_type)
        sanitized_hash = hashlib.sha256(sanitized_bytes).hexdigest()
        
        # Prevent duplicates within the same batch upload
        if sanitized_hash in batch_hashes:
            continue
        batch_hashes.add(sanitized_hash)
        
        processed_files.append({
            "filename": filename,
            "bytes": sanitized_bytes,
            "hash": sanitized_hash
        })

    # 3. Check photo limits based on subscription plan
    active_sub = next((s for s in current_agent.subscriptions if s.status == 'active'), None)
    plan_text = str(active_sub.selected_plan if active_sub else '').lower()
    max_photos = 10 if 'professional' in plan_text else 5
    
    current_count = db.query(AgentAchievementPhoto).filter(
        AgentAchievementPhoto.agent_id == current_agent.id
    ).count()

    # Identify which files are new (not already in the database for this agent)
    new_processed_files = []
    existing_photos_map = {}
    
    for pf in processed_files:
        existing = db.query(AgentAchievementPhoto).filter(
            AgentAchievementPhoto.agent_id == current_agent.id,
            AgentAchievementPhoto.file_hash == pf["hash"]
        ).first()
        
        if existing:
            existing_photos_map[pf["hash"]] = existing
        else:
            new_processed_files.append(pf)

    # Enforce plan limits
    if current_count + len(new_processed_files) > max_photos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Achievement photo limit exceeded. Your current plan allows up to {max_photos} photos."
        )

    # 4. Upload and Save new files
    uploaded_results = []
    
    for pf in processed_files:
        if pf["hash"] in existing_photos_map:
            # Re-use existing photo record
            existing = existing_photos_map[pf["hash"]]
            uploaded_results.append({
                "id": existing.id,
                "photo_url": existing.photo_path
            })
            continue

        # Upload with Fallback (run off the asyncio event loop)
        import time, os, uuid
        ext = os.path.splitext(pf["filename"])[1].lower() if pf["filename"] else ".jpg"
        relative_path = f"app/public/achievement/achievement_{current_agent.id}_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        secure_url = await run_in_threadpool(
            _upload_image_with_fallback,
            pf["bytes"],
            f"agent_achievements/{current_agent.id}",
            pf["hash"],
            relative_path
        )

        # Store the uploaded photo URL
        pf["photo_url"] = secure_url

    # Save to DB via service layer
    profile_service = ProfileService(AgentRepository(db))
    uploaded_results = profile_service.save_achievement_photos(
        agent_id=current_agent.id,
        processed_files=processed_files,
        existing_photos_map=existing_photos_map
    )

    # Construct response
    return {
        "success": True,
        "photos": uploaded_results
    }

@router.get("/profile/companies")
def get_companies(current_agent: Agent = Depends(get_current_agent), db: Session = Depends(get_db)):
    """
    Get the list of insurance companies grouped by segment (health, life, motor, sme).
    Locked using authentication token for the agent.
    Fetched from the database table (seeded with initial list if empty).
    """
    from fastapi_app.models.insurance_company import InsuranceCompany
    import re
    
    # Check if table is empty
    count = db.query(InsuranceCompany).count()
    if count == 0:
        # Seed the table from existing list
        def slugify(text):
            text = text.lower()
            text = re.sub(r'[^a-z0-9\s-]', '', text)
            text = re.sub(r'[\s-]+', '-', text)
            return text.strip('-')
            
        inserted_slugs = set()
        for segment_type, company_names in INSURANCE_COMPANIES.items():
            for name in company_names:
                slug = slugify(name)
                # Check for slug duplicates within current seed
                if slug in inserted_slugs:
                    slug = f"{slug}-1"
                inserted_slugs.add(slug)
                db.add(InsuranceCompany(name=name, slug=slug))
        db.commit()
    
    # Query all companies from db
    companies = db.query(InsuranceCompany).all()
    
    # Group by segment
    grouped_companies = {
        "health": [],
        "life": [],
        "motor": [],
        "sme": []
    }
    
    # Fast lookup sets for static lists
    lookup = {
        seg: {name.lower().strip() for name in names}
        for seg, names in INSURANCE_COMPANIES.items()
    }
    
    for company in companies:
        c_name_lower = company.name.lower().strip()
        matched = False
        
        # Match against static mappings
        for seg, name_set in lookup.items():
            if c_name_lower in name_set:
                grouped_companies[seg].append(company.name)
                matched = True
        
        # Fallback if company is not in the predefined static lists
        if not matched:
            if "life" in c_name_lower:
                grouped_companies["life"].append(company.name)
            elif "health" in c_name_lower:
                grouped_companies["health"].append(company.name)
            else:
                grouped_companies["motor"].append(company.name)
                grouped_companies["sme"].append(company.name)
                
    # Deduplicate and sort in alphabetical order
    for seg in grouped_companies:
        grouped_companies[seg] = sorted(list(set(grouped_companies[seg])))
        
    return grouped_companies

@router.post("/profile/licenses/irdai")
async def upload_irdai_license(
    request: Request,
    file: UploadFile = File(...),
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Upload IRDAI license document.
    Guarded by edit_profile_certifications lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_certifications")
    
    # 1. Read file and validate
    file_bytes = await file.read()
    file_bytes = validate_document_file(file_bytes, file.filename or "irdai.pdf", file.content_type or "application/pdf")
    
    # 2. Get profile
    profile = db.query(AgentProfile).filter(AgentProfile.agent_id == current_agent.id).first()
    if not profile:
        profile = AgentProfile(agent_id=current_agent.id)
        db.add(profile)
        db.flush()
        
    old_path = profile.irdai_license_doc
    
    # 3. Save to Django media path
    import time, os
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"
    relative_path = f"app/public/insurance/irdai_{current_agent.id}_{int(time.time())}{ext}"
    
    try:
        saved_path = await run_in_threadpool(LocalStorageService.save_django_path_file, file_bytes, relative_path)
    except Exception as e:
        logger.error(f"Local storage failure for IRDAI: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save IRDAI license document.")
        
    # 4. Update DB
    profile.irdai_license_doc = saved_path
    db.commit()
    
    # 5. Cleanup old local file (if it was local)
    if old_path and not old_path.startswith("http"):
        try:
            full_old_path = os.path.join(settings.LOCAL_STORAGE_PATH, old_path)
            if os.path.exists(full_old_path):
                os.remove(full_old_path)
        except Exception:
            pass
            
    response_path = f"/media/{saved_path}" if not saved_path.startswith("http") else saved_path
    return {"status": "success", "message": "IRDAI license uploaded successfully.", "path": response_path}


@router.post("/profile/licenses/amfi")
async def upload_amfi_license(
    request: Request,
    file: UploadFile = File(...),
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Upload AMFI license document.
    Guarded by edit_profile_certifications lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_certifications")

    # 1. Read file and validate
    file_bytes = await file.read()
    file_bytes = validate_document_file(file_bytes, file.filename or "amfi.pdf", file.content_type or "application/pdf")
    
    # 2. Get profile
    profile = db.query(AgentProfile).filter(AgentProfile.agent_id == current_agent.id).first()
    if not profile:
        profile = AgentProfile(agent_id=current_agent.id)
        db.add(profile)
        db.flush()
        
    old_path = profile.amfi_license_doc
    
    # 3. Save to Django media path
    import time, os
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".jpg"
    relative_path = f"app/public/investment/amfi_{current_agent.id}_{int(time.time())}{ext}"
    
    try:
        saved_path = await run_in_threadpool(LocalStorageService.save_django_path_file, file_bytes, relative_path)
    except Exception as e:
        logger.error(f"Local storage failure for AMFI: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save AMFI license document.")
        
    # 4. Update DB
    profile.amfi_license_doc = saved_path
    db.commit()
    
    # 5. Cleanup old local file
    if old_path and not old_path.startswith("http"):
        try:
            full_old_path = os.path.join(settings.LOCAL_STORAGE_PATH, old_path)
            if os.path.exists(full_old_path):
                os.remove(full_old_path)
        except Exception:
            pass
            
    response_path = f"/media/{saved_path}" if not saved_path.startswith("http") else saved_path
    return {"status": "success", "message": "AMFI license uploaded successfully.", "path": response_path}


@router.get("/profile/generate-bio")
def generate_professional_bio(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Generate an AI professional bio using the authenticated agent's data.
    The data is pulled exclusively from the database using the agent's identity.
    Guarded by edit_profile_professional_bio feature lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_professional_bio")

    import os, sys
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
    from django.apps import apps
    if not apps.ready:
        django.setup()

    from apps.agents.models import Agent as DjangoAgent
    from apps.agents.models import AgentProfile as DjangoAgentProfile
    from apps.agents.views.bio_generator import generate_agent_bio_logic

    try:
        django_agent = DjangoAgent.objects.filter(id=current_agent.id).first()
        if not django_agent:
            raise HTTPException(status_code=404, detail="Agent profile not found in Django context.")

        django_profile, _ = DjangoAgentProfile.objects.get_or_create(agent=django_agent)
        
        bio = generate_agent_bio_logic(django_agent, django_profile, {})
        return {"status": "success", "bio": bio}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bio generation failed via FastAPI: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate professional bio. Please try again later.")


from pydantic import BaseModel

class CityCreateRequest(BaseModel):
    name: str

@router.get("/profile/serviceable-cities")
def get_serviceable_cities(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Retrieve a list of all active serviceable cities.
    """
    import os, sys
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
    from django.apps import apps
    if not apps.ready:
        django.setup()

    from apps.agents.models import City as DjangoCity

    cities = DjangoCity.objects.filter(is_active=True).order_by('name')
    result = [{"id": c.id, "name": c.name} for c in cities]
    return {"status": "success", "cities": result}


@router.post("/profile/serviceable-cities")
def add_serviceable_city(
    payload: CityCreateRequest,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Add a new city to the global database if it doesn't already exist.
    """
    import os, sys
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
    from django.apps import apps
    if not apps.ready:
        django.setup()

    from apps.agents.models import City as DjangoCity

    if not payload.name or not payload.name.strip():
        raise HTTPException(status_code=400, detail="City name is required.")

    name = payload.name.strip()
    
    # Check if city already exists (case-insensitive)
    existing_city = DjangoCity.objects.filter(name__iexact=name).first()
    if existing_city:
        return {
            "status": "success",
            "message": "City already exists.",
            "city": {"id": existing_city.id, "name": existing_city.name}
        }

    # Create new city
    from django.utils.text import slugify
    new_slug = slugify(name)
    new_city = DjangoCity.objects.create(name=name, slug=new_slug, state="", is_active=True)
    return {
        "status": "success",
        "message": "City added successfully.",
        "city": {"id": new_city.id, "name": new_city.name}
    }


@router.delete("/profile/achievement/{photo_id}")
def delete_achievement_photo_endpoint(
    photo_id: int,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Delete an achievement / gallery photo for the authenticated agent.
    Guarded by upload_achievements lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "upload_achievements")
    profile_service = ProfileService(AgentRepository(db))
    profile_service.delete_achievement_photo(current_agent.id, photo_id)
    return {"success": True, "message": "Achievement photo deleted successfully."}


@router.get("/profile/career-timeline/suggestions")
def career_timeline_suggestions_endpoint(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """
    Auto-detected career timeline milestones (read-only).
    Mirrors Django GET /agent/career-timeline/suggestions/ using shared business logic.
    """
    from apps.agents.models import Agent as DjangoAgent, AgentCareerTimeline
    from apps.agents.services.career_timeline_suggestions import (
        get_career_timeline_next_milestones,
        get_career_timeline_suggestions,
    )

    django_agent = (
        DjangoAgent.objects.filter(id=current_agent.id)
        .select_related('profile', 'performanceStats')
        .first()
    )
    if not django_agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    all_suggestions = get_career_timeline_suggestions(django_agent)
    try:
        used_keys = set(
            AgentCareerTimeline.objects.filter(agent=django_agent)
            .exclude(suggestion_key__isnull=True)
            .exclude(suggestion_key='')
            .values_list('suggestion_key', flat=True)
        )
    except Exception:
        used_keys = set()

    suggestions = [s for s in all_suggestions if s.get('key') not in used_keys]
    next_milestones = get_career_timeline_next_milestones(django_agent)
    next_milestones = [m for m in next_milestones if m.get('key') not in used_keys]

    return {
        "success": True,
        "status": "success",
        "suggestions": suggestions,
        "next_milestones": next_milestones,
    }


@router.get("/profile/career-timeline")
def get_career_timelines_endpoint(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Get all career timeline milestones for the authenticated agent.
    """
    profile_service = ProfileService(AgentRepository(db))
    items = profile_service.get_career_timelines(current_agent.id)
    return {"success": True, "data": items}


@router.post("/profile/career-timeline")
def add_career_timeline_endpoint(
    payload: dict,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Add a new career timeline milestone (Guarded by edit_profile_career_timeline lock).
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_career_timeline")
    profile_service = ProfileService(AgentRepository(db))
    created = profile_service.add_career_timeline(current_agent, payload)
    return {"success": True, "data": created, "message": "Career timeline event added."}


@router.put("/profile/career-timeline/{timeline_id}")
def update_career_timeline_endpoint(
    timeline_id: int,
    payload: dict,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Update a career timeline milestone (Guarded by edit_profile_career_timeline lock).
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_career_timeline")
    profile_service = ProfileService(AgentRepository(db))
    updated = profile_service.update_career_timeline(current_agent, timeline_id, payload)
    return {"success": True, "data": updated, "message": "Career timeline event updated."}


@router.delete("/profile/career-timeline/{timeline_id}")
def delete_career_timeline_endpoint(
    timeline_id: int,
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Delete a career timeline milestone.
    Guarded by edit_profile_career_timeline lock.
    """
    lock_service = LockUnlockService(db)
    lock_service.require_feature_unlocked(current_agent, "edit_profile_career_timeline")
    profile_service = ProfileService(AgentRepository(db))
    profile_service.delete_career_timeline(current_agent, timeline_id)
    return {"success": True, "message": "Career timeline event deleted successfully."}


@router.delete("/profile/licenses/irdai")
def delete_irdai_license_doc(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Remove uploaded IRDAI certificate document.
    """
    profile = db.query(AgentProfile).filter(AgentProfile.agent_id == current_agent.id).first()
    if profile:
        profile.irdai_license_doc = None
        db.commit()
    return {"success": True, "message": "IRDAI certificate document removed."}


@router.delete("/profile/licenses/amfi")
def delete_amfi_license_doc(
    current_agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db)
):
    """
    Remove uploaded AMFI certificate document.
    """
    profile = db.query(AgentProfile).filter(AgentProfile.agent_id == current_agent.id).first()
    if profile:
        profile.amfi_license_doc = None
        db.commit()
    return {"success": True, "message": "AMFI certificate document removed."}


