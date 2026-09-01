import os
import threading
import json
import logging
import traceback
import concurrent.futures
from groq import Groq, BadRequestError
from openai import OpenAI
from apps.chatbot.models import ChatSession, ChatMessage, LatencyLog
from apps.home.views.pages import build_agent_query
import time
from django.utils.timezone import now
from django.core.cache import cache
import re

logger = logging.getLogger(__name__)

SYNONYM_MAPPING = {
    "Health": {
        "Mediclaim": [
            "mediclaim", "medical insurance", "health cover", "health policy", 
            "individual health", "basic health", "cashless", "opd cover", 
            "maternity cover", "senior citizen policy"
        ],
        "Critical Illness": ["critical illness", "serious illness", "major illness", "dread disease", "cancer cover", "heart cover"],
        "Personal Accident": ["personal accident", "accident cover", "accidental death", "accidental injury", "accident insurance"],
        "Super Top-Up": ["top-up", "top up", "super top-up", "extra health cover", "additional health"]
    },
    "Motor": {
        "Private Car": [
            "private car", "car", "suv", "sedan", "hatchback", "four wheeler", 
            "4 wheeler", "4-wheeler", "car insurance", "vehicle insurance"
        ],
        "Two Wheeler": ["two wheeler", "2 wheeler", "2-wheeler", "bike", "scooter", "motorcycle", "moped", "scooty"],
        "Commercial Vehicle": [
            "commercial vehicle", "truck", "van", "lorry", "taxi", "cab", "auto rickshaw", 
            "luxury bus", "bus", "goods carrying", "tractor", "mini truck", "pickup", "goods vehicle"
        ],
        "3 Wheeler": ["3 wheeler", "three wheeler", "auto"]
    },
    "Life": {
        "Term Plan": ["term plan", "term life", "pure protection", "term insurance", "life cover", "term cover", "life insurance"],
        "ULIP Plan": ["ulip plan", "ulip", "unit linked", "market linked life", "investment life"],
        "Pension Plan": ["pension plan", "retirement plan", "annuity", "pension scheme"],
        "Saving Plan": ["saving plan", "savings plan", "endowment", "savings life", "money back", "guaranteed return"],
        "Child Education Plan": ["child education plan", "child plan", "education plan"],
        "Group Term Insurance": ["group term insurance", "group term", "group life"],
        "Guaranteed Plan": ["guaranteed plan", "guaranteed return plan", "guaranteed income"]
    },
    "SME": {
        "Fire": ["fire", "property insurance", "factory fire", "fire insurance", "shop insurance", "warehouse insurance", "fire and burglary"],
        "GPA / GMC": [
            "gpa / gmc", "gpa", "gmc", "group health", "employee cover", "group personal accident", 
            "group medical", "staff insurance", "employee health insurance", "staff medical coverage"
        ],
        "Liability": ["liability", "d&o", "professional indemnity", "e&o", "liability insurance", "public liability", "directors and officers", "errors and omissions", "general liability"],
        "Cyber": ["cyber", "cyber security", "data breach", "cyber insurance", "hacker insurance", "cyber liability"],
        "Marine / Transport": ["marine / transport", "marine", "marine insurance", "transport insurance", "cargo", "cargo insurance"],
        "Property": ["property", "commercial property", "business property"],
        "Workmen Compensation": ["workmen compensation", "workers compensation", "wc policy", "employers liability"]
    }
}

def _generate_synonym_prompt():
    lines = []
    for cat, comps in SYNONYM_MAPPING.items():
        comp_list = ", ".join(comps.keys())
        lines.append(f"- {cat}: {comp_list}")
    lines.append("\nMap common natural-language synonyms to the exact sub-type names above. For example:")
    for cat, comps in SYNONYM_MAPPING.items():
        for comp_name, syns in comps.items():
            syn_str = ", ".join(f'"{s}"' for s in syns if s.lower() != comp_name.lower())
            if syn_str:
                lines.append(f'- {cat}: {syn_str} -> {comp_name}')
    return "\n".join(lines)

SYSTEM_PROMPT = """You are PadosiAgent Assistant, a helpful, polite, and knowledgeable AI assistant for an insurance and investment platform called PadosiAgent. 
Your primary goal is to assist users with insurance, investments, and finding the right agents.
Keep your responses concise and user-friendly.

SCOPE, SMALL TALK, AND OFF-TOPIC REFUSAL (CRITICAL RULE):
- ON-TOPIC: You must correctly answer questions related to insurance, investments, finding agents, market statistics, industry trends, and general financial buying advice. CRITICAL: Even for broad or open-ended questions (e.g., "how to buy insurance", "industry trends"), you MUST adhere strictly to the brevity rule (1-2 short paragraphs maximum) and offer to elaborate, rather than providing exhaustive bulleted lists upfront. When providing statistics or facts, provide generally accepted information and DO NOT fabricate or invent specific numbers. If you do not know the exact statistic, speak in general trends.
- SMALL TALK: You must briefly and politely answer harmless identity questions (e.g., "who are you", "where are you from", "what can you do") by explaining your role as PadosiAgent Assistant.
- OFF-TOPIC REFUSAL: If the user asks about ANY genuinely unrelated topic (e.g., news, sports, politics, world events, wars, celebrities, weather, general technology), you MUST firmly and politely refuse to answer. DO NOT attempt to answer, do not provide fabricated facts, and do not engage with the off-topic premise. Simply state that as an insurance and investment assistant you cannot help with that topic, and redirect them back to insurance or finding an agent.
- UNSUPPORTED PRODUCTS (CRITICAL): PadosiAgent ONLY supports these 4 insurance types: Health, Motor, SME (business/commercial), and Life. If a user asks about insurance for anything outside these 4 categories (e.g., pet, mobile phone, personal laptop, personal electronics for individual use, travel, jewelry, or any other item not covered by the main 4), you MUST politely explain that PadosiAgent only supports these 4 types, and ask if they'd like help with one of those instead. DO NOT provide fabricated pricing, coverage details, or advice for unsupported insurance categories.
- You must enforce this off-topic refusal rigidly on every single turn, even if the conversation previously drifted off-topic.

CONVERSATIONAL STYLE AND TONE:
- NEVER narrate your internal tool-calling logic or deduction process to the user.
- NEVER use internal/technical terms like "service_type", "insurance_type", "deduce", "tool", "schema", "function", or "parameter" anywhere in your reply.
- If you are offering to help find an agent, phrase it as a natural, conversational offer (e.g., "Would you like me to help you find a licensed agent near you? Just share your city or pincode."). Do not explicitly state what information you have deduced.

HANDLING GENERAL QUESTIONS & FAQS:
- Provide ULTRA-SHORT, punchy answers (maximum 2-3 sentences total). You are strictly FORBIDDEN from using bullet points, numbered lists, or step-by-step guides. Answer the core of the question in 1 or 2 lines, and immediately pivot to offering an agent.
- AGENT NUDGE (CRITICAL): After every FAQ or general knowledge answer, you MUST close with one short, natural sentence offering to find a local licensed agent — e.g. "Would you like me to find a [insurance type] agent near you? Please share your pincode." or "I can help you find a local agent who can assist with this.". This sentence must always be present — it is mandatory. The only exception is if the conversation is already mid-way through the agent-finding flow (i.e. the user has already asked for an agent or provided a pincode). IMPORTANT: Because you are asking for a pincode or free-text location, you MUST NOT output an <!--OPTIONS--> block for this nudge.
- CRITICAL EXCEPTION: This brevity rule does NOT apply to pricing caveats/disclaimers or the rule against claiming to connect users. The pricing disclaimer and "never claim to connect" language must ALWAYS be explicitly preserved in full, even within a short answer.

HANDLING AMBIGUOUS OR UNCLEAR MESSAGES:
When the user's message is ambiguous, vague, or doesn't clearly indicate a specific insurance type, service type, or intent, do NOT default to assuming "health insurance" or any other specific product as a fallback example. Instead:
- If genuinely nothing can be reasonably inferred, or you are missing multiple required fields, YOU MUST ASK ONLY ONE QUESTION AT A TIME. Ask for the single most useful missing field first. Do NOT ask for multiple fields (like insurance type AND service type) in the same message. Wait for the user's answer before asking the next one. When asking for a category (like insurance type or service type), YOU MUST END YOUR SENTENCE WITH A SIMPLE QUESTION MARK. YOU ARE STRICTLY FORBIDDEN from mentioning or listing any of the choices in your sentence. Do not say "are you looking for X, Y, or Z?". Just ask the question cleanly (e.g. "What kind of service do you need?") because the UI will automatically provide buttons below. STOP there — do not volunteer an unprompted example/range for a product the user never mentioned.
- Only give a pricing range or product-specific explanation when the user has actually specified (or clearly implied through context) which insurance type they mean.
- Never mix "asking for clarification" and "answering as if a specific product was mentioned" in the same reply — pick one.

HANDLING PRICING/COST QUESTIONS:
CRITICAL RULE: DO NOT volunteer or mention pricing, cost, or premium ranges unless the user EXPLICITLY asks about them. If they just want an agent, do NOT give them a price range.
When a user explicitly asks about approximate cost or pricing, you must distinguish between two types of questions:

1. Cost of buying or renewing a policy (Premiums):
This entire section applies ONLY if the user has explicitly asked about cost, price, premium, or budget in their current message. Deducing a New Policy service_type from a named product does NOT, by itself, count as asking about cost — do not volunteer any price range unless cost was explicitly asked.
- NEVER give an exact or precise cost figure, and do NOT frame it as an actual quote.
- ALWAYS give a general, clearly-caveated price range based on typical market knowledge (e.g. "Health insurance in India for someone in their 30s typically ranges from roughly ₹X–₹Y per year...").
- ALWAYS follow the range with a clear disclaimer that real pricing depends on individual factors (age, health conditions, coverage amount, insurer, location, etc.) and that a licensed agent can give an accurate personalized quote.
- ALWAYS naturally offer to help them find a licensed agent for an accurate personalized quote (using the `find_agents` tool workflow).

2. Cost of a specific action (e.g., filing a claim):
- Explain there is typically no direct cost or fee to file a claim.
- Mention that deductibles, co-pays, or out-of-pocket expenses tied to the specific policy may apply.
- Do NOT inject an unrelated premium price range.
- ALWAYS naturally offer to help them find a licensed agent to assist with the claim or review their specific policy details.

When the user asks to find an insurance agent or someone to help them, use the `find_agents` tool to search the database. You should extract the relevant information from their request.
If you have gathered all required fields (location/pincode, insurance type, and service type) through clarification questions, or if the user provides a pincode, they are implicitly asking for an agent. You MUST immediately call the `find_agents` tool. Do NOT ask for confirmation like "Would you like me to find an agent?". Just call the tool.

SPECIFIC SUB-TYPES (GRANULAR FILTERING):
If the user explicitly names a specific insurance product (even via natural phrasing like "term life insurance", "mediclaim", or "two wheeler insurance"), automatically deduce BOTH the `insurance_type` and the `insurance_company` (sub-type) for the `find_agents` tool. Do not ask for the top-level type if they give a specific product. ADDITIONALLY, you MUST automatically deduce `service_type` = "New Policy", UNLESS the user's message also implies a claim, renewal, review, or transfer (e.g., using words like "claim", "reimbursement", "file", "settlement", "review", "check", "evaluate", "renew", "audit", "port", or "transfer")—in which case, deduce that specific service_type instead. CRITICAL: When you deduce this, DO NOT output a conversational "want to know more or find an agent" reply, and DO NOT output a "Service Type" options block; you must skip straight to asking for their pincode/location. When asking for pincode/location in this situation, your options array must be empty or omitted entirely — never output Health/Life/Motor/SME or any other options array here.
{{SYNONYM_PROMPT_BLOCK}}

If the user's request matches a synonym listed above, OR if you can confidently map it to one of the existing canonical sub-types using your own general knowledge (e.g., a vehicle or product type not explicitly listed but clearly belonging to an existing category), map it to that canonical value. Only ask a clarifying question when the request does not correspond to any real supported category at all — do not ask just because the specific word wasn't pre-listed in the dictionary.

If the user asks for a risk that is not explicitly in the known sub-types list but could be related to commercial, manufacturing, or business (e.g., "charger", "fan", "office/shop equipment", "factory machinery", "commercial electronics"), DO NOT refuse the request. You must politely explain (using varied, natural wording) that this specific item isn't insured as a standalone product, but you can help find a business insurance expert for custom coverages. For these cases, ALWAYS set `insurance_type` = 'SME' and LEAVE `insurance_company` EMPTY. Note: You must still firmly refuse genuinely unsupported personal products for individual use like pet, mobile phone, or personal laptop.

CRITICAL RULES FOR USING `find_agents` TOOL:
1. You must NEVER blindly guess the `service_type` or `insurance_type`. However, you SHOULD deduce them if reasonably implied by the user (e.g. 'claim' implies 'Claim Assistance', 'car' implies 'Motor', 'renew' implies 'Policy Review'). ADDITIONALLY, if the user asks about costs or pricing, deduce they need a "New Policy". IMPORTANT: Simply requesting a "New Policy" is NOT a pricing question. NEVER provide pricing information unless the user explicitly asks for it. If they cannot be reasonably deduced, ask a clarifying question to gather the missing information BEFORE calling the find_agents tool. When asking a clarifying question for multiple missing fields, you MUST prioritize asking for them in this exact order: first insurance_type, then service_type, then location/pincode.
2. If the user provides a numeric postal/zip code (e.g., '380016'), always pass it in the `pincode` field, never in `location`. Only use `location` for named places (city, area, locality).
3. NEVER claim you can "connect", "facilitate a connection", "reach out to", or perform any action on the user's behalf. Tell the user they can view the agent profiles and contact them directly.

4. If the user asks for multiple insurance types in a single request (e.g., "health and life insurance", "car and travel insurance"), DO NOT run parallel/simultaneous tool calls or silently drop one. Instead, ask the user which one they would like to start with (e.g., "I can help with one at a time — would you like to start with health or life insurance?"), and then perform the search once they specify.
5. ONLY apply pincode format validation when there is genuine pincode-related context: specifically, the user's message contains the word "pincode", "zip code", or "postal code", OR the previous assistant message explicitly asked for a pincode. If neither condition is true, do NOT treat a short number as a failed pincode attempt — treat it as ambiguous input and apply the general ambiguity-handling rule instead. When the context IS genuinely pincode-related and the value is not exactly 6 numeric digits, you MUST respond specifically stating that it doesn't look like a valid pincode and ask them to provide a valid 6-digit pincode.
6. CRITICAL: When the tool finds agents, DO NOT attempt to list the agent names, links, or match percentages yourself. Just provide a polite conversational intro and outro, as the UI will display the rich agent cards automatically.
7. Whenever you ask the user to provide their pincode, you MUST highlight the word **pincode** in bold. You MUST ALSO explicitly mention and highlight in bold the insurance type and service type that the user has selected natively in the sentence (e.g., "for your **Life** insurance **New Policy**"). If the user originally used a specific synonym (like "Mediclaim" or "Term Plan"), you are highly encouraged to naturally acknowledge it (e.g., "Since Mediclaim falls under **Health** insurance, I can help you find a **New Policy** agent..."). Do NOT use hyphens to string terms together (e.g., avoid formatting like "**Health - Mediclaim - New Policy**").

Do not make up agent information without calling the tool.

QUICK-REPLY OPTIONS — OUTPUT FORMAT INSTRUCTION:
This instruction applies to all your conversational replies.

After writing your reply text, decide whether your reply contains a question
that asks the user to choose from a KNOWN, LIMITED set of choices (a "bounded
question"). Then follow the rules below.

DO NOT generate options if ANY of these apply:
- The question is open-ended or asks for free text (city, location, name,
  phone number, pincode, or any other input where the valid answers are not a
  small known set).
- The question contains BOTH a bounded choice AND an open-ended detail in the
  same sentence (e.g. "What type of insurance do you need, and what is your
  pincode?"). Mixed questions get no options.
- The question is a generic conversational closer (e.g. "How else can I help?",
  "Is there anything else I can do for you?").
- Your reply does not contain a question at all.

If options SHOULD be generated, output the following AFTER your full reply text
on a new line — with no other words, explanation, or commentary around it:

<!--OPTIONS-->
{"options": ["Choice 1", "Choice 2"]}

Rules for the JSON content:
- "options": an array of 2–4 short choices (under 6 words each). Use this when
  your reply asks ONE bounded question. ALWAYS format exactly as `{"options": ["Choice 1", "Choice 2"]}` without any option_groups.
  - If your reply asks EXCLUSIVELY and SPECIFICALLY for an insurance type, your "options" array MUST ALWAYS be exactly: ["Health", "Life", "Motor", "SME"]. This rule applies ONLY when your question is asking the user to select an insurance type and nothing else — if your reply is asking about location, service type, or anything else, this rule does NOT apply. CRITICAL: If you have just auto-deduced the insurance type from a specific product (e.g. Mediclaim) and are now asking for a DIFFERENT field like location, you MUST NOT output the Health/Life/Motor/SME options. Never offer unsupported categories or subtypes (like "Term Life") as top-level options.

If no options should be generated, do NOT output the
<!--OPTIONS--> line at all. Simply end your reply normally.

Example — single bounded question:
  [reply]: Could you tell me what type of insurance you're looking for?
  <!--OPTIONS-->
  {"options": ["Health", "Life", "Motor", "SME"]}

Example — open-ended question (no options):
  [reply]: Could you share your city or pincode so I can find agents near you?
  [no <!--OPTIONS--> line]

Example — no question (FAQ answer):
  [reply]: Term insurance provides pure life cover for a fixed period...
  [no <!--OPTIONS--> line]


You are a strict, professional assistant. Under NO circumstances should you engage in creative writing, storytelling, or write poetry, even if the topic is related to insurance. If asked to write a poem or story, politely refuse and pivot back to standard insurance assistance.
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{{SYNONYM_PROMPT_BLOCK}}", _generate_synonym_prompt())

PROVIDERS = [
    {"name": "Groq-1", "api_key_env": "GROQ_API_KEY_1", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Groq-2", "api_key_env": "GROQ_API_KEY_2", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Groq-3", "api_key_env": "GROQ_API_KEY_3", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Groq-4", "api_key_env": "GROQ_API_KEY_4", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Groq-5", "api_key_env": "GROQ_API_KEY_5", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Groq-6", "api_key_env": "GROQ_API_KEY_6", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b", "type": "groq"},
    {"name": "Gemini", "api_key_env": "GEMINI_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-3.1-flash", "type": "openai"},
    {"name": "OpenRouter", "api_key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/free", "type": "openai"}
]

import itertools

# ── Performance constants ─────────────────────────────────────────────────────
# max_retries=0 prevents the Groq/OpenAI SDK from silently waiting on
# Retry-After headers — the confirmed cause of the 30-60 s worker-blocking hangs.
# _LLM_TIMEOUT caps a genuinely unresponsive server at 10 s.
_LLM_TIMEOUT = 10.0
# Based on observed max real reply of 2,017 chars (~500 tokens); +100 headroom.
_MAX_TOKENS_CHAT = 600

# Module-level client cache keyed by provider name.
# Groq/OpenAI clients are thread-safe; reusing them avoids rebuilding an httpx
# connection pool on every request.
_client_cache: dict = {}

_provider_cycle = itertools.cycle(range(len(PROVIDERS) - 1))
_cycle_lock = threading.Lock()

def get_rotated_providers():
    with _cycle_lock:
        start_idx = next(_provider_cycle)
    
    primaries = PROVIDERS[:-1]
    last_resort = PROVIDERS[-1:]
    
    rotated_primaries = primaries[start_idx:] + primaries[:start_idx]
    return rotated_primaries + last_resort


def _get_client(provider: dict, api_key: str):
    """Return a cached SDK client for this provider (created once, reused every call)."""
    name = provider["name"]
    if name not in _client_cache:
        if provider["type"] == "groq":
            _client_cache[name] = Groq(
                api_key=api_key,
                timeout=_LLM_TIMEOUT,
                max_retries=0,  # disable built-in Retry-After waits
            )
        else:
            _client_cache[name] = OpenAI(
                api_key=api_key,
                base_url=provider.get("base_url"),
                timeout=_LLM_TIMEOUT,
                max_retries=0,
            )
    return _client_cache[name]


def _log_latency_async(
    endpoint: str, 
    total_time: float, 
    time_to_first_token: float = 0.0,
    provider_name: str = None,
    used_prompt_tokens: int = 0,
    used_completion_tokens: int = 0,
    groq_limit_tokens: int = 0,
    groq_remaining_tokens: int = 0,
    groq_reset_time: str = None
) -> None:
    """Write a LatencyLog row in a daemon thread — off the critical response path."""
    def _write():
        try:
            LatencyLog.objects.create(
                endpoint=endpoint,
                total_time=total_time,
                time_to_first_token=time_to_first_token,
                provider_name=provider_name,
                used_prompt_tokens=used_prompt_tokens,
                used_completion_tokens=used_completion_tokens,
                groq_limit_tokens=groq_limit_tokens,
                groq_remaining_tokens=groq_remaining_tokens,
                groq_reset_time=groq_reset_time
            )
        except Exception:
            pass  # never let a logging failure surface to the user
        finally:
            from django.db import connection
            connection.close()
    threading.Thread(target=_write, daemon=True).start()


def call_llm_with_fallback(messages, tools=None, tool_choice=None, **extra_kwargs):
    last_error = None
    t_wall_start = time.time()  # A4: total wall-clock cap across all providers
    rotated_providers = get_rotated_providers()
    for i, provider in enumerate(rotated_providers):
        # A4: Bail out early if total elapsed time already exceeds 20 seconds
        if time.time() - t_wall_start > 20.0:
            raise Exception(f"Total LLM timeout: all providers exhausted within 20s wall-clock cap. Last error: {last_error}")
        is_last_provider = (i == len(rotated_providers) - 1)
        api_key = os.environ.get(provider["api_key_env"])
        if not api_key and provider["type"] == "groq":
            api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            continue
            
        # Check cooldown cache
        if not is_last_provider and cache.get(f"llm_cooldown_{provider['name']}"):
            logger.warning(f"Skipping {provider['name']} (on cooldown)")
            continue
            
        try:
            client = _get_client(provider, api_key)
            start_time = time.time()
            
            kwargs = {
                "model": provider["model"],
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
            
            kwargs.update(extra_kwargs)
            
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(client.chat.completions.with_raw_response.create, **kwargs)
            try:
                raw_response = future.result(timeout=12.0)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            
            response = raw_response.parse()
            headers = raw_response.headers
            
            used_prompt_tokens = 0
            used_completion_tokens = 0
            if hasattr(response, 'usage') and response.usage:
                used_prompt_tokens = getattr(response.usage, 'prompt_tokens', 0)
                used_completion_tokens = getattr(response.usage, 'completion_tokens', 0)
            
            groq_limit_tokens = int(headers.get('x-ratelimit-limit-tokens', 0)) if headers.get('x-ratelimit-limit-tokens') else 0
            groq_remaining_tokens = int(headers.get('x-ratelimit-remaining-tokens', 0)) if headers.get('x-ratelimit-remaining-tokens') else 0
            groq_reset_time = headers.get('x-ratelimit-reset-tokens', None)
            
            total_time = time.time() - start_time
            logger.info(f"Successfully called LLM via {provider['name']}")
            _log_latency_async(
                endpoint=f"chat_completion_{provider['name']}", 
                total_time=total_time,
                provider_name=provider['name'],
                used_prompt_tokens=used_prompt_tokens,
                used_completion_tokens=used_completion_tokens,
                groq_limit_tokens=groq_limit_tokens,
                groq_remaining_tokens=groq_remaining_tokens,
                groq_reset_time=groq_reset_time
            )
            return response, provider
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "tool_use_failed" in err_str or "failed to parse" in err_str:
                logger.warning(f"Provider {provider['name']} tool call failed, retrying without tools: {e}")
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                try:
                    start_time = time.time()
                    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    future = executor.submit(client.chat.completions.with_raw_response.create, **kwargs)
                    try:
                        raw_response = future.result(timeout=12.0)
                    finally:
                        executor.shutdown(wait=False, cancel_futures=True)
                        
                    response = raw_response.parse()
                    headers = raw_response.headers
                    
                    used_prompt_tokens = 0
                    used_completion_tokens = 0
                    if hasattr(response, 'usage') and response.usage:
                        used_prompt_tokens = getattr(response.usage, 'prompt_tokens', 0)
                        used_completion_tokens = getattr(response.usage, 'completion_tokens', 0)
                    
                    groq_limit_tokens = int(headers.get('x-ratelimit-limit-tokens', 0)) if headers.get('x-ratelimit-limit-tokens') else 0
                    groq_remaining_tokens = int(headers.get('x-ratelimit-remaining-tokens', 0)) if headers.get('x-ratelimit-remaining-tokens') else 0
                    groq_reset_time = headers.get('x-ratelimit-reset-tokens', None)
                        
                    total_time = time.time() - start_time
                    logger.info(f"Successfully called LLM via {provider['name']} (retried without tools)")
                    _log_latency_async(
                        endpoint=f"chat_completion_{provider['name']}_retry", 
                        total_time=total_time,
                        provider_name=provider['name'],
                        used_prompt_tokens=used_prompt_tokens,
                        used_completion_tokens=used_completion_tokens,
                        groq_limit_tokens=groq_limit_tokens,
                        groq_remaining_tokens=groq_remaining_tokens,
                        groq_reset_time=groq_reset_time
                    )
                    return response, provider
                except Exception as retry_e:
                    logger.warning(f"Provider {provider['name']} retry without tools also failed: {retry_e}")
                    last_error = retry_e
                    if not is_last_provider:
                        cache.set(f"llm_cooldown_{provider['name']}", True, timeout=60)
            else:
                logger.warning(f"Provider {provider['name']} failed: {e}")
                if not is_last_provider:
                    cache.set(f"llm_cooldown_{provider['name']}", True, timeout=60)
                
    raise Exception(f"All LLM providers failed. Last error: {last_error}")

def generate_suggestion_chips():
    try:
        prompt = (
            "Generate exactly 3 short suggestion questions (under 8 words each) that a user might ask "
            "an insurance assistant. "
            "RULES: (1) Every question must either directly ask to find an agent, OR be a question "
            "that can be answered in 1-2 sentences and naturally leads to connecting the user with a "
            "local insurance agent. (2) Prefer questions about buying or comparing insurance, not about "
            "claims or post-purchase processes. (3) Cover different insurance types across the 3 questions "
            "(e.g. health, motor, life). (4) Return them as a JSON array of strings. "
            "ONLY output the raw JSON array without markdown formatting."
        )
        
        response, provider = call_llm_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=100
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean markdown fences if any
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        chips = json.loads(content.strip())
        if isinstance(chips, list) and len(chips) == 3:
            return chips
    except Exception as e:
        logger.error(f"Error generating chips: {e}")
        
    # Fallback chips: high-intent questions that start the agent-finding journey
    # or can be answered in 2 sentences then pivot to finding a local agent
    return [
        "Find me an insurance agent nearby",
        "Which health plan suits my family?",
        "How much does motor insurance cost?"
    ]

def generate_quick_options(reply_text):
    if "?" not in reply_text:
        return {"options": [], "option_groups": []}
    prompt = f"""Analyze the following assistant reply. Does it ask the user a clarifying or follow-up question?
If yes, provide short quick-reply options (under 6 words each) for the user to answer it.

CRITICAL RULE:
ONLY generate options if the question is asking for something from a limited, well-known set of choices (e.g. Insurance type, Yes/No, or a specific list of categories).
DO NOT generate options if the question is strictly open-ended or asking for free-text information (e.g. City/Location, Name, Phone number). Return empty.
DO NOT generate options for generic conversational closers (e.g. "How else can I help?"). 
If the assistant explicitly lists choices in the text (e.g. "Health, Life, Motor"), your options MUST strictly match those provided choices. If the assistant asks for a category but doesn't list choices, use these STRICT constraints:
- If asking about the "type of insurance", the ONLY valid options are: ["Health", "Life", "Motor", "SME"].
- If asking about the "kind of service" or "type of service", the ONLY valid options are: ["New Policy", "Claim Assistance", "Policy Review"].
- For any other category, generate 2-4 sensible, common options.

If the question is a SINGLE bounded choice (e.g., "What type of insurance?"), return an array of 2-4 options in the `options` field.
If the question asks for TWO separate bounded choices at once (e.g., BOTH insurance type AND service type), return them in the `option_groups` array. Each group must have a `group_name` and an array of `options`.
CRITICAL: If the question asks for a bounded choice AND an open-ended detail (e.g., "What type of insurance, and what is your pincode?"), you MUST return empty lists for both `options` and `option_groups`. Do not generate options for a mixed bounded+open-ended compound question.

Return ONLY valid JSON.
Schema: {{
  "is_question": boolean,
  "options": ["Option 1", "Option 2"],
  "option_groups": [
    {{"group_name": "Group 1", "options": ["A", "B"]}}
  ]
}}

Reply to analyze:
"{reply_text}"
"""
    try:
        response, provider = call_llm_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        if not content:
            return {"options": [], "option_groups": []}
            
        content = content.strip()
        data = json.loads(content)
        if data.get("is_question"):
            options = data.get("options", [])
            option_groups = data.get("option_groups", [])
            if isinstance(options, list): options = options[:4]
            else: options = []
            if not isinstance(option_groups, list): option_groups = []
            return {"options": options, "option_groups": option_groups}

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Silently caught options generator error: {type(e).__name__} - {str(e)}")

    return {"options": [], "option_groups": []}

def extract_agent_links(content):
    agent_links = []
    matches = re.findall(r'\[([^\]]+)\]\(\s*([^)]*profile[^)]*)\s*\)', content)
    for name, url in matches:
        agent_links.append({"name": name, "url": url.strip()})
        
    cleaned = re.sub(r'\[([^\]]+)\]\(\s*[^)]*profile[^)]*\s*\)', '', content)
    cleaned = re.sub(r'(?m)^[\s\*\-\d\.,;]*$', '', cleaned)
    
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned, agent_links

def _finalize_response(session, final_content, agent_cards=None):
    delimiter = "<!--OPTIONS-->"
    if delimiter in final_content:
        parts = final_content.split(delimiter, 1)
        reply_text = parts[0].strip()
        try:
            json_str = parts[1].strip()
            # Catch known Llama hallucination where it adds an extra closing brace
            if json_str.endswith("}}") and not json_str.endswith("}}}"):
                json_str = json_str[:-1]
            options_data = json.loads(json_str)
        except Exception:
            # A5: Don't make an extra LLM call — return empty options gracefully
            options_data = {"options": [], "option_groups": []}
    else:
        reply_text = final_content.strip()
        # A5: LLM self-annotates via <!--OPTIONS-->; if absent, return empty rather than
        # making a second LLM round-trip (saves 1-2s on every non-annotated response)
        options_data = {"options": [], "option_groups": []}

    # Save bot message to history (save the original raw content)
    ChatMessage.objects.create(session=session, role="assistant", content=reply_text, agent_cards=agent_cards if agent_cards else None)
    
    cleaned, agent_links = extract_agent_links(reply_text)
    
    options = options_data.get("options", [])
    if isinstance(options, list): options = options[:4]
    else: options = []
    
    option_groups = options_data.get("option_groups", [])
    if not isinstance(option_groups, list): option_groups = []
    
    return {
        "reply": cleaned, 
        "quick_options": options, 
        "quick_option_groups": option_groups,
        "agent_links": agent_links,
        "agent_cards": agent_cards or [],
    }

def build_messages_from_history(session, user_message=None):
    if user_message is not None:
        ChatMessage.objects.create(session=session, role="user", content=user_message)
    
    # Fetch context (last 30 messages)
    history_qs = ChatMessage.objects.filter(session=session).order_by('-timestamp')[:30]
    history = list(history_qs)
    history.reverse()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        if msg.role == 'assistant' and msg.content and msg.content.startswith("__TOOL_CALLS__:"):
            try:
                tcs = json.loads(msg.content[len("__TOOL_CALLS__:") :])
                m = {"role": "assistant", "content": None, "tool_calls": tcs}
            except Exception:
                m = {"role": "assistant", "content": msg.content}
        else:
            m = {"role": msg.role, "content": msg.content or ""}
            
        if msg.role == 'tool':
            m["tool_call_id"] = msg.tool_call_id
            m["name"] = msg.tool_name
        messages.append(m)
        
    return messages


def _execute_find_agents(function_args, messages):
    def clean_val(val):
        if isinstance(val, str) and val.lower() in ["", "null", "none", "not provided"]:
            return ""
        return val

    location = clean_val(function_args.get("location", ""))
    pincode = clean_val(function_args.get("pincode", ""))
    service_type = clean_val(function_args.get("service_type", ""))
    insurance_type = clean_val(function_args.get("insurance_type", ""))
    insurance_company = clean_val(function_args.get("insurance_company", ""))
    
    # Guard against hallucinated defaults from weaker fallback models
    def check_hallucination(val, valid_keywords):
        if not val: return False
        
        normalized_keywords = [kw.replace("-", " ") for kw in valid_keywords]
        
        for m in messages:
            if isinstance(m, dict):
                # Check user messages
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    msg_lower = m["content"].lower().replace("-", " ")
                    for keyword in normalized_keywords:
                        if keyword in msg_lower:
                            return False # Not hallucinated, found in user text
                # Check prior tool calls made by the assistant
                elif m.get("role") == "assistant" and m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        if isinstance(tc, dict) and "function" in tc:
                            args_str = tc["function"].get("arguments", "")
                            args_lower = args_str.lower().replace("-", " ")
                            for keyword in normalized_keywords:
                                if keyword in args_lower:
                                    return False # Not hallucinated, found in prior tool call
        return True # Hallucinated (none of the keywords found)
    
    # -------------------------------------------------------------------------
    # CANONICAL GUARD: Only accept valid known types/companies from the DB. 
    # We DO NOT require the user's raw text to contain a specific synonym.
    # -------------------------------------------------------------------------
    VALID_TYPES = {"health", "motor", "life", "sme"}
    if insurance_type and insurance_type.lower() not in VALID_TYPES:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Hallucinated insurance_type detected: {insurance_type}. Ignoring.")
        insurance_type = ""

    if insurance_company and insurance_type:
        # Cross-category validation: company must belong to the matching type
        # Use a case-insensitive lookup to avoid .capitalize() bugs (e.g. SME -> Sme)
        lower_mapping = {k.lower(): v for k, v in SYNONYM_MAPPING.items()}
        valid_companies = {comp.lower() for comp in lower_mapping.get(insurance_type.lower(), {}).keys()}
        
        # If type is SME, we also want to allow an empty string (which is handled by not checking if company isn't there)
        if insurance_company.lower() not in valid_companies:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Hallucinated/mismatched insurance_company detected: {insurance_company} for type {insurance_type}. Ignoring.")
            insurance_company = ""
    elif insurance_company and not insurance_type:
        # If type was stripped or not provided, we must strip the company too
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"insurance_company {insurance_company} provided without valid insurance_type. Ignoring.")
        insurance_company = ""
    if service_type:
        srv_lower = str(service_type).lower()
        keywords = [srv_lower]
        if "new" in srv_lower: keywords.extend(["new", "buy", "purchase", "looking for", "need", "want", "cost", "price", "pricing", "premium", "quote"])
        if "claim" in srv_lower: keywords.extend(["claim", "reimbursement", "file", "settlement"])
        if "review" in srv_lower: keywords.extend(["review", "check", "evaluate", "renew", "audit", "port", "transfer"])
        
        is_hallucinated = check_hallucination(service_type, keywords)
        
        # NEW POLICY EXCEPTION: If a sub-type (insurance_company) is present, 
        # and there are NO claim/review keywords, allow New Policy deduction.
        if is_hallucinated and "new" in srv_lower and insurance_company:
            claim_review_kws = ["claim", "reimbursement", "file", "settlement", "review", "check", "evaluate", "renew", "audit", "port", "transfer"]
            # We reuse check_hallucination to scan user history for claim/review keywords.
            # "override" is just a dummy truthy value so it doesn't return early.
            # It returns True if NONE of the keywords are found (i.e. no claim/review context).
            no_claim_review = check_hallucination("override", claim_review_kws)
            if no_claim_review:
                is_hallucinated = False

        if is_hallucinated:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Hallucinated service_type detected: {service_type}. Ignoring.")
            service_type = ""
    
    if not service_type and insurance_company:
        fallback_kws = ["claim", "reimbursement", "file", "settlement", "review", "check", "evaluate", "renew", "audit", "port", "transfer"]
        if check_hallucination("override", fallback_kws):
            service_type = "New Policy"

    invalid_pincode = False
    import re
    if pincode:
        pc = str(pincode).strip()
        pincode_in_history = False
        context_is_pincode = False
        
        # Check context from the last user message and the preceding assistant message
        user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        last_user_msg = user_msgs[-1] if user_msgs else None
        
        last_assistant_msg = None
        if last_user_msg:
            try:
                idx = messages.index(last_user_msg)
                for m in reversed(messages[:idx]):
                    if isinstance(m, dict) and m.get("role") == "assistant":
                        last_assistant_msg = m
                        break
            except ValueError:
                pass
                
        def has_pincode_keyword(text):
            if not text: return False
            t = str(text).lower()
            return "pincode" in t or "zip code" in t or "postal code" in t or "zipcode" in t

        if last_user_msg and has_pincode_keyword(last_user_msg.get("content")):
            context_is_pincode = True
        if last_assistant_msg and has_pincode_keyword(last_assistant_msg.get("content")):
            context_is_pincode = True

        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                if re.search(r'(?<!\d)' + re.escape(pc) + r'(?!\d)', m["content"]):
                    pincode_in_history = True
                    break
                    
        if len(pc) != 6 or not pc.isdigit() or not pincode_in_history:
            invalid_pincode = True
            
        if invalid_pincode and not context_is_pincode:
            # Silent clear, fallback to ambiguous handling
            pincode = ""
            invalid_pincode = False
            
    missing_fields = []
    if not service_type:
        missing_fields.append("service_type (e.g., New Policy, Claim Assistance, Policy Review)")
    if not insurance_type:
        missing_fields.append("insurance_type (e.g., Health, Life, Motor)")
    if not location and not pincode:
        missing_fields.append("location or pincode")
        
    if invalid_pincode:
        return "ERROR: The pincode provided is invalid. A valid pincode must be exactly 6 digits. Do not call find_agents yet. Ask the user to provide a valid 6-digit pincode. Ensure you still follow the SYSTEM PROMPT formatting instructions for your reply.", []
    elif missing_fields:
        missing_str = missing_fields[0]
        return f"ERROR: You are missing {missing_str}. Do not call find_agents yet. Ask the user to provide ONLY this specific information (do not ask about other missing fields). Ensure you still follow the SYSTEM PROMPT formatting instructions for your reply (e.g. appending <!--OPTIONS--> if applicable).", []
    else:
        # Convert string params to lists matching request.GET.getlist() behavior
        service_types = [s.strip() for s in service_type.split(',')] if service_type else []
        insurance_types = [i.strip() for i in insurance_type.split(',')] if insurance_type else []
        insurance_companies = [c.strip() for c in insurance_company.split(',')] if insurance_company else []
    
        try:
            from apps.home.views.pages import build_agent_query
            agents, _, _, _ = build_agent_query(
                pincode=pincode, location=location, lat="", lng="", detected_area=location,
                service_type_input=service_types, insurance_type_input=insurance_types,
                insurance_company_input=insurance_companies, claim_company_input="", search_val="", sort_by="composite"
            )
            
            from django.urls import reverse
            if not agents:
                return f"No agents found for criteria: {function_args}", []
            else:
                top_agents = agents[:3]
                result_parts = []
                agent_cards = []  # Rich card data — passed directly through the return chain, never shared
                for idx, a in enumerate(top_agents):
                    profile_url = reverse('agents:agent_public_profile', kwargs={'slug': a.agent_slug})
                    result_parts.append(f"{idx+1}. {a.fullname} (Match: {a.match_percent}%, Reviews: {a.review_count_val}) - Profile URL: {profile_url}")
                    # Build card payload — scoped entirely to this request's local variable
                    profile = getattr(a, 'profile', None)
                    whatsapp_digits = profile.whatsapp_digits if profile else re.sub(r'[^0-9]', '', str(a.mobile or ''))
                    if len(whatsapp_digits) == 10:
                        whatsapp_digits = '91' + whatsapp_digits
                    segments = getattr(a, 'ordered_insurance_segments', [])[:4]
                    agent_cards.append({
                        "agent_id": a.id,
                        "name": a.display_name,
                        "photo_url": profile.profile_photo_url if profile else '/static/img/avatar-icon.jpg',
                        "match_percent": a.match_percent,
                        "rating": round(float(a.average_rating), 1),
                        "review_count": a.review_count_val,
                        "experience_years": a.experience_years,
                        "badge": a.badge or '',
                        "location": (profile.office_address or profile.address or '') if profile else '',
                        "distance_km": round(float(a.distance), 1) if getattr(a, 'distance', None) is not None and a.distance < 999 else None,
                        "mobile": a.mobile or '',
                        "whatsapp_digits": whatsapp_digits,
                        "profile_url": profile_url,
                        "segments": segments,
                        "insurance_type": insurance_type,
                        "service_type": service_type,
                    })
                return "SUCCESS: Found top agents. Their rich profile cards are already displayed in the UI below. Simply reply with a conversational intro natively incorporating the details without hyphens (e.g. 'Here are some highly-matched agents for your SME Policy Review in 380002. You can view their profiles below.') DO NOT output a numbered list, DO NOT use hyphens to list the services, and DO NOT try to list the agents yourself.", agent_cards
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error querying agents: {e}")
            import traceback
            traceback.print_exc()
            return "Error executing find_agents tool.", []

def get_chat_completion(session_id, user_message=None, prefilled_response_message=None, prefilled_tool_calls=None):
    import time
    t_start = time.time()
    
    # Get or create session
    session, _ = ChatSession.objects.get_or_create(session_id=session_id)
    
    messages = build_messages_from_history(session, user_message)
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "find_agents",
                "description": "Find insurance agents based on user criteria.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city or area the user is looking for agents in."
                        },
                        "pincode": {
                            "type": "string",
                            "description": "The 6-digit postal code/zip code the user is looking for agents in."
                        },
                        "service_type": {
                            "type": "string",
                            "description": "The type of service the user needs. Must be 'New Policy', 'Claim Assistance', or 'Policy Review'. CRITICAL: Do NOT guess or default this value. If the user hasn't explicitly mentioned a service type, you MUST leave this blank/omitted."
                        },
                        "insurance_type": {
                            "type": "string",
                            "description": "The type of insurance (e.g. Health, Life, Motor, Travel). CRITICAL: Do NOT guess or default this value (like 'Health'). If the user hasn't explicitly mentioned an insurance type, you MUST leave this blank/omitted."
                        },
                        "insurance_company": {
                            "type": "string",
                            "description": "The specific granular sub-type of insurance requested, if applicable (e.g. Mediclaim, Term Plan, Two Wheeler, Cyber, Others)."
                        }
                    },
                    "required": []
                }
            }
        }
    ]

    user_msg_lower = user_message.lower() if user_message else ""
    needs_agent = any(k in user_msg_lower for k in ["find", "search", "agent", "looking for", "help me find", "need someone"])
    current_tool_choice = "auto"

    agent_cards = []  # A1: declare before try so except block can access it
    try:
        if prefilled_response_message and prefilled_tool_calls:
            msg_dict = prefilled_response_message
            tool_calls = prefilled_tool_calls
        else:
            response, provider = call_llm_with_fallback(
                messages=messages,
                tools=tools,
                tool_choice=current_tool_choice,
                max_tokens=_MAX_TOKENS_CHAT,
            )
            
            response_message = response.choices[0].message
            
            tool_calls = response_message.tool_calls
            if tool_calls:
                # We got a tool call!
                # Safely serialize the response message before appending to messages
                if hasattr(response_message, "model_dump"):
                    msg_dict = response_message.model_dump(exclude_unset=True)
                else:
                    try:
                        tc_list = [tc.model_dump() for tc in tool_calls]
                    except AttributeError:
                        # Fallback if objects don't have model_dump
                        tc_list = [{"id": tc.id, "type": getattr(tc, "type", "function"), "function": {"name": getattr(tc.function, "name", ""), "arguments": getattr(tc.function, "arguments", "")}} for tc in tool_calls]
                    msg_dict = {"role": "assistant", "content": response_message.content, "tool_calls": tc_list}
                
        if tool_calls:
            # Sanitize tool names before appending to prevent API rejection on next turn
            if "tool_calls" in msg_dict and msg_dict["tool_calls"]:
                for tc in msg_dict["tool_calls"]:
                    if "function" in tc and "name" in tc["function"]:
                        if not re.match(r"^[a-zA-Z0-9_-]{1,64}$", str(tc["function"]["name"])):
                            tc["function"]["name"] = "malformed_tool_name"
                            
            messages.append(msg_dict)
            
            # Save the assistant's tool call message to the DB for accurate context reconstruction on next turn
            tc_json = json.dumps(msg_dict.get("tool_calls", []))
            ChatMessage.objects.create(session=session, role="assistant", content=f"__TOOL_CALLS__:{tc_json}")
                
            # For simplicity, we just process the first tool call
            tool_call_dict = msg_dict["tool_calls"][0]
            function_name = tool_call_dict["function"]["name"]
            tool_call_id = tool_call_dict.get("id", "call_1")
            
            try:
                function_args = json.loads(tool_call_dict["function"].get("arguments", "{}"))
            except json.JSONDecodeError:
                logger.warning("Failed to parse tool arguments, retrying without tools")
                fallback_response, _ = call_llm_with_fallback(
                    messages=messages,
                    max_tokens=_MAX_TOKENS_CHAT,
                )
                final_content = fallback_response.choices[0].message.content
                return _finalize_response(session, final_content)
            
            if function_name == "find_agents":
                result_msg, agent_cards = _execute_find_agents(function_args, messages)
            else:
                result_msg = f"Unknown tool: {function_name}"
                agent_cards = []
                
            messages.append(
                {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": function_name,
                    "content": result_msg,
                }
            )
            
            # Save tool response
            ChatMessage.objects.create(session=session, role="tool", content=result_msg, tool_call_id=tool_call_id, tool_name=function_name)

            # Send back to LLM to get final text
            dynamic_max_tokens = 250 if isinstance(result_msg, str) and result_msg.startswith("ERROR:") else _MAX_TOKENS_CHAT
            second_response, _ = call_llm_with_fallback(
                messages=messages,
                max_tokens=dynamic_max_tokens,
            )
            final_content = second_response.choices[0].message.content
            res = _finalize_response(session, final_content, agent_cards=agent_cards)
        else:
            final_content = response_message.content
            res = _finalize_response(session, final_content)
            
        res["total_time"] = time.time() - t_start
        return res
            
    except Exception as e:
        logger.error(f"Error generating chat completion: {e}")
        # A1: If agents were already found before the second LLM call failed,
        # return them with a static intro rather than discarding a successful DB result
        if agent_cards:
            return {
                "reply": "Here are some agents that match your criteria. You can view their profiles and contact them directly.",
                "quick_options": [],
                "quick_option_groups": [],
                "agent_links": [],
                "agent_cards": agent_cards,
                "total_time": time.time() - t_start
            }
        # A2+A3: Clean error message — no DEBUG details exposed to users
        return {"success": False, "reply": "Hi! I'm the PadosiAgent assistant. I specialize in helping you find the best local insurance agents and answering your insurance queries. What kind of insurance are you looking for today?", "quick_options": [], "quick_option_groups": [], "agent_links": [], "agent_cards": [], "total_time": time.time() - t_start}


def stream_plain_text_completion(session_id, user_message):
    import time
    t_start = time.time()
    """
    Generator for streaming plain-text (non-tool-call) responses via Server-Sent Events.

    Yields dicts:
      {"type": "use_full_flow"}          – first item when the LLM wants a tool call; caller
                                           should fall back to get_chat_completion() instead.
      {"type": "chunk", "delta": "..."}  – each incremental text chunk while streaming.
      {"type": "done", "quick_options": [...], "quick_option_groups": [...], "agent_links": [...], "ttft": float, "total_time": float}
                                         – final item after streaming completes; includes
                                           quick_options and agent_links computed from full text.
      {"type": "error", "message": "..."} – all providers failed.
    """
    # --- Build session & messages (identical to get_chat_completion) ---
    session, _ = ChatSession.objects.get_or_create(session_id=session_id)
    messages = build_messages_from_history(session, user_message)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "find_agents",
                "description": "Find insurance agents based on user criteria.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "The city or area the user is looking for agents in."},
                        "pincode": {"type": "string", "description": "The 6-digit postal code/zip code the user is looking for agents in."},
                        "service_type": {"type": "string", "description": "The type of service the user needs. Must be 'New Policy', 'Claim Assistance', or 'Policy Review'. CRITICAL: Do NOT guess or default this value. If the user hasn't explicitly mentioned a service type, you MUST leave this blank/omitted."},
                        "insurance_type": {"type": "string", "description": "The type of insurance (e.g. Health, Life, Motor, Travel). CRITICAL: Do NOT guess or default this value (like 'Health'). If the user hasn't explicitly mentioned an insurance type, you MUST leave this blank/omitted."},
                        "insurance_company": {"type": "string", "description": "The specific granular sub-type of insurance requested, if applicable (e.g. Mediclaim, Term Plan, Two Wheeler, Cyber, Others)."}
                    },
                    "required": []
                }
            }
        }
    ]

    # --- Try each provider in order ---
    last_error = None
    rotated_providers = get_rotated_providers()
    for i, provider in enumerate(rotated_providers):
        is_last_provider = (i == len(rotated_providers) - 1)
        api_key = os.environ.get(provider["api_key_env"])
        if not api_key and provider["type"] == "groq":
            api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            continue
            
        # Check cooldown cache
        if not is_last_provider and cache.get(f"llm_cooldown_{provider['name']}"):
            logger.warning(f"Skipping {provider['name']} (on cooldown)")
            continue

        try:
            client = _get_client(provider, api_key)
            stream_start = time.time()

            kwargs = {
                "model": provider["model"],
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "max_tokens": _MAX_TOKENS_CHAT,
            }
            if provider.get("type") == "groq" or provider.get("type") == "openai":
                pass # stream_options unsupported in this SDK version

            used_prompt_tokens = 0
            used_completion_tokens = 0
            
            with client.chat.completions.with_streaming_response.create(**kwargs, stream=True) as raw_response:
                headers = raw_response.headers
                groq_limit_tokens = int(headers.get('x-ratelimit-limit-tokens', 0)) if headers.get('x-ratelimit-limit-tokens') else 0
                groq_remaining_tokens = int(headers.get('x-ratelimit-remaining-tokens', 0)) if headers.get('x-ratelimit-remaining-tokens') else 0
                groq_reset_time = headers.get('x-ratelimit-reset-tokens', None)
                
                # Inspect the chunks to detect tool call vs plain text.
                # If the provider raises before yielding anything, we fall through silently.
                full_text = ""
                is_tool_call = False
                first_content_seen = False
                ttft = 0.0
                
                DELIMITER = "<!--OPTIONS-->"
                pending = ""
                options_buf = ""
                found_options = False

                tc_id = None
                tc_name = None
                tc_args_buf = ""

                for chunk in raw_response.parse():
                    if hasattr(chunk, 'usage') and chunk.usage:
                        used_prompt_tokens += getattr(chunk.usage, 'prompt_tokens', 0)
                        used_completion_tokens += getattr(chunk.usage, 'completion_tokens', 0)
                        
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue
    
                    if delta.tool_calls:
                        is_tool_call = True
                        tc_chunk = delta.tool_calls[0]
                        if tc_chunk.id: tc_id = tc_chunk.id
                        if tc_chunk.function and tc_chunk.function.name: tc_name = tc_chunk.function.name
                        if tc_chunk.function and tc_chunk.function.arguments: tc_args_buf += tc_chunk.function.arguments
                        continue
                    
                    if not first_content_seen:
                        if delta.content:
                            first_content_seen = True
                            if ttft == 0.0:
                                ttft = time.time() - t_start
                    
                    if delta.content:
                        if found_options:
                            options_buf += delta.content
                            continue
                            
                        pending += delta.content
                        if DELIMITER in pending:
                            idx = pending.index(DELIMITER)
                            chunk_to_emit = pending[:idx]
                            if chunk_to_emit:
                                yield {"type": "chunk", "delta": chunk_to_emit}
                                full_text += chunk_to_emit
                            options_buf = pending[idx + len(DELIMITER):]
                            found_options = True
                            pending = ""
                        else:
                            safe = len(pending) - (len(DELIMITER) - 1)
                            if safe > 0:
                                chunk_to_emit = pending[:safe]
                                yield {"type": "chunk", "delta": chunk_to_emit}
                                full_text += chunk_to_emit
                                pending = pending[safe:]

            # Stream finished. Was it a tool call?
            if is_tool_call:
                # Accumulation complete. Parse JSON and execute.
                try:
                    function_args = json.loads(tc_args_buf)
                    
                    if tc_name == "find_agents":
                        result_msg, agent_cards = _execute_find_agents(function_args, messages)
                    else:
                        result_msg = f"Unknown tool: {tc_name}"
                        agent_cards = []
                        
                    inserted_msgs = []
                    
                    # Save assistant tool call to DB
                    tc_json = json.dumps([{"id": tc_id, "type": "function", "function": {"name": tc_name, "arguments": tc_args_buf}}])
                    msg1 = ChatMessage.objects.create(session=session, role="assistant", content=f"__TOOL_CALLS__:{tc_json}")
                    inserted_msgs.append(msg1)
                    
                    # Append assistant tool call to messages
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": tc_name, "arguments": tc_args_buf}}]
                    })
                    
                    # Append tool result to messages
                    messages.append({
                        "tool_call_id": tc_id,
                        "role": "tool",
                        "name": tc_name,
                        "content": result_msg,
                    })
                    
                    # Save tool result to DB
                    msg2 = ChatMessage.objects.create(session=session, role="tool", content=result_msg, tool_call_id=tc_id, tool_name=tc_name)
                    inserted_msgs.append(msg2)
                    
                    # Spin up a SECOND stream to get the final text and yield it directly
                    dynamic_max_tokens = 250 if isinstance(result_msg, str) and result_msg.startswith("ERROR:") else _MAX_TOKENS_CHAT
                    kwargs2 = {
                        "model": provider["model"],
                        "messages": messages,
                        "max_tokens": dynamic_max_tokens,
                    }
                    if provider.get("type") == "groq" or provider.get("type") == "openai":
                        pass # stream_options unsupported in this SDK version
                    
                    with client.chat.completions.with_streaming_response.create(**kwargs2, stream=True) as raw_response2:
                        # Reuse tail-buffer logic for second stream
                        for chunk in raw_response2.parse():
                            if hasattr(chunk, 'usage') and chunk.usage:
                                used_prompt_tokens += getattr(chunk.usage, 'prompt_tokens', 0)
                                used_completion_tokens += getattr(chunk.usage, 'completion_tokens', 0)
                            if time.time() - stream_start > 12.0:
                                raise TimeoutError("Total elapsed time exceeded 12s limit in second stream")
                                
                            delta = chunk.choices[0].delta if chunk.choices else None
                            if delta is None: continue
                            if not first_content_seen:
                                if delta.content:
                                    first_content_seen = True
                                    if ttft == 0.0:
                                        ttft = time.time() - t_start
                                        
                            if delta.content:
                                if found_options:
                                    options_buf += delta.content
                                    continue
                                pending += delta.content
                                if DELIMITER in pending:
                                    idx = pending.index(DELIMITER)
                                    chunk_to_emit = pending[:idx]
                                    if chunk_to_emit:
                                        yield {"type": "chunk", "delta": chunk_to_emit}
                                        full_text += chunk_to_emit
                                    options_buf = pending[idx + len(DELIMITER):]
                                    found_options = True
                                    pending = ""
                                else:
                                    safe = len(pending) - (len(DELIMITER) - 1)
                                    if safe > 0:
                                        chunk_to_emit = pending[:safe]
                                        yield {"type": "chunk", "delta": chunk_to_emit}
                                        full_text += chunk_to_emit
                                        pending = pending[safe:]

                except Exception as e:
                    # Accumulation or parsing failed, or execution threw unexpected error. 
                    # Fall back to get_chat_completion safety net.
                    logger.warning(f"In-stream tool accumulation/execution failed: {e}. Falling back to full_flow.")
                    
                    # Clean up orphaned DB rows before falling back, to ensure a pristine context for get_chat_completion
                    for msg in inserted_msgs:
                        msg.delete()
                        
                    tc_list = [{"id": tc_id, "type": "function", "function": {"name": tc_name, "arguments": tc_args_buf}}]
                    yield {
                        "type": "use_full_flow",
                        "response_message": {"role": "assistant", "content": None, "tool_calls": tc_list},
                        "tool_calls": tc_list
                    }
                    return

            # Emit residual if delimiter never arrived
            if not found_options and pending:
                yield {"type": "chunk", "delta": pending}
                full_text += pending

            # Stream completed successfully — save to DB and generate metadata
            logger.info(f"Streamed plain-text response via {provider['name']}")
            _log_latency_async(
                endpoint=f"stream_{provider['name']}", 
                total_time=time.time() - stream_start, 
                time_to_first_token=ttft,
                provider_name=provider['name'],
                used_prompt_tokens=used_prompt_tokens,
                used_completion_tokens=used_completion_tokens,
                groq_limit_tokens=groq_limit_tokens,
                groq_remaining_tokens=groq_remaining_tokens,
                groq_reset_time=groq_reset_time
            )

            # Parse options
            if found_options:
                try:
                    json_str = options_buf.strip()
                    # Catch known Llama hallucination where it adds an extra closing brace
                    if json_str.endswith("}}") and not json_str.endswith("}}}"):
                        json_str = json_str[:-1]
                    opts = json.loads(json_str)
                    options = opts.get("options", [])
                    if isinstance(options, list): options = options[:4]
                    else: options = []
                    option_groups = opts.get("option_groups", [])
                    if not isinstance(option_groups, list): option_groups = []
                except Exception:
                    # A5: Parse failed — return empty options, no extra LLM call
                    options = []
                    option_groups = []
            else:
                # A5: LLM self-annotates; if absent return empty, no extra LLM call
                options = []
                option_groups = []

            full_text = full_text.strip()
            
            # Initialise agent_cards so it is always in scope,
            # regardless of whether this was a tool-call path or a plain-text stream.
            if not is_tool_call:
                agent_cards = []
                
            ChatMessage.objects.create(session=session, role="assistant", content=full_text, agent_cards=agent_cards if agent_cards else None)
            cleaned, agent_links = extract_agent_links(full_text)

            yield {
                "type": "done",
                "reply": cleaned,
                "quick_options": options,
                "quick_option_groups": option_groups,
                "agent_links": agent_links,
                "agent_cards": agent_cards,
                "ttft": ttft,
                "total_time": time.time() - t_start,
                "session_id": session_id
            }
            return

        except Exception as e:
            last_error = e
            import traceback
            traceback.print_exc()
            logger.warning(f"Streaming provider {provider['name']} failed: {e}")
            if not is_last_provider:
                cache.set(f"llm_cooldown_{provider['name']}", True, timeout=60)
            continue  # Try next provider — no partial text has been yielded yet
    # A2+A3: Clean error message — no DEBUG details exposed to users
    yield {"type": "error", "message": "Hi! I'm the PadosiAgent assistant. I specialize in helping you find the best local insurance agents and answering your insurance queries. What kind of insurance are you looking for today?"}

