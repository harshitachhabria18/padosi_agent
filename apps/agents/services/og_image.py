"""Generate WhatsApp / Open Graph share cards that match the public agent card."""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

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


def render_agent_og_jpeg(agent):
    """Return JPEG bytes for a 1200x630 agent-card style OG image."""
    width, height = 1200, 630
    canvas = Image.new('RGB', (width, height), (241, 245, 249))
    draw = ImageDraw.Draw(canvas)

    card = (36, 48, 1164, 582)
    _rounded_rect(draw, (card[0] + 6, card[1] + 8, card[2] + 6, card[3] + 8), 28, fill=(203, 213, 225))
    _rounded_rect(draw, card, 28, fill=(255, 255, 255), outline=(226, 232, 240), width=2)

    profile = AgentProfile.objects.filter(agent=agent).first()
    perf = AgentPerformanceStat.objects.filter(agent=agent).first()
    fonts = _load_fonts()

    photo_w = 392
    photo_box = (card[0], card[1], card[0] + photo_w, card[3])
    _paste_profile_photo(canvas, agent, profile, photo_box)

    content_x = photo_box[2] + 36
    content_right = card[2] - 32
    y = card[1] + 36

    display_name = ((profile.display_name if profile else '') or agent.fullname or 'Agent').strip()
    if len(display_name) > 28:
        name_font = fonts['name_sm']
    else:
        name_font = fonts['name']
    draw.text((content_x, y), display_name, font=name_font, fill=(15, 23, 42))

    name_w = _text_size(draw, display_name, name_font)[0]
    badge_x = content_x + name_w + 14
    badge_y = y + 10
    if badge_x > content_right - 90:
        badge_x = content_x
        badge_y = y + 58
        y += 30
    _draw_status_badges(draw, agent, profile, fonts['pill'], badge_x, badge_y, content_right)
    y += 62

    _draw_stars_and_rating(draw, agent, fonts, content_x, y)
    y += 52

    metrics = _metric_values(agent, profile, perf)
    _draw_metric_boxes(draw, fonts, metrics, content_x, y, content_right)
    _draw_tags(draw, fonts['tag'], list(getattr(agent, 'ordered_insurance_segments', None) or [])[:4], content_x, card[3] - 78)

    buffer = io.BytesIO()
    canvas.save(buffer, format='JPEG', quality=92)
    return buffer.getvalue()


def _load_fonts():
    bold_paths = [
        r'C:\Windows\Fonts\segoeuib.ttf',
        r'C:\Windows\Fonts\arialbd.ttf',
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'static', 'fonts', 'arialbd.ttf'),
        'arialbd.ttf',
    ]
    reg_paths = [
        r'C:\Windows\Fonts\segoeui.ttf',
        r'C:\Windows\Fonts\arial.ttf',
        os.path.join(os.path.dirname(__file__), '..', '..', '..', 'static', 'fonts', 'arial.ttf'),
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
        'name': pick(bold_paths, 48),
        'name_sm': pick(bold_paths, 36),
        'pill': pick(bold_paths, 15),
        'rating': pick(bold_paths, 22),
        'reviews': pick(reg_paths, 18),
        'val': pick(bold_paths, 28),
        'label': pick(bold_paths, 13),
        'tag': pick(bold_paths, 16),
    }


def _text_size(draw, text, font):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        return draw.textsize(text, font=font)


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
    from django.conf import settings

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
    cleaned_path = normalized_path
    for prefix in ['app/public/', 'public/storage/', 'public/', 'storage/', 'agent/profiles/']:
        if cleaned_path.startswith(prefix):
            cleaned_path = cleaned_path[len(prefix):]
            break
    possible_paths.append(os.path.join(settings.MEDIA_ROOT, cleaned_path))
    possible_paths.append(os.path.abspath(os.path.join(settings.BASE_DIR, '..', 'storage', 'app', 'public', cleaned_path)))
    for path in possible_paths:
        if os.path.exists(path) and os.path.isfile(path):
            try:
                return Image.open(path)
            except Exception:
                continue
    return None


def _paste_profile_photo(canvas, agent, profile, box):
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    src = _load_photo(agent, profile)
    if src is not None:
        try:
            if src.mode not in ('RGB', 'RGBA'):
                src = src.convert('RGB')
            fitted = _cover_crop(src.convert('RGB'), w, h)
        except Exception:
            fitted = None
    else:
        fitted = None

    if fitted is None:
        fitted = Image.new('RGB', (w, h), (30, 58, 138))
        d = ImageDraw.Draw(fitted)
        name_str = ((profile.display_name if profile else '') or agent.fullname or 'A').strip()
        initial = name_str[0].upper() if name_str else 'A'
        font = _load_fonts()['name']
        tw, th = _text_size(d, initial, font)
        d.text(((w - tw) / 2, (h - th) / 2 - 8), initial, font=font, fill=(255, 255, 255))

    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    _rounded_rect(md, (0, 0, w, h), 26, fill=255)
    md.rectangle((w - 40, 0, w, h), fill=255)
    canvas.paste(fitted, (x0, y0), mask=mask)


def _draw_status_badges(draw, agent, profile, font, x, y, max_x):
    badge_val = (getattr(agent, 'badge', '') or '').lower()
    show_licensed = bool(
        (profile and (profile.license_number or profile.arn_number))
        or 'irdai' in badge_val
        or 'licensed' in badge_val
    )
    show_trusted = bool(
        getattr(agent, 'is_trusted', False)
        or 'trusted' in badge_val
        or str(getattr(agent, 'plan_type', '') or '').lower() in ('professional', 'pro', 'exclusive')
    )
    badges = []
    if show_licensed:
        badges.append(('Licensed', (239, 246, 255), (29, 78, 216), (191, 219, 254)))
    if show_trusted:
        badges.append(('Trusted', (240, 253, 244), (22, 163, 74), (187, 247, 208)))

    for label, bg, fg, border in badges:
        tw, th = _text_size(draw, label, font)
        bw = tw + 28
        if x + bw > max_x:
            break
        _rounded_rect(draw, (x, y, x + bw, y + 28), 14, fill=bg, outline=border, width=1)
        draw.text((x + 14, y + 5), label, font=font, fill=fg)
        x += bw + 8
    return x


def _draw_star(draw, cx, cy, r, fill):
    pts = []
    for i in range(10):
        angle = math.radians(-90 + i * 36)
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(angle), cy + rad * math.sin(angle)))
    draw.polygon(pts, fill=fill)


def _draw_stars_and_rating(draw, agent, fonts, x, y):
    rating = float(agent.average_rating or 0)
    if rating <= 0:
        rating = 5.0
    review_count = int(agent.review_count or 0)
    full = int(round(rating))
    full = max(0, min(5, full))
    for i in range(5):
        cx = x + 12 + i * 26
        _draw_star(draw, cx, y + 12, 11, (245, 158, 11) if i < full else (229, 231, 235))

    rating_text = f'{rating:.1f}'
    rx = x + 142
    draw.text((rx, y + 2), rating_text, font=fonts['rating'], fill=(15, 23, 42))
    rw = _text_size(draw, rating_text, fonts['rating'])[0]
    count_label = f'({review_count} reviews)' if review_count else '(Verified)'
    draw.text((rx + rw + 8, y + 5), count_label, font=fonts['reviews'], fill=(107, 114, 128))


def _metric_values(agent, profile, perf):
    exp = 0
    if profile and profile.experience_years:
        exp = profile.experience_years
    else:
        exp = getattr(agent, 'experience_years', 0) or 0
    clients = getattr(agent, 'formatted_client_base', None) or str(getattr(agent, 'client_base', '') or '0')
    claims = perf.formatted_claims_processed if perf else '0'
    settled = perf.formatted_claims_amount if perf else '0'
    return [
        (f'{exp}+' if exp else '1+', 'YEARS'),
        (str(clients or '0'), 'CLIENTS'),
        (str(claims or '0'), 'CLAIMS'),
        (f'₹{settled}', 'SETTLED'),
    ]


def _draw_metric_boxes(draw, fonts, metrics, x, y, right):
    gap = 12
    count = max(1, len(metrics))
    box_w = int((right - x - gap * (count - 1)) / count)
    box_h = 102
    for i, (value, label) in enumerate(metrics):
        bx = x + i * (box_w + gap)
        _rounded_rect(draw, (bx, y, bx + box_w, y + box_h), 12, fill=(255, 255, 255), outline=(226, 232, 240), width=1)
        vw, _ = _text_size(draw, value, fonts['val'])
        lw, _ = _text_size(draw, label, fonts['label'])
        draw.text((bx + (box_w - vw) / 2, y + 22), value, font=fonts['val'], fill=(15, 23, 42))
        draw.text((bx + (box_w - lw) / 2, y + 64), label, font=fonts['label'], fill=(100, 116, 139))


def _draw_tags(draw, font, tags, x, y):
    cursor = x
    for raw in tags:
        key = str(raw or '').strip().lower()
        if not key:
            continue
        label = 'SME' if key == 'sme' else key.capitalize()
        bg, fg, border = TAG_COLORS.get(key, TAG_DEFAULT)
        tw, _ = _text_size(draw, label, font)
        bw = tw + 28
        _rounded_rect(draw, (cursor, y, cursor + bw, y + 32), 16, fill=bg, outline=border, width=2)
        draw.text((cursor + 14, y + 6), label, font=font, fill=fg)
        cursor += bw + 10


__all__ = ['render_agent_og_jpeg']
