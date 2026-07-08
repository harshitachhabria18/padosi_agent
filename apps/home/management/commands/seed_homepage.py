from django.core.management.base import BaseCommand
from apps.home.models.homepage import (
    HomePageSettings, HeroTrustBadge, HeroStatistic, HeroProductTile,
    HeroSlide, DidYouKnowSlide, QuickPickItem, WhyChooseCard, HowItWorksStep
)

class Command(BaseCommand):
    help = 'Seeds the homepage with default content migrated from the PHP project.'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding homepage settings...')
        
        # 1. HomePageSettings
        settings, _ = HomePageSettings.objects.get_or_create(pk=1)
        settings.hero_heading = 'Find a {Trusted} Insurance Expert in your {Padosi}'
        settings.save()
        
        # 2. HeroTrustBadge
        HeroTrustBadge.objects.all().delete()
        trust_badges = [
            {'icon': 'check-circle', 'label': 'Licensed', 'order': 1},
            {'icon': 'shield', 'label': 'No Spam Calls', 'order': 2},
            {'icon': 'trending-up', 'label': 'Zero Platform Fee', 'order': 3},
        ]
        for badge in trust_badges:
            HeroTrustBadge.objects.create(**badge)
            
        # 3. HeroStatistic
        HeroStatistic.objects.all().delete()
        stats = [
            {'label': 'Expert Agents', 'target': 1000, 'suffix': '+', 'icon': 'users', 'is_large': True, 'is_decimal': False, 'order': 1},
            {'label': 'Cities Covered', 'target': 50, 'suffix': '+', 'icon': 'map-pin', 'is_large': False, 'is_decimal': False, 'order': 2},
            {'label': 'Rating', 'target': 4.8, 'suffix': '', 'icon': 'star', 'is_large': False, 'is_decimal': True, 'order': 3},
            {'label': 'Families Covered', 'target': 1, 'suffix': 'L+', 'icon': 'heart', 'is_large': False, 'is_decimal': False, 'order': 4},
        ]
        for stat in stats:
            HeroStatistic.objects.create(**stat)
            
        # 4. HeroProductTile
        HeroProductTile.objects.all().delete()
        tiles = [
            {'label': 'Health Insurance', 'icon': 'heart', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Health+Insurance&openFilter=1', 'css_class': 'pa-tile-rose', 'order': 1},
            {'label': 'Life Insurance', 'icon': 'shield', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Life+Insurance&openFilter=1', 'css_class': 'pa-tile-sky', 'order': 2},
            {'label': 'Vehicle Insurance', 'icon': 'car', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=Motor+Insurance&openFilter=1', 'css_class': 'pa-tile-amber', 'order': 3},
            {'label': 'Business Insurance', 'icon': 'building-2', 'url': '/find-agents?ServiceType=New+Policy&InsuranceType=SME+Insurance&openFilter=1', 'css_class': 'pa-tile-violet', 'order': 4},
        ]
        for tile in tiles:
            HeroProductTile.objects.create(**tile)
            
        # 5. HeroSlide
        HeroSlide.objects.all().delete()
        slides = [
            {'icon': 'indian-rupee', 'hero_text': '₹25,000 Cr', 'tag': 'Unclaimed Insurance', 'body': "Most families miss out because they don't have an agent.", 'is_chart': False, 'order': 1},
            {'icon': 'users', 'hero_text': 'Agent > Chatbot', 'tag': 'Real Support Matters', 'body': 'Cheap product or hassle-free service? Agents deliver both.', 'is_chart': False, 'order': 2},
            {'icon': 'trending-up', 'hero_text': 'Claim Rejections +34%', 'tag': 'As Online Sales Grow', 'body': '', 'is_chart': True, 'order': 3},
            {'icon': 'badge-percent', 'hero_text': 'Save 20-40%', 'tag': 'Better Premiums', 'body': "Agents find coverage algorithms can't.", 'is_chart': False, 'order': 4},
            {'icon': 'clock', 'hero_text': 'Claims 2x Faster', 'tag': 'With an Agent', 'body': 'No IVR loops. Real human follow-through.', 'is_chart': False, 'order': 5},
            {'icon': 'shield-check', 'hero_text': '9/10 Approved', 'tag': 'Agent-Backed Claims', 'body': 'Insurers settle 3x more with agent support.', 'is_chart': False, 'order': 6},
            {'icon': 'users', 'hero_text': '1,000+ Agents', 'tag': 'In Your City', 'body': 'Your neighbour is already an agent. Meet face-to-face.', 'is_chart': False, 'order': 7},
        ]
        for slide in slides:
            HeroSlide.objects.create(**slide)
            
        # 6. DidYouKnowSlide
        DidYouKnowSlide.objects.all().delete()
        dyk_slides = [
            {'accent_class': 'accent-rose', 'bg_class': 'bg-rose-500', 'icon': 'users', 'title': '3× faster claim settlements', 'body': 'Customers served by a nearby agent report claims clearing up to 3× faster — your agent walks the file through with the insurer.', 'order': 1},
            {'accent_class': 'accent-emerald', 'bg_class': 'bg-emerald-500', 'icon': 'shield', 'title': 'Local agents catch policy gaps', 'body': 'A neighbourhood expert knows your city\'s hospital network, traffic risks and weather patterns — and recommends covers a tele-caller never will.', 'order': 2},
            {'accent_class': 'accent-sky', 'bg_class': 'bg-sky-500', 'icon': 'clock', 'title': 'Face-to-face saves hours of confusion', 'body': '70%+ of policyholders say they understood their cover only after meeting an agent in person. Jargon disappears across a table.', 'order': 3},
            {'accent_class': 'accent-amber', 'bg_class': 'bg-amber-500', 'icon': 'trending-up', 'title': '40% lower lapse rates', 'body': 'Customers with a dedicated nearby agent are 40% less likely to let a policy lapse — they get timely renewal nudges from a real human.', 'order': 4},
            {'accent_class': 'accent-violet', 'bg_class': 'bg-violet-500', 'icon': 'lightbulb', 'title': 'Zero platform fee, full licensed advice', 'body': 'Your agent earns from the insurer — not from you. Same premium, lifetime advisor in your neighbourhood.', 'order': 5},
            {'accent_class': 'accent-pink', 'bg_class': 'bg-pink-500', 'icon': 'heart', 'title': 'Lifetime relationship, not a ticket number', 'body': 'Your Padosi agent stays the same across renewals, claims and family additions — no fresh call-centre script each time.', 'order': 6},
            {'accent_class': 'accent-indigo', 'bg_class': 'bg-indigo-500', 'icon': 'building-2', 'title': 'Hospital networks matter locally', 'body': 'A local agent maps the right cashless hospitals near your home and office before you ever need one.', 'order': 7},
            {'accent_class': 'accent-teal', 'bg_class': 'bg-teal-500', 'icon': 'indian-rupee', 'title': 'Right cover, not the costliest cover', 'body': 'A neighbourhood advisor sizes the premium to your real life — not to a target sheet.', 'order': 8},
        ]
        for dyk in dyk_slides:
            DidYouKnowSlide.objects.create(**dyk)
            
        # 7. QuickPickItem
        QuickPickItem.objects.all().delete()
        quick_picks = [
            {'label': 'Mediclaim', 'badge_text': 'Most Bought', 'badge_bg_color': '#ffe4e6', 'badge_text_color': '#be123c', 'icon_bg_color': '#fff1f2', 'icon_color': '#f43f5e', 'icon': 'heart-pulse', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Mediclaim&openFilter=1', 'order': 1},
            {'label': 'Term Plan', 'badge_text': 'Pure Cover', 'badge_bg_color': '#e0f2fe', 'badge_text_color': '#0369a1', 'icon_bg_color': '#f0f9ff', 'icon_color': '#0284c7', 'icon': 'clock', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Term%20Plan&openFilter=1', 'order': 2},
            {'label': 'Private Car', 'badge_text': 'Renew Fast', 'badge_bg_color': '#fef3c7', 'badge_text_color': '#b45309', 'icon_bg_color': '#fffbeb', 'icon_color': '#d97706', 'icon': 'car-front', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Private%20Car&openFilter=1', 'order': 3},
            {'label': 'Two Wheeler', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#ecfdf5', 'icon_color': '#059669', 'icon': 'bike', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Two%20Wheeler&openFilter=1', 'order': 4},
            {'label': 'Critical Illness', 'badge_text': 'Lumpsum', 'badge_bg_color': '#fae8ff', 'badge_text_color': '#a21caf', 'icon_bg_color': '#fdf4ff', 'icon_color': '#c026d3', 'icon': 'alert-triangle', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Critical%20Illness&openFilter=1', 'order': 5},
            {'label': 'Personal Accident', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#fff7ed', 'icon_color': '#ea580c', 'icon': 'user-check', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Personal%20Accident&openFilter=1', 'order': 6},
            {'label': 'Super Top-up', 'badge_text': 'Save Big', 'badge_bg_color': '#ccfbf1', 'badge_text_color': '#0f766e', 'icon_bg_color': '#f0fdfa', 'icon_color': '#0d9488', 'icon': 'trending-up', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Health%20Insurance&InsuranceCompany=Super%20Top-up&openFilter=1', 'order': 7},
            {'label': 'ULIP Plan', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#f5f3ff', 'icon_color': '#7c3aed', 'icon': 'bar-chart-3', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=ULIP%20Plan&openFilter=1', 'order': 8},
            {'label': 'Pension Plan', 'badge_text': 'Lifetime', 'badge_bg_color': '#e0e7ff', 'badge_text_color': '#4338ca', 'icon_bg_color': '#eef2ff', 'icon_color': '#4f46e5', 'icon': 'landmark', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Pension%20Plan&openFilter=1', 'order': 9},
            {'label': 'Saving Plan', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#fdf2f8', 'icon_color': '#db2777', 'icon': 'piggy-bank', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Life%20Insurance&InsuranceCompany=Saving%20Plan&openFilter=1', 'order': 10},
            {'label': 'Commercial Vehicle', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#fef9c3', 'icon_color': '#a16207', 'icon': 'truck', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=Motor%20Insurance&InsuranceCompany=Commercial%20Vehicle&openFilter=1', 'order': 11},
            {'label': 'Fire (SME)', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#fef2f2', 'icon_color': '#dc2626', 'icon': 'flame', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Fire%20(SME)&openFilter=1', 'order': 12},
            {'label': 'Cyber (SME)', 'badge_text': 'New', 'badge_bg_color': '#cffafe', 'badge_text_color': '#0e7490', 'icon_bg_color': '#ecfeff', 'icon_color': '#0891b2', 'icon': 'lock', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Cyber%20(SME)&openFilter=1', 'order': 13},
            {'label': 'Liability (SME)', 'badge_text': '', 'badge_bg_color': '', 'badge_text_color': '', 'icon_bg_color': '#f1f5f9', 'icon_color': '#475569', 'icon': 'scale', 'url': '/find-agents?ServiceType=New%20Policy&InsuranceType=SME%20Insurance&InsuranceCompany=Liability%20(SME)&openFilter=1', 'order': 14},
        ]
        for qp in quick_picks:
            QuickPickItem.objects.create(**qp)
            
        # 8. WhyChooseCard
        WhyChooseCard.objects.all().delete()
        why_cards = [
            {'stat_text': '0', 'caption': 'Spam Calls', 'icon': 'shield-check', 'title': 'Privacy-first by design', 'body': 'Only YOU can contact an agent. Agents can never call you first — your number is never sold or shared.', 'order': 1},
            {'stat_text': '₹0', 'caption': 'Platform Fee', 'icon': 'indian-rupee', 'title': '100% free for buyers', 'body': 'No charges, no hidden costs. Your premium stays the same — the agent earns from the insurer, never from you.', 'order': 2},
            {'stat_text': '100%', 'caption': 'Licensed Agents', 'icon': 'badge-check', 'title': 'Verified, licensed experts only', 'body': 'Every agent is a licensed insurance professional, vetted before listing. No call-centre scripts, ever.', 'order': 3},
            {'stat_text': '1,000+', 'caption': 'Padosi Agents', 'icon': 'map-pin', 'title': 'A neighbour in every PIN code', 'body': 'Discover trusted advisors within your locality who understand local hospitals, traffic and risks.', 'order': 4},
            {'stat_text': '1L+', 'caption': 'Families Covered', 'icon': 'users', 'title': 'A network you can rely on', 'body': 'Lakhs of Indian families have already found their PadosiAgent for buying, renewing and claims.', 'order': 5},
            {'stat_text': '5.0★', 'caption': 'Average Rating', 'icon': 'star', 'title': 'Loved by buyers across India', 'body': 'Real reviews from real customers — no incentivised ratings, no fake testimonials.', 'order': 6},
            {'stat_text': 'AES-256', 'caption': 'Encrypted Data', 'icon': 'lock', 'title': 'Bank-grade data security', 'body': 'Your information is encrypted end-to-end and never sold to third parties. Full control, always.', 'order': 7},
        ]
        for wc in why_cards:
            WhyChooseCard.objects.create(**wc)
            
        # 9. HowItWorksStep
        HowItWorksStep.objects.all().delete()
        steps = [
            {'icon': 'search', 'accent_class': 'accent-primary', 'badge_number': '1', 'title': 'Search', 'description': 'Find verified agents', 'tooltip': 'Find verified insurance experts by area or service.', 'order': 1},
            {'icon': 'git-compare', 'accent_class': 'accent-secondary', 'badge_number': '2', 'title': 'Compare', 'description': 'Review ratings', 'tooltip': 'Review ratings and profiles to find your perfect match.', 'order': 2},
            {'icon': 'message-square', 'accent_class': 'accent-accent', 'badge_number': '3', 'title': 'Connect', 'description': 'Call or WhatsApp', 'tooltip': 'Get in touch via Call or WhatsApp instantly.', 'order': 3},
            {'icon': 'hand-heart', 'accent_class': 'accent-violet', 'badge_number': '4', 'title': 'Assist Me', 'description': 'Personalized service', 'tooltip': 'Get professional support for policies, claims, and more.', 'order': 4},
        ]
        for step in steps:
            HowItWorksStep.objects.create(**step)
            
        self.stdout.write(self.style.SUCCESS('Successfully seeded homepage data!'))
