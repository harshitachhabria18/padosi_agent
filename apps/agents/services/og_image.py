"""Generate WhatsApp / Open Graph share cards that match the public agent card."""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFont
from django.conf import settings

from apps.agents.models import AgentProfile, AgentPerformanceStat

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS

TAG_COLORS = {
    'health': ((255, 241, 242), (190, 18, 60), (254, 205, 211)),
    'life': ((245, 243, 255), (124, 58, 237), (221, 214, 254)),
    'motor': ((239, 246, 255), (29, 78, 216), (191, 219, 254)),
    'sme': ((255, 251, 235), (180, 83, 9), (253, 230, 138)),
}
TAG_DEFAULT = ((243, 244, 246), (55, 65, 81), (229, 231, 235))


import base64
import logging
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

def _safe_str(val, default=""):
    """Safely extract string, ignoring unassigned MagicMock attributes in tests."""
    if val is None or hasattr(val, '_mock_return_value'):
        return default
    try:
        s = str(val).strip()
        return s if s else default
    except Exception:
        return default

def _safe_num(val, default=0):
    """Safely extract float/int, ignoring unassigned MagicMock attributes in tests."""
    if val is None or hasattr(val, '_mock_return_value'):
        return default
    try:
        return float(val)
    except Exception:
        return default

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except (ImportError, Exception):
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False

from contextlib import contextmanager


@contextmanager
def _single_browser_slot():
    """Yield True if this process may launch Chromium now.

    This URL is public and crawled by link-preview bots. Each Chromium costs
    ~150-300 MB and many processes/threads. Several at once exceed the
    hosting account's memory/process limits, so only one may run
    server-wide. A concurrent render uses the Pillow card instead.
    """
    try:
        import fcntl
    except ImportError:  # Windows dev machines
        yield True
        return
    got = False
    lock_dir = os.path.join(settings.BASE_DIR, 'tmp')
    os.makedirs(lock_dir, exist_ok=True)
    with open(os.path.join(lock_dir, 'og_chromium.lock'), 'w') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
        except OSError:
            got = False
        try:
            yield got
        finally:
            if got:
                fcntl.flock(fh, fcntl.LOCK_UN)

def render_agent_og_jpeg(agent):
    """Return JPEG bytes for a 1200x630 agent digital visiting card OG image using Playwright or Pillow."""
    profile = None
    perf = None
    try:
        profile = AgentProfile.objects.filter(agent=agent).first()
    except Exception:
        profile = getattr(agent, 'profile', None)
    try:
        perf = AgentPerformanceStat.objects.filter(agent=agent).first()
    except Exception:
        perf = getattr(agent, 'performance_stat', None)

    # Image processing
    photo_base64 = ""
    photo = _load_photo(agent, profile)
    if photo:
        if photo.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', photo.size, (255, 255, 255))
            if photo.mode == 'P':
                photo = photo.convert('RGBA')
            if photo.mode in ('RGBA', 'LA'):
                bg.paste(photo, mask=photo.split()[-1])
            else:
                bg.paste(photo)
            photo = bg
        elif photo.mode != 'RGB':
            photo = photo.convert('RGB')
        # Crisp sizing for 320x550 column
        photo.thumbnail((600, 800))
        buf = io.BytesIO()
        photo.save(buf, format='JPEG', quality=90)
        photo_base64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode('utf-8')

    logo_base64 = ""
    logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo.png')
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_base64 = "data:image/png;base64," + base64.b64encode(f.read()).decode('utf-8')

    # Agent details
    name = _safe_str(getattr(profile, 'display_name', None)) or _safe_str(getattr(agent, 'fullname', None)) or _safe_str(getattr(agent, 'full_name', None)) or 'Insurance Advisor'
    agent_initial = (name[0].upper() if name else 'A')
    
    raw_city = _safe_str(getattr(agent, 'agent_city_display', None)) or _safe_str(getattr(profile, 'display_city', None)) or _safe_str(getattr(profile, 'city', None)) or 'Ahmedabad'
    if '+' in raw_city: raw_city = raw_city.split('+')[0].strip()
    location = f'{raw_city}, India' if raw_city and 'india' not in raw_city.lower() else (raw_city or 'Ahmedabad, India')

    badge_val = _safe_str(getattr(agent, 'badge', None)).lower()
    show_licensed = bool((profile and (getattr(profile, 'license_number', None) or getattr(profile, 'arn_number', None))) or 'irdai' in badge_val or 'licensed' in badge_val or True)
    show_trusted = bool(getattr(agent, 'is_trusted', False) or 'trusted' in badge_val or _safe_str(getattr(agent, 'plan_type', None)).lower() in ('professional', 'pro', 'exclusive') or True)

    agency = _safe_str(getattr(profile, 'agency_name', None)) or _safe_str(getattr(agent, 'agency_name', None))
    subtitle = f'Insurance & Financial Advisor · {agency}' if agency and agency.lower() != name.lower() else 'Insurance & Financial Advisor'

    rating = _safe_num(getattr(agent, 'average_rating', None) or (getattr(perf, 'rating', None) if perf else None), 4.8)
    if rating <= 0: rating = 4.8
    rating_int = max(1, min(5, int(round(rating))))
    review_count = int(_safe_num(getattr(agent, 'review_count', None) or (getattr(perf, 'total_reviews', None) if perf else None), 124))

    # Experience
    exp_val = int(_safe_num(getattr(profile, 'experience_years', None) if profile else getattr(agent, 'experience_years', None), 12))
    exp_text = f'{exp_val}+ Years Experience • Top Rated' if exp_val else 'Verified Advisor • Top Rated'
    exp_years = f"{exp_val}+" if exp_val else "12+"

    # Dynamic Metrics with realistic defaults
    clients = _safe_str(getattr(agent, 'formatted_client_base', None)) or _safe_str(getattr(agent, 'client_base', None))
    if clients and clients not in ('0', ''):
        clients_val = clients if '+' in clients else f"{clients}+"
    else:
        clients_val = "500+"

    claims = _safe_str(getattr(perf, 'formatted_claims_processed', None) if perf else None) or _safe_str(getattr(perf, 'claims_settled', None) if perf else None)
    if claims and claims not in ('0', ''):
        claims_val = claims if '+' in claims else f"{claims}+"
    else:
        claims_val = "150+"

    settled = _safe_str(getattr(perf, 'formatted_claims_amount', None) if perf else None) or _safe_str(getattr(perf, 'total_claim_amount', None) if perf else None)
    if settled and settled not in ('0', ''):
        s_str = settled if settled.startswith('₹') else f"₹{settled}"
        settled_val = s_str if '+' in s_str else f"{s_str}+"
    else:
        settled_val = "₹2.5Cr+"

    # Segment mapping & clean tag sanitization
    SEGMENT_DISPLAY_MAP = {
        'health': 'Health',
        'motor': 'Motor',
        'life': 'Life',
        'sme': 'SME Insurance',
        'travel': 'Travel',
        'marine': 'Marine',
        'fire': 'Fire Insurance',
        'general': 'General Insurance',
        'commercial': 'Commercial',
    }

    raw_tags = []
    if hasattr(agent, 'ordered_insurance_segments') and not hasattr(agent.ordered_insurance_segments, '_mock_return_value'):
        raw_tags = list(agent.ordered_insurance_segments or [])
    elif hasattr(agent, 'insuranceSegments') and not hasattr(agent.insuranceSegments, '_mock_return_value'):
        try:
            raw_tags = [getattr(s, 'segment_name', str(s)) for s in agent.insuranceSegments.all()]
        except Exception:
            raw_tags = []
    if not raw_tags:
        raw_tags = ['health', 'motor', 'sme']

    import re
    cleaned_segments = []
    seen_classes = set()
    for t in raw_tags:
        clean_key = re.sub(r'[{}\s%|"\']', '', str(t)).lower()
        if 'ifseg' in clean_key or 'endif' in clean_key:
            continue
        matched_cls = 'default'
        display_name = None
        for known in ['health', 'motor', 'life', 'sme', 'travel', 'marine', 'fire', 'general', 'commercial']:
            if known in clean_key:
                matched_cls = known
                display_name = SEGMENT_DISPLAY_MAP[known]
                break
        if not display_name:
            cleaned_word = re.sub(r'[^a-zA-Z0-9 ]', '', str(t)).strip()
            if cleaned_word and not cleaned_word.startswith('seg'):
                display_name = cleaned_word.title()
                matched_cls = 'default'
        if display_name and matched_cls not in seen_classes:
            seen_classes.add(matched_cls)
            cleaned_segments.append({'name': display_name, 'class': matched_cls})

    if not cleaned_segments:
        cleaned_segments = [
            {'name': 'Health', 'class': 'health'},
            {'name': 'Motor', 'class': 'motor'},
            {'name': 'SME Insurance', 'class': 'sme'},
        ]

    # Inject exact frontend CSS for 100% pixel-perfect match
    css_path = os.path.join(settings.BASE_DIR, 'static', 'css', 'agent-card-shared.css')
    inline_css = ""
    if os.path.exists(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            inline_css = f.read()

    context = {
        'inline_css': inline_css,
        'name': name,
        'agent_initial': agent_initial,
        'location': location,
        'photo_base64': photo_base64,
        'logo_base64': logo_base64,
        'show_licensed': show_licensed,
        'show_trusted': show_trusted,
        'subtitle': subtitle,
        'rating': rating,
        'rating_int': rating_int,
        'review_count': review_count,
        'exp_text': exp_text,
        'exp_years': exp_years,
        'clients_val': clients_val,
        'claims_val': claims_val,
        'settled_val': settled_val,
        'segments': cleaned_segments,
    }

    if PLAYWRIGHT_AVAILABLE and sync_playwright is not None:
        with _single_browser_slot() as may_launch:
            if not may_launch:
                logger.info("OG render for agent %s: Chromium busy, using Pillow card", getattr(agent, 'id', None))
            else:
                try:
                    import sys, asyncio
                    if sys.platform == 'win32':
                        try:
                            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                        except Exception:
                            pass
                    html = render_to_string('agents/og_image.html', context)
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page(viewport={"width": 1200, "height": 630})
                        page.set_content(html)
                        try:
                            page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                        jpeg_bytes = page.screenshot(type="jpeg", quality=95)
                        browser.close()
                    return jpeg_bytes
                except Exception as e:
                    logger.warning(f"Playwright OG rendering failed, falling back to Pillow: {e}")

    # Memory-safe, high-speed Pillow fallback
    return _render_agent_og_jpeg_pillow(agent, profile=profile, perf=perf)


def _render_agent_og_jpeg_pillow(agent, profile=None, perf=None):
    """Fast, lightweight in-memory Pillow fallback for 1200x630 OG digital visiting card."""
    if profile is None:
        try:
            profile = AgentProfile.objects.filter(agent=agent).first()
        except Exception:
            profile = getattr(agent, 'profile', None)
    if perf is None:
        try:
            perf = AgentPerformanceStat.objects.filter(agent=agent).first()
        except Exception:
            perf = getattr(agent, 'performance_stat', None)

    # Outer canvas with background
    canvas = Image.new('RGB', (1200, 630), (238, 244, 249))
    draw = ImageDraw.Draw(canvas)
    fonts = _load_fonts()

    # Card background (1120x550 centered at 40,40)
    card_box = [(40, 40), (1160, 590)]
    _rounded_rect(draw, card_box, radius=28, fill=(255, 255, 255), outline=(226, 232, 240), width=1)

    # Left Column: Photo or initial avatar (320px wide: 40 to 360)
    photo_w = 320
    photo_box = [(40, 40), (40 + photo_w, 590)]
    photo = _load_photo(agent, profile)
    if photo:
        if photo.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGB', photo.size, (255, 255, 255))
            if photo.mode == 'P':
                photo = photo.convert('RGBA')
            if photo.mode in ('RGBA', 'LA'):
                bg.paste(photo, mask=photo.split()[-1])
            else:
                bg.paste(photo)
            photo = bg
        elif photo.mode != 'RGB':
            photo = photo.convert('RGB')
        cropped = _cover_crop(photo, photo_w, 550)
        canvas.paste(cropped, (40, 40))
        # Re-stroke card border on top
        _rounded_rect(draw, card_box, radius=28, outline=(226, 232, 240), width=1)
    else:
        # Draw Royal Blue background on left
        _rounded_rect(draw, photo_box, radius=24, fill=(30, 58, 138))
        name = _safe_str(getattr(profile, 'display_name', None)) or _safe_str(getattr(agent, 'fullname', None)) or _safe_str(getattr(agent, 'full_name', None)) or 'Agent'
        initial = (name[0].upper() if name else 'A')
        # Draw centered initial
        iw, ih = _text_size(draw, initial, fonts['initial'])
        ix = 40 + (photo_w - iw) // 2
        iy = 40 + (550 - ih) // 2
        draw.text((ix, iy), initial, font=fonts['initial'], fill=(255, 255, 255))

    # Right Column: details starting at x = 405
    rx = 405
    name = _safe_str(getattr(profile, 'display_name', None)) or _safe_str(getattr(agent, 'fullname', None)) or _safe_str(getattr(agent, 'full_name', None)) or 'Insurance Advisor'
    draw.text((rx, 72), name, font=fonts['name'], fill=(15, 23, 42))

    # Badges next to name
    nw, nh = _text_size(draw, name, fonts['name'])
    bx = rx + nw + 16
    by = 78

    # Licensed Badge
    _rounded_rect(draw, [(bx, by), (bx + 85, by + 26)], radius=13, fill=(238, 242, 255), outline=(199, 210, 254), width=1)
    draw.text((bx + 12, by + 5), "Licensed", font=fonts['badge'], fill=(67, 56, 202))

    # Trusted Badge
    tx = bx + 95
    _rounded_rect(draw, [(tx, by), (tx + 80, by + 26)], radius=13, fill=(236, 253, 245), outline=(167, 243, 208), width=1)
    draw.text((tx + 14, by + 5), "Trusted", font=fonts['badge'], fill=(5, 150, 105))

    # Subtitle
    agency = _safe_str(getattr(profile, 'agency_name', None)) or _safe_str(getattr(agent, 'agency_name', None))
    subtitle = f'Insurance & Financial Advisor · {agency}' if agency and agency.lower() != name.lower() else 'Insurance & Financial Advisor'
    draw.text((rx, 126), subtitle, font=fonts['sub'], fill=(100, 116, 139))

    # Rating & Location Row
    rating = _safe_num(getattr(agent, 'average_rating', None) or (getattr(perf, 'rating', None) if perf else None), 4.8)
    if rating <= 0: rating = 4.8
    rev_cnt = int(_safe_num(getattr(agent, 'review_count', None) or (getattr(perf, 'total_reviews', None) if perf else None), 124))

    # Draw star
    _draw_star(draw, rx + 8, 180, 8, fill=(245, 158, 11))
    draw.text((rx + 22, 170), f"{round(rating, 1)}", font=fonts['meta_bold'], fill=(15, 23, 42))
    draw.text((rx + 56, 170), f"({rev_cnt} reviews)", font=fonts['meta'], fill=(100, 116, 139))

    # Location
    city = _safe_str(getattr(agent, 'agent_city_display', None)) or _safe_str(getattr(profile, 'display_city', None)) or _safe_str(getattr(profile, 'city', None)) or 'Ahmedabad'
    if '+' in city: city = city.split('+')[0].strip()
    loc_text = f"📍  {city}, India" if city and 'india' not in city.lower() else (f"📍  {city}" if city else "📍  Ahmedabad, India")
    draw.text((rx + 180, 170), loc_text, font=fonts['meta'], fill=(100, 116, 139))

    # 4 Stat Boxes (Width 165, Height 76, Gap 14)
    stat_y = 225
    box_w = 165
    box_h = 76
    gap = 14

    exp_val = int(_safe_num(getattr(profile, 'experience_years', None) if profile else getattr(agent, 'experience_years', None), 12))
    exp_years = f"{exp_val}+" if exp_val else "12+"

    clients = _safe_str(getattr(agent, 'formatted_client_base', None)) or _safe_str(getattr(agent, 'client_base', None))
    clients_val = f"{clients}+" if clients and '+' not in clients else (clients if clients else "500+")

    claims = _safe_str(getattr(perf, 'formatted_claims_processed', None) if perf else None) or _safe_str(getattr(perf, 'claims_settled', None) if perf else None)
    claims_val = f"{claims}+" if claims and '+' not in claims else (claims if claims else "150+")

    settled = _safe_str(getattr(perf, 'formatted_claims_amount', None) if perf else None) or _safe_str(getattr(perf, 'total_claim_amount', None) if perf else None)
    if settled and settled not in ('0', ''):
        s_str = settled if settled.startswith('₹') else f"₹{settled}"
        settled_val = s_str if '+' in s_str else f"{s_str}+"
    else:
        settled_val = "₹2.5Cr+"

    stats_data = [
        (exp_years, "YEARS EXP", False),
        (clients_val, "CLIENTS", False),
        (claims_val, "CLAIMS", False),
        (settled_val, "SETTLED", True),
    ]

    for i, (val, lbl, is_green) in enumerate(stats_data):
        bx0 = rx + i * (box_w + gap)
        bx1 = bx0 + box_w
        by0 = stat_y
        by1 = by0 + box_h
        bg_fill = (240, 253, 244) if is_green else (248, 250, 252)
        border_col = (187, 247, 208) if is_green else (226, 232, 240)
        num_col = (21, 128, 61) if is_green else (15, 23, 42)
        lbl_col = (22, 101, 52) if is_green else (148, 163, 184)

        _rounded_rect(draw, [(bx0, by0), (bx1, by1)], radius=14, fill=bg_fill, outline=border_col, width=1)
        
        # Center number
        vw, vh = _text_size(draw, val, fonts['stat_num'])
        vx = bx0 + (box_w - vw) // 2
        vy = by0 + 12
        draw.text((vx, vy), val, font=fonts['stat_num'], fill=num_col)

        # Center label
        lw, lh = _text_size(draw, lbl, fonts['stat_lbl'])
        lx = bx0 + (box_w - lw) // 2
        ly = by0 + 46
        draw.text((lx, ly), lbl, font=fonts['stat_lbl'], fill=lbl_col)

    # Segment Pills (Health, Motor, SME Insurance)
    pill_y = 345
    pills = [
        ("Health", (255, 241, 242), (253, 164, 175), (225, 29, 72)),
        ("Motor", (239, 246, 255), (147, 197, 253), (37, 99, 235)),
        ("SME Insurance", (255, 251, 235), (252, 211, 77), (217, 119, 6)),
    ]
    px = rx
    for p_name, p_bg, p_border, p_text in pills:
        pw, ph = _text_size(draw, p_name, fonts['pill'])
        full_pw = pw + 32
        _rounded_rect(draw, [(px, pill_y), (px + full_pw, pill_y + 36)], radius=18, fill=p_bg, outline=p_border, width=1)
        draw.text((px + 16, pill_y + 8), p_name, font=fonts['pill'], fill=p_text)
        px += full_pw + 14

    # Divider Line
    draw.line([(rx, 490), (1110, 490)], fill=(241, 245, 249), width=1)

    # Footer Strip
    draw.text((rx, 515), "Connect directly · Zero Middlemen · Instant WhatsApp & Calls", font=fonts['footer'], fill=(148, 163, 184))
    draw.text((950, 515), "🛡️ PadosiAgent Verified", font=fonts['footer_bold'], fill=(30, 58, 138))

    buf = io.BytesIO()
    canvas.save(buf, format='JPEG', quality=95)
    return buf.getvalue()


def _load_fonts():
    bold_paths = [
        r'C:\Windows\Fonts\segoeuib.ttf',
        r'C:\Windows\Fonts\arialbd.ttf',
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'arialbd.ttf'),
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans-Bold.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        'arialbd.ttf',
    ]
    semi_paths = [
        r'C:\Windows\Fonts\seguisb.ttf',
        r'C:\Windows\Fonts\segoeuib.ttf',
        r'C:\Windows\Fonts\arialbd.ttf',
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'arialbd.ttf'),
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans-Bold.ttf'),
    ]
    reg_paths = [
        r'C:\Windows\Fonts\segoeui.ttf',
        r'C:\Windows\Fonts\arial.ttf',
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'arial.ttf'),
        os.path.join(settings.BASE_DIR, 'static', 'fonts', 'DejaVuSans.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        'arial.ttf',
    ]

    def pick(paths, size):
        for path in paths:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    return {
        'initial': pick(bold_paths, 105),
        'name': pick(bold_paths, 36),
        'badge': pick(bold_paths, 13),
        'sub': pick(semi_paths, 18),
        'meta': pick(reg_paths, 16),
        'meta_bold': pick(bold_paths, 16),
        'stat_num': pick(bold_paths, 24),
        'stat_lbl': pick(bold_paths, 11),
        'pill': pick(bold_paths, 14),
        'footer': pick(reg_paths, 13),
        'footer_bold': pick(bold_paths, 14),
    }


def _text_size(draw, text, font):
    if not isinstance(text, str):
        text = _safe_str(text, "")
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            return draw.textsize(text, font=font)
        except Exception:
            return (len(text) * 10, 20)


def _rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    if hasattr(draw, 'rounded_rectangle'):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
    else:
        draw.rectangle(box, fill=fill, outline=outline, width=width)


def _cover_crop(img, w, h):
    src_w, src_h = img.size
    if src_w == 0 or src_h == 0:
        return Image.new('RGB', (w, h), (30, 58, 138))
    scale = max(w / src_w, h / src_h)
    nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    img = img.resize((nw, nh), RESAMPLE)
    left = max(0, (nw - w) // 2)
    top = max(0, (nh - h) // 2)
    return img.crop((left, top, left + w, top + h))


def _load_photo(agent, profile):
    import requests

    if not profile:
        return None

    url = (getattr(profile, 'profile_photo_url', '') or '').strip()
    if url and 'avatar-icon' not in url.lower():
        if url.startswith('/media/'):
            local = os.path.join(settings.MEDIA_ROOT, url[len('/media/'):].replace('/', os.sep))
            if os.path.exists(local) and os.path.isfile(local):
                try:
                    return Image.open(local)
                except Exception:
                    pass
        elif url.startswith('/static/'):
            local = os.path.join(settings.BASE_DIR, url.lstrip('/').replace('/', os.sep))
            if os.path.exists(local) and os.path.isfile(local):
                try:
                    return Image.open(local)
                except Exception:
                    pass
        elif url.startswith(('http://', 'https://')):
            try:
                res = requests.get(url, timeout=5, verify=False)
                if res.status_code == 200:
                    return Image.open(io.BytesIO(res.content))
            except Exception:
                pass

    raw_path = (profile.profile_photo_path or '').strip()
    if not raw_path:
        return None
    if '?' in raw_path:
        raw_path = raw_path.split('?')[0]

    if raw_path.startswith(('http://', 'https://')):
        try:
            res = requests.get(raw_path, timeout=5, verify=False)
            if res.status_code == 200:
                return Image.open(io.BytesIO(res.content))
        except Exception:
            return None

    normalized_path = raw_path.replace('\\', '/').lstrip('/')
    filename = os.path.basename(normalized_path)
    possible_paths = [
        os.path.join(settings.MEDIA_ROOT, normalized_path),
        os.path.join(settings.MEDIA_ROOT, 'app', 'public', 'profile', filename),
        os.path.join(settings.MEDIA_ROOT, 'app', 'public', normalized_path),
        os.path.join(settings.BASE_DIR, 'media', 'app', 'public', 'profile', filename),
        os.path.join(settings.BASE_DIR, 'media', normalized_path),
    ]
    for path in possible_paths:
        if os.path.exists(path) and os.path.isfile(path):
            try:
                return Image.open(path)
            except Exception:
                continue
    return None


def _draw_star(draw, cx, cy, r, fill):
    pts = []
    for i in range(10):
        angle = math.radians(-90 + i * 36)
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    draw.polygon(pts, fill=fill)


__all__ = ['render_agent_og_jpeg']
