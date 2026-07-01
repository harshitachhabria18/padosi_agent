from django import template
from django.utils.html import escape
from apps.home.models.site_setting import SiteSetting

register = template.Library()


@register.inclusion_tag('components/hero-section.html', takes_context=True)
def hero_section(context):
    hero_defaults = {
        'heading': 'Find a {Trusted} Insurance Expert in your {Padosi}',
        'trust_badges': [
            {'icon': 'check-circle', 'label': 'Licensed'},
            {'icon': 'shield',       'label': 'No Spam Calls'},
            {'icon': 'trending-up',  'label': 'Zero Platform Fee'},
        ],
        'stats': [
            {'label': 'Expert Agents', 'target': 1000, 'suffix': '+', 'icon': 'users', 'large': True, 'decimal': False},
            {'label': 'Cities Covered', 'target': 50, 'suffix': '+', 'icon': 'map-pin', 'large': False, 'decimal': False},
            {'label': 'Rating', 'target': 4.8, 'suffix': '', 'icon': 'star', 'large': False, 'decimal': True},
            {'label': 'Families Covered', 'target': 1, 'suffix': 'L+', 'icon': 'heart', 'large': False, 'decimal': False},
        ],
        'tiles': [
            {'label': 'Health Insurance', 'icon': 'heart', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Health+Insurance&openFilter=1', 'tileClass': 'pa-tile-rose'},
            {'label': 'Life Insurance', 'icon': 'shield', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Life+Insurance&openFilter=1', 'tileClass': 'pa-tile-sky'},
            {'label': 'Vehicle Insurance', 'icon': 'car', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Motor+Insurance&openFilter=1', 'tileClass': 'pa-tile-amber'},
            {'label': 'Business Insurance', 'icon': 'building-2', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=SME+Insurance&openFilter=1', 'tileClass': 'pa-tile-violet'},
        ],
        'slides': [
            {'icon': 'indian-rupee', 'hero': '₹25,00,000 Cr', 'tag': 'Unclaimed Insurance', 'body': "Most families miss out because they don't have an agent.", 'isChart': False},
            {'icon': 'users', 'hero': 'Agent > Chatbot', 'tag': 'Real Support Matters', 'body': 'Cheap product or hassle-free service? Agents deliver both.', 'isChart': False},
            {'icon': 'trending-up', 'hero': 'Claim Rejections +34%', 'tag': 'As Online Sales Grow', 'body': '', 'isChart': True},
            {'icon': 'badge-percent', 'hero': 'Save 20-40%', 'tag': 'Better Premiums', 'body': "Agents find coverage algorithms can't.", 'isChart': False},
            {'icon': 'clock', 'hero': 'Claims 2x Faster', 'tag': 'With an Agent', 'body': 'No IVR loops. Real human follow-through.', 'isChart': False},
            {'icon': 'shield-check', 'hero': '9/10 Approved', 'tag': 'Agent-Backed Claims', 'body': 'Insurers settle 3x more with agent support.', 'isChart': False},
            {'icon': 'users', 'hero': '1,000+ Agents', 'tag': 'In Your City', 'body': 'Your neighbour is already an agent. Meet face-to-face.', 'isChart': False},
        ],
        'cta_claim_text': 'Insurance Claims Support',
        'cta_claim_url': '/find-agents?ServiceType=Claim%20Assistance&openFilter=1',
        'cta_review_text': 'Insurance Audit',
        'cta_review_url': '/find-agents?ServiceType=Policy%20Review&openFilter=1',
        'claims_card_label': 'FIND INSURANCE EXPERTS NEAR ME FOR:',
        'claims_card_heading': 'Claims, audits and policy review with local advisors',
        'claims_card_text': 'Easy local guidance from verified agents, with real advisor stories and trusted help just a few minutes away.',
    }

    hero_db = SiteSetting.get_value('hero_section', {})
    hero = {**hero_defaults, **(hero_db if isinstance(hero_db, dict) else {})}

    trust_badges = hero.get('trust_badges') or hero_defaults['trust_badges']
    stats_data = hero.get('stats') or hero_defaults['stats']
    product_tiles = hero.get('tiles') or hero_defaults['tiles']
    facts = hero.get('slides') or hero_defaults['slides']

    for s in stats_data:
        s['large'] = str(s.get('large', False)).lower() in ('true', '1')
        s['decimal'] = str(s.get('decimal', False)).lower() in ('true', '1')
        try:
            s['target'] = float(s.get('target', 0))
        except (ValueError, TypeError):
            s['target'] = 0.0

    for f in facts:
        f['isChart'] = str(f.get('isChart', False)).lower() in ('true', '1')

    chart_data = [
        {'year': '2020', 'rejection': 12},
        {'year': '2021', 'rejection': 16},
        {'year': '2022', 'rejection': 21},
        {'year': '2023', 'rejection': 27},
        {'year': '2024', 'rejection': 34},
    ]

    slide_gradients = [
        'linear-gradient(135deg, hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.25), hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.1), hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.05))',
        'linear-gradient(135deg, hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.25), hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.1), hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.05))',
        'linear-gradient(135deg, hsla(0, 72%, 51%, 0.25), hsla(0, 72%, 51%, 0.1), hsla(0, 72%, 51%, 0.05))',
        'linear-gradient(135deg, hsla(38, 92%, 50%, 0.25), hsla(38, 92%, 50%, 0.1), hsla(38, 92%, 50%, 0.05))',
        'linear-gradient(135deg, hsla(173, 80%, 36%, 0.25), hsla(173, 80%, 36%, 0.1), hsla(173, 80%, 36%, 0.05))',
        'linear-gradient(135deg, hsla(160, 84%, 39%, 0.25), hsla(160, 84%, 39%, 0.1), hsla(160, 84%, 39%, 0.05))',
        'linear-gradient(135deg, hsla(262, 83%, 58%, 0.25), hsla(262, 83%, 58%, 0.1), hsla(262, 83%, 58%, 0.05))',
    ]

    slide_icon_shadows = [
        '0 10px 15px -3px hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.2), 0 4px 6px -4px hsla(var(--pa-primary-h), var(--pa-primary-s), var(--pa-primary-l), 0.2)',
        '0 10px 15px -3px hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.2), 0 4px 6px -4px hsla(var(--pa-secondary-h), var(--pa-secondary-s), var(--pa-secondary-l), 0.2)',
        '0 10px 15px -3px hsla(0, 72%, 51%, 0.2), 0 4px 6px -4px hsla(0, 72%, 51%, 0.2)',
        '0 10px 15px -3px hsla(38, 92%, 50%, 0.2), 0 4px 6px -4px hsla(38, 92%, 50%, 0.2)',
        '0 10px 15px -3px hsla(173, 80%, 36%, 0.2), 0 4px 6px -4px hsla(173, 80%, 36%, 0.2)',
        '0 10px 15px -3px hsla(160, 84%, 39%, 0.2), 0 4px 6px -4px hsla(160, 84%, 39%, 0.2)',
        '0 10px 15px -3px hsla(262, 83%, 58%, 0.2), 0 4px 6px -4px hsla(262, 83%, 58%, 0.2)',
    ]

    slides_zipped = []
    for idx, f in enumerate(facts):
        slides_zipped.append({
            'fact': f,
            'gradient': slide_gradients[idx % len(slide_gradients)],
            'shadow': slide_icon_shadows[idx % len(slide_icon_shadows)],
            'index': idx
        })

    hero_heading = hero.get('heading') or hero_defaults['heading']
    escaped_heading = escape(hero_heading)
    formatted_heading = escaped_heading.replace('{Trusted}', '<span class="pa-heading-trusted">Trusted</span>')
    formatted_heading = formatted_heading.replace('{Licensed}', '<span class="pa-heading-trusted">Licensed</span>')
    formatted_heading = formatted_heading.replace('{Padosi}', '<span class="pa-heading-highlight">Padosi</span>')

    return {
        'trust_badges': trust_badges,
        'stats_data': stats_data,
        'product_tiles': product_tiles,
        'slides_zipped': slides_zipped,
        'chart_data': chart_data,
        'formatted_heading': formatted_heading,
        'hero': hero,
        'slides_count': len(facts),
        'hide_header': context.get('hide_header', True),
    }
