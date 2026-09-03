import json
import logging
import re
import time

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from apps.agents.models import Agent, AgentProfile, AgentBioGenerationLog
from apps.chatbot.llm_client import call_llm_with_fallback

logger = logging.getLogger(__name__)

BIO_MAX_CHARS = 500
BIO_MIN_CHARS = 180
BIO_JSON_KEYS = (
    "bio",
    "professional_bio",
    "professionalBio",
    "text",
    "content",
    "summary",
)


@require_POST
def generate_professional_bio(request):
    """
    AI Professional Bio Generator API (First-Person, SEO-Optimised, E-E-A-T).
    POST /agent/generate-bio/
    Supports logged-in agent or admin viewing/editing an agent profile.
    """
    try:
        from apps.admin_panel.views.dashboard import _get_admin_from_session

        admin_id = _get_admin_from_session(request)
        is_admin = bool(admin_id)

        if not is_admin and not request.user.is_authenticated:
            return JsonResponse(
                {"status": "error", "message": "Authentication required. Please log in."},
                status=401,
            )

        agent_id = request.POST.get("agent_id") or request.GET.get("agent_id")

        if is_admin and agent_id:
            agent = Agent.objects.filter(id=agent_id).first()
        else:
            agent = (
                Agent.objects.filter(user=request.user).first()
                if request.user.is_authenticated
                else None
            )
            if not agent and agent_id and is_admin:
                agent = Agent.objects.filter(id=agent_id).first()

        if not agent:
            return JsonResponse(
                {"status": "error", "message": "Agent profile not found."}, status=404
            )

        profile, _ = AgentProfile.objects.get_or_create(agent=agent)

        payload = {
            "full_name": request.POST.get("full_name"),
            "agency_name": request.POST.get("agency_name"),
            "experience_years": request.POST.get("experience_years"),
            "serviceable_cities": request.POST.get("serviceable_cities[]") or request.POST.get("serviceable_cities"),
            "languages": request.POST.get("languages"),
            "service_pincode": request.POST.get("service_pincode"),
            "investment_types": request.POST.getlist("investment_types[]") or request.POST.getlist("investment_types"),
            "license_number": request.POST.get("license_number"),
            "client_base": request.POST.get("client_base"),
            "success_rate": request.POST.get("success_rate"),
            "segments": request.POST.getlist("segments[]") or request.POST.getlist("segments"),
        }

        generated_bio = generate_agent_bio_logic(agent, profile, payload)
        if not generated_bio:
            return JsonResponse(
                {
                    "status": "error",
                    "message": "The generator returned an empty bio. Please try again.",
                },
                status=502,
            )
        return JsonResponse({"status": "success", "bio": generated_bio})

    except Exception as e:
        logger.error("Bio generation failed: %s", str(e), exc_info=True)
        if "agent" in locals() and agent:
            try:
                AgentBioGenerationLog.objects.create(
                    agent=agent,
                    status="failure",
                    error_message=str(e)[:2000],
                )
            except Exception:
                pass
        return JsonResponse(
            {
                "status": "error",
                "message": "Failed to generate professional bio. Please try again later.",
            },
            status=500,
        )


def generate_agent_bio_logic(agent: Agent, profile: AgentProfile, payload: dict) -> str:
    """
    Core logic to generate professional bio using agent profile and provided payload data.
    """
    fullname = payload.get("full_name") or agent.fullname or ""
    agency_name = payload.get("agency_name") or getattr(profile, "agency_name", "") or ""
    experience = payload.get("experience_years") or str(
        getattr(profile, "experience_years", "") or getattr(agent, "experience_range", "") or ""
    )

    city_post = payload.get("serviceable_cities")
    city = city_post if city_post else (
        getattr(agent, "city", "")
        or (profile.address.split(",")[0].strip() if getattr(profile, "address", None) else "")
        or ""
    )

    state = getattr(profile, "state", "") or ""
    languages = payload.get("languages") or getattr(profile, "formatted_languages", "") or ""
    pincode = payload.get("service_pincode") or agent.get_effective_pincode() or ""

    investments_post = payload.get("investment_types")
    if investments_post:
        investments = ", ".join([str(item) for item in investments_post if item])
    else:
        normalized = getattr(profile, "normalized_investment_types", None) or []
        investments = ", ".join(normalized) if normalized else ""

    is_licensed = bool(
        payload.get("license_number")
        or getattr(profile, "license_number", "")
        or getattr(profile, "arn_number", "")
    )

    client_base_post = payload.get("client_base")
    client_base = client_base_post if client_base_post else getattr(agent, "client_base", "")

    perf_stat = getattr(agent, "performanceStats", None)
    success_rate_post = payload.get("success_rate")
    if success_rate_post:
        success_rate = f"{success_rate_post}%" if not str(success_rate_post).endswith("%") else success_rate_post
    elif perf_stat and getattr(perf_stat, "success_rate", None) and float(perf_stat.success_rate) > 0:
        success_rate = f"{perf_stat.success_rate}%"
    else:
        success_rate = ""

    segments_post = payload.get("segments")
    if segments_post:
        all_insurance = list(dict.fromkeys([str(s).strip() for s in segments_post if s]))
    else:
        segments = getattr(agent, "ordered_insurance_segments", None) or []
        insurance_types = []
        if hasattr(agent, "insuranceSegments"):
            insurance_types = list(
                agent.insuranceSegments.values_list("segment_type", flat=True)
            )
        all_insurance = list(dict.fromkeys(list(segments) + insurance_types))

    insurance_str = ", ".join([s for s in all_insurance if s]) if all_insurance else ""

    agent_details = {}
    if fullname:
        agent_details["name"] = str(fullname)
    if agency_name:
        agent_details["company"] = str(agency_name)
    if experience:
        exp_text = str(experience).strip()
        agent_details["experience"] = exp_text if "year" in exp_text.lower() else f"{exp_text} years"
    if city:
        agent_details["city"] = str(city)
    if state:
        agent_details["state"] = str(state)
    if insurance_str:
        agent_details["insurance"] = insurance_str
    if languages:
        agent_details["languages"] = str(languages)
    if pincode:
        agent_details["pincode"] = str(pincode)
    if investments:
        agent_details["investments"] = investments
    if is_licensed:
        agent_details["licensed"] = "Yes, verified licensed agent"
    if client_base:
        agent_details["clients_served"] = str(client_base)
    if success_rate:
        agent_details["claim_success_rate"] = str(success_rate)
    agent_details["claim_support"] = "Yes"

    agent_details_json = json.dumps(agent_details, ensure_ascii=False, indent=2, default=str)

    system_prompt = (
        "You are a senior SEO copywriter and insurance branding expert with 15+ years of experience "
        "in creating high-converting profile content.\n\n"
        "Your task is to write a short professional bio for an insurance agent's public profile on an "
        "insurance marketplace.\n\n"
        "## Goal\n"
        "Create a bio that:\n"
        "- Builds trust instantly.\n"
        "- Improves profile SEO.\n"
        "- Increases profile engagement.\n"
        "- Encourages users to contact the agent.\n"
        "- Sounds completely human-written.\n"
        "- Reflects the agent's expertise using only the provided information.\n\n"
        "## Bio Requirements\n"
        f"- Length: {BIO_MIN_CHARS}–{BIO_MAX_CHARS} characters (strictly enforced).\n"
        "- Write ONLY in FIRST PERSON (I, We, My, Our). Do NOT use third person.\n"
        "- Single paragraph, no line breaks.\n"
        "- No bullet points, no emojis, no hashtags, no quotation marks, no markdown, no HTML.\n\n"
        "## Content Guidelines\n"
        "Generate the bio using ONLY the provided details. Never invent experience, certifications, "
        "awards, companies, licenses, achievements, or services not mentioned. If a field is missing, skip it.\n\n"
        "Naturally highlight the strongest available information such as:\n"
        "company name, clients served, languages spoken, claim success rate, specific investment types (like SIP, STP, SWP, PMS, NPS), "
        "insurance categories, years of experience, city/state, personalized policy guidance, "
        "claim assistance, and financial protection.\n\n"
        "## SEO Keywords (use naturally, never force)\n"
        "company name, pincode, Product Portfolio, Investment Types, SIP, STP, SWP, PMS, NPS, licensed, "
        "life insurance, health insurance, term insurance, motor insurance, car insurance, bike insurance, "
        "insurance advisor, claim assistance, financial protection, clients served, claim success rate.\n\n"
        "## Tone\n"
        "Professional, friendly, trustworthy, helpful, confident, customer-focused.\n"
        "Avoid: 'Best Agent', 'No.1 Advisor', 'Guaranteed Savings', '100% Success', 'Trusted by Everyone', "
        "'Leading Expert'. Never make false promises.\n\n"
        "## Output Format\n"
        "Return ONLY valid JSON with a single key 'bio'.\n"
        "Example: {\"bio\": \"I specialize in...\"}\n"
        "Do NOT add any explanation, notes, or extra text outside the JSON object."
    )

    user_prompt = (
        "Generate a first-person professional bio for the insurance agent below.\n\n"
        f"Agent details:\n{agent_details_json}\n\n"
        "Requirements:\n"
        f"- {BIO_MIN_CHARS} to {BIO_MAX_CHARS} characters (count carefully before responding).\n"
        "- First person only (I / We / My / Our). Do not use He / She / Name.\n"
        "- Single paragraph, no formatting.\n"
        "- Natural SEO keywords where applicable.\n"
        "- Return ONLY: {\"bio\": \"<bio text>\"}"
    )

    plain_system_prompt = (
        "Write a first-person professional insurance agent bio using only the supplied facts. "
        f"Return one paragraph, {BIO_MIN_CHARS}-{BIO_MAX_CHARS} characters, with no JSON, markdown, or labels."
    )
    plain_user_prompt = (
        f"Agent details:\n{agent_details_json}\n\n"
        "Write the bio paragraph now. First person only. Return only the bio text."
    )

    start_time = time.time()
    generated_bio, raw_output, response, provider_name = _generate_bio_with_retries(
        system_prompt,
        user_prompt,
        plain_system_prompt,
        plain_user_prompt,
    )
    generation_time = time.time() - start_time

    tokens = 0
    if response and getattr(response, "usage", None):
        tokens = getattr(response.usage, "total_tokens", 0) or 0

    if not generated_bio:
        logger.warning(
            "Bio generation returned empty output (provider=%s, raw_len=%s, raw_preview=%r)",
            provider_name,
            len(raw_output or ""),
            (raw_output or "")[:240],
        )

    try:
        AgentBioGenerationLog.objects.create(
            agent=agent,
            generation_time=generation_time,
            tokens_used=tokens,
            status="success" if generated_bio else "failure",
            error_message="" if generated_bio else "Empty bio after extraction",
        )
    except Exception:
        logger.warning("Could not write bio generation log", exc_info=True)

    return generated_bio


def _generate_bio_with_retries(system_prompt, user_prompt, plain_system_prompt, plain_user_prompt):
    """
    Call the LLM with retries tuned for reasoning models (e.g. Groq gpt-oss-120b)
    that can exhaust max_tokens on internal reasoning and return empty content.
    """
    attempts = (
        {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.65,
            "max_tokens": 1200,
            "reasoning_effort": "low",
        },
        {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.55,
            "max_tokens": 1600,
            "reasoning_effort": "low",
        },
        {
            "messages": [
                {"role": "system", "content": plain_system_prompt},
                {"role": "user", "content": plain_user_prompt},
            ],
            "temperature": 0.6,
            "max_tokens": 900,
            "reasoning_effort": "low",
        },
    )

    last_raw = ""
    last_response = None
    last_provider = ""

    for attempt in attempts:
        llm_kwargs = {
            key: value
            for key, value in attempt.items()
            if key != "messages"
        }
        try:
            response, provider = call_llm_with_fallback(
                messages=attempt["messages"],
                timeout=35.0,
                **llm_kwargs,
            )
        except Exception as exc:
            logger.warning("Bio LLM attempt failed: %s", exc)
            continue

        raw_output = _read_message_text(response)
        generated_bio = _extract_bio(raw_output)
        last_raw = raw_output or last_raw
        last_response = response
        last_provider = provider.get("name", "") if isinstance(provider, dict) else str(provider or "")

        if generated_bio:
            return generated_bio, raw_output, response, last_provider

        finish_reason = _finish_reason(response)
        logger.info(
            "Bio attempt produced empty extract (provider=%s finish_reason=%s raw_len=%s)",
            last_provider,
            finish_reason,
            len(raw_output or ""),
        )

    return _extract_bio(last_raw), last_raw, last_response, last_provider


def _finish_reason(response) -> str:
    try:
        return str(response.choices[0].finish_reason or "")
    except Exception:
        return ""


def _read_message_text(response) -> str:
    """Collect assistant text from standard and reasoning-model response shapes."""
    try:
        message = response.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return ""

    parts = []

    content = getattr(message, "content", None)
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
            else:
                text = getattr(block, "text", None) or getattr(block, "content", None) or ""
            if text and str(text).strip():
                parts.append(str(text).strip())

    message_data = {}
    if hasattr(message, "model_dump"):
        try:
            message_data = message.model_dump()
        except Exception:
            message_data = {}

    for attr in ("reasoning", "reasoning_content"):
        val = getattr(message, attr, None) or message_data.get(attr)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    combined = "\n".join(parts).strip()
    if combined:
        return combined

    if message_data:
        content_val = message_data.get("content")
        if isinstance(content_val, str) and content_val.strip():
            return content_val.strip()

    return ""


def _bio_from_parsed(parsed) -> str:
    if isinstance(parsed, str):
        return parsed.strip()
    if not isinstance(parsed, dict):
        return ""

    lowered = {str(key).lower(): value for key, value in parsed.items()}
    for key in BIO_JSON_KEYS:
        val = parsed.get(key)
        if val is None:
            val = lowered.get(key.lower())
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_bio(raw: str) -> str:
    """
    Extract the bio string from the LLM output.
    Handles: pure JSON, JSON wrapped in markdown fences, or plain text fallback.
    Strips markdown artefacts and enforces the character hard cap.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"^(?:here is|here's|output:|response:)\s*", "", cleaned, flags=re.IGNORECASE).strip()

    parsed = None
    try:
        parsed = json.loads(cleaned)
    except Exception:
        json_blob = re.search(r"\{[\s\S]*\}", cleaned)
        if json_blob:
            blob_text = json_blob.group(0)
            for candidate in (blob_text, blob_text.replace("\n", " ")):
                try:
                    parsed = json.loads(candidate)
                    break
                except Exception:
                    parsed = None

    bio = _bio_from_parsed(parsed)
    if not bio:
        for pattern in (
            r'"(?:bio|professional_bio|professionalBio)"\s*:\s*"((?:\\.|[^"\\])*)"',
            r"'(?:bio|professional_bio|professionalBio)'\s*:\s*'((?:\\.|[^'\\])*)'",
        ):
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                bio = match.group(1)
                break

    if not bio:
        bio = cleaned
        if bio.startswith("{") and re.search(r'"(?:bio|professional_bio)"', bio, flags=re.IGNORECASE):
            bio = ""

    if not isinstance(bio, str):
        bio = str(bio)

    bio = bio.replace("\\n", " ").replace('\\"', '"').replace("\\\\", "\\")
    bio = re.sub(r"[*#>`]", "", bio)
    bio = " ".join(bio.split()).strip()

    if bio.lower().startswith("{") and re.search(r'"(?:bio|professional_bio)"', bio, flags=re.IGNORECASE):
        inner = re.search(r'"(?:bio|professional_bio)"\s*:\s*"((?:\\.|[^"\\])*)"', bio, flags=re.IGNORECASE)
        if inner:
            bio = " ".join(inner.group(1).replace("\\n", " ").split())

    if len(bio) > BIO_MAX_CHARS:
        truncated = bio[: BIO_MAX_CHARS - 3]
        last_space = truncated.rfind(" ")
        bio = (truncated[:last_space] if last_space > 160 else truncated) + "..."

    return bio.strip()
