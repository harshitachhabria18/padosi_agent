import io
import base64
import random
import string
import logging
import qrcode
from urllib.parse import quote
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc

from fastapi_app.models.agent import Agent
from fastapi_app.models.agent_review import AgentReview
from fastapi_app.models.agent_profile import AgentProfile
from fastapi_app.models.agent_serviceable_city import AgentServiceableCity
from fastapi_app.models.city import City
from fastapi_app.models.championship import (
    ChampionshipCampaign,
    ChampionshipParticipant,
    ChampionshipReferral,
    ChampionshipRewardSlab,
    ChampionshipRewardClaim,
    ChampionshipSocialAction,
    ChampionshipScratchUnlock,
    ChampionshipGoogleReviewLog,
    ChampionshipFraudFlag,
    ChampionshipAuditLog,
    ChampionshipLeaderboardCache,
)

logger = logging.getLogger(__name__)

# Multi-lingual WhatsApp templates (9 Indian Languages)
WHATSAPP_TEMPLATES = {
    'en': {
        'label': 'English',
        'templates': [
            {
                'id': 'en_1',
                'title': 'Professional Growth Invitation',
                'text': "Hi, I'm {{agent_name}}, an Insurance Agent.\n\nJoin PadosiAgent and build your digital presence with better online visibility.\n\nCurrent campaign offer:\n• Starter's Plan: ₹{{digital_price}}/year\n• Professional's Plan: ₹{{professional_price}}/year\n\nJoin through my referral:\n{{referral_link}}\n\nYou can also view my profile:\n{{profile_link}}"
            },
            {
                'id': 'en_2',
                'title': '50% Limited Campaign Offer',
                'text': "Special invite from {{agent_name}}!\n\nPadosiAgent is hosting the National Referral Championship. Unlock 50% OFF today on your verified digital profile.\n\nClaim offer here:\n{{referral_link}}"
            },
            {
                'id': 'en_3',
                'title': 'Grow Your Insurance Business Online',
                'text': "Fellow Advisor, take your insurance career digital with PadosiAgent. Verified badge, reviews & leads all in one place.\n\nRegister with my invite code: {{referral_link}}\nSee how my profile looks: {{profile_link}}"
            },
            {
                'id': 'en_4',
                'title': 'New Customer Visibility',
                'text': "Want customers in your area to discover you easily? Get listed on India's top insurance advisor network at just ₹{{digital_price}}/year!\n\nUse my invitation link: {{referral_link}}"
            },
            {
                'id': 'en_5',
                'title': 'Direct Recommendation',
                'text': "I personally recommend PadosiAgent for all licensed insurance agents. Check it out and unlock exclusive campaign pricing:\n{{referral_link}}"
            }
        ]
    },
    'hi': {
        'label': 'हिन्दी (Hindi)',
        'templates': [
            {
                'id': 'hi_1',
                'title': 'डिजिटल पहचान बनाएं',
                'text': "नमस्ते, मैं {{agent_name}}, एक सर्टिफाइड इंश्योरेंस एडवाइजर हूँ।\n\nPadosiAgent के साथ अपनी डिजिटल प्रोफाइल बनाएं और नए ग्राहकों तक पहुँचें।\n\nऑफर:\n• डिजिटल प्लान: मात्र ₹{{digital_price}}/वर्ष\n• प्रोफेशनल प्लान: मात्र ₹{{professional_price}}/वर्ष\n\nमेरे रेफरल लिंक से जुड़ें:\n{{referral_link}}\n\nमेरी प्रोफाइल देखें:\n{{profile_link}}"
            },
            {
                'id': 'hi_2',
                'title': '50% छूट का विशेष अवसर',
                'text': "साथी एजेंट, PadosiAgent नेशनल चैंपियनशिप के तहत अभी 50% की विशेष छूट मिल रही है।\n\nतुरंत लाभ उठाएं और डिजिटल एडवाइजर बनें:\n{{referral_link}}"
            },
            {
                'id': 'hi_3',
                'title': 'विश्वसनीयता और रिव्यूज',
                'text': "ग्राहकों का विश्वास जीतें और अपना इंश्योरेंस बिजनेस ऑनलाइन बढ़ाएं। PadosiAgent पर आज ही रजिस्टर करें:\n{{referral_link}}"
            },
            {
                'id': 'hi_4',
                'title': 'वेरिफाइड एजेंट बैज',
                'text': "अपने शहर में वेरिफाइड एजेंट की पहचान बनाएं। मात्र ₹{{digital_price}}/वर्ष में शुरू करें:\n{{referral_link}}"
            },
            {
                'id': 'hi_5',
                'title': 'सीधा निमंत्रण',
                'text': "मैंने PadosiAgent जॉइन किया है और रिस्पॉन्स बहुत बढ़िया है। आप भी जुड़ें:\n{{referral_link}}"
            }
        ]
    },
    'gu': {
        'label': 'ગુજરાતી (Gujarati)',
        'templates': [
            {
                'id': 'gu_1',
                'title': 'ડિજિટલ પ્રોફાઇલ આમંત્રણ',
                'text': "નમસ્તે, હું {{agent_name}}, ઇન્સ્યોરન્સ એડવાઇઝર છું.\n\nPadosiAgent સાથે તમારી ડિજિટલ ઓળખ બનાવો અને વધુ ગ્રાહકો સુધી પહોંચો.\n\nકેમ્પેઇન ઓફર:\n• Digital: માત્ર ₹{{digital_price}}/વર્ષ\n• Professional: માત્ર ₹{{professional_price}}/વર્ષ\n\nમારી લિંકથી જોડાઓ:\n{{referral_link}}\n\nમારી પ્રોફાઇલ જુઓ:\n{{profile_link}}"
            },
            {
                'id': 'gu_2',
                'title': '૫૦% ડિસ્કાઉન્ટ ઓફર',
                'text': "વિશેષ ઓફર! PadosiAgent નેશનલ ચેમ્પિયનશિપ હેઠળ 50% ડિસ્કાઉન્ટ મેળવો:\n{{referral_link}}"
            },
            {
                'id': 'gu_3',
                'title': 'ઓનલાઇન બિઝનેસ ગ્રોથ',
                'text': "તમારા વીમા વ્યવસાયને ઓનલાઇન લઈ જાઓ. વેરિફાઇડ બેજ અને રિવ્યુઝ સાથે ગ્રાહકોનો વિશ્વાસ જીતો:\n{{referral_link}}"
            },
            {
                'id': 'gu_4',
                'title': 'ગ્રાહકોની શોધમાં આગળ રહો',
                'text': "તમારા વિસ્તારમાં ગ્રાહકો તમને સરળતાથી શોધી શકે તે માટે આજે જ લિસ્ટ થાઓ:\n{{referral_link}}"
            },
            {
                'id': 'gu_5',
                'title': 'ખાસ ભલામણ',
                'text': "હું પોતે PadosiAgent વાપરું છું. તમે પણ જોડાઈને ફાયદો ઉઠાવો:\n{{referral_link}}"
            }
        ]
    },
    'mr': {
        'label': 'मराठी (Marathi)',
        'templates': [
            {
                'id': 'mr_1',
                'title': 'डिजिटल ओळख तयार करा',
                'text': "नमस्कार, मी {{agent_name}}, विमा सल्लागार आहे.\n\nPadosiAgent सह आपली डिजिटल ओळख निर्माण करा.\n\nऑफर: ₹{{digital_price}}/वर्ष\nयेथे नोंदणी करा: {{referral_link}}\nमाझे प्रोफाइल पहा: {{profile_link}}"
            },
            {
                'id': 'mr_2',
                'title': '५०% विशेष सवलत',
                'text': "PadosiAgent च्या विशेष मोहिमेत 50% सवलतीचा लाभ घ्या आणि ऑनलाइन व्हा:\n{{referral_link}}"
            },
            {
                'id': 'mr_3',
                'title': 'विमा व्यवसाय वाढवा',
                'text': "आपल्या परिसरातील नवीन ग्राहकांपर्यंत पोहोचण्यासाठी आजच नोंदणी करा:\n{{referral_link}}"
            },
            {
                'id': 'mr_4',
                'title': 'व्हेरिफाइड एजंट बॅज',
                'text': "अधिकृत विमा सल्लागाराची ओळख मिळवा आणि व्यवसाय वाढवा:\n{{referral_link}}"
            },
            {
                'id': 'mr_5',
                'title': 'थेट शिफारस',
                'text': "मी PadosiAgent वापरत आहे, आपणही जुळा आणि लाभ घ्या:\n{{referral_link}}"
            }
        ]
    },
    'ta': {
        'label': 'தமிழ் (Tamil)',
        'templates': [
            {
                'id': 'ta_1',
                'title': 'டிஜிட்டல் அடையாளம்',
                'text': "வணக்கம், நான் {{agent_name}}, காப்பீட்டு ஆலோசகர்.\n\nPadosiAgent மூலம் உங்கள் ஆன்லைன் இருப்பை உருவாக்குங்கள்.\nசலுகை விலை: ₹{{digital_price}}/ஆண்டு\nஇணைப்பு: {{referral_link}}\nஎன் சுயவிவரம்: {{profile_link}}"
            },
            {
                'id': 'ta_2',
                'title': '50% சிறப்பு தள்ளுபடி',
                'text': "PadosiAgent சாம்பியன்ஷிப் சிறப்பு சலுகையில் 50% தள்ளுபடி பெறுங்கள்:\n{{referral_link}}"
            },
            {
                'id': 'ta_3',
                'title': 'புதிய வாடிக்கையாளர்கள்',
                'text': "உங்கள் பகுதியில் உள்ள புதிய வாடிக்கையாளர்களை ஈர்க்க இப்போதே சேருங்கள்:\n{{referral_link}}"
            },
            {
                'id': 'ta_4',
                'title': 'சரிபார்க்கப்பட்ட பேட்ஜ்',
                'text': "சரிபார்க்கப்பட்ட காப்பீட்டு முகவராக அடையாளம் காணுங்கள்:\n{{referral_link}}"
            },
            {
                'id': 'ta_5',
                'title': 'நேரடி அழைப்பு',
                'text': "என் பரிந்துரை மூலம் சேர்ந்து உங்கள் தொழிலை வளர்த்துக் கொள்ளுங்கள்:\n{{referral_link}}"
            }
        ]
    },
    'te': {
        'label': 'తెలుగు (Telugu)',
        'templates': [
            {
                'id': 'te_1',
                'title': 'డిజిటల్ గుర్తింపు',
                'text': "నమస్కారం, నేను {{agent_name}}, ఇన్సూరెన్స్ అడ్వైజర్.\n\nPadosiAgent లో డిజిటల్ ప్రొఫైల్ ఏర్పాటు చేసుకోండి.\nప్రత్యేక ధర: ₹{{digital_price}}/సంవత్సరం\nలింక్: {{referral_link}}\nనా ప్రొఫైల్: {{profile_link}}"
            },
            {
                'id': 'te_2',
                'title': '50% తగ్గింపు ఆఫర్',
                'text': "నేషనల్ ఛాంపియన్‌షిప్ ఆఫర్‌లో 50% తగ్గింపును పొందండి:\n{{referral_link}}"
            },
            {
                'id': 'te_3',
                'title': 'వ్యాపార వృద్ధి',
                'text': "మీ ప్రాంతంలో ఎక్కువ మంది కస్టమర్లను చేరుకోవడానికి చేరండి:\n{{referral_link}}"
            },
            {
                'id': 'te_4',
                'title': 'వెరిఫైడ్ బ్యాడ్జ్',
                'text': "వెరిఫైడ్ ఏజెంట్ గుర్తింపుతో నమ్మకాన్ని పెంచుకోండి:\n{{referral_link}}"
            },
            {
                'id': 'te_5',
                'title': 'ప్రత్యేక ఆహ్వానం',
                'text': "నా ఆహ్వాన లింక్ ద్వారా చేరి ప్రయోజనం పొందండి:\n{{referral_link}}"
            }
        ]
    },
    'bn': {
        'label': 'বাংলা (Bengali)',
        'templates': [
            {
                'id': 'bn_1',
                'title': 'ডিজিটাল প্রোফাইল তৈরি করুন',
                'text': "নমস্কার, আমি {{agent_name}}, ইনসিওরেন্স এজেন্ট।\n\nPadosiAgent-এ আপনার ডিজিটাল প্রোফাইল তৈরি করুন।\nঅফার মূল্য: ₹{{digital_price}}/বছর\nলিঙ্ক: {{referral_link}}\nআমার প্রোফাইল: {{profile_link}}"
            },
            {
                'id': 'bn_2',
                'title': '৫০% বিশেষ ছাড়',
                'text': "PadosiAgent ক্যাম্পেইনে বিশেষ ৫০% ছাড়ের সুযোগ নিন:\n{{referral_link}}"
            },
            {
                'id': 'bn_3',
                'title': 'নতুন গ্রাহকদের কাছে পৌঁছান',
                'text': "আপনার এলাকায় নতুন গ্রাহকদের দৃষ্টি আকর্ষণ করতে এখনই যোগ দিন:\n{{referral_link}}"
            },
            {
                'id': 'bn_4',
                'title': 'ভেরিফায়েড ব্যাজ',
                'text': "ভেরিফায়েড ইন্স্যুরেন্স এজেন্টের সম্মান ও পরিচয় লাভ করুন:\n{{referral_link}}"
            },
            {
                'id': 'bn_5',
                'title': 'সরাসরি আমন্ত্রণ',
                'text': "আমার রেফারেল লিঙ্ক দিয়ে আজই যুক্ত হোন:\n{{referral_link}}"
            }
        ]
    },
    'ml': {
        'label': 'മലയാളം (Malayalam)',
        'templates': [
            {
                'id': 'ml_1',
                'title': 'ഡിജിറ്റൽ പ്രൊഫൈൽ',
                'text': "നമസ്കാരം, ഞാൻ {{agent_name}}, ഇൻഷുറൻസ് ഏജന്റ് ആണ്.\n\nPadosiAgent വഴി നിങ്ങളുടെ ഡിജിറ്റൽ പ്രൊഫൈൽ തുടങ്ങൂ.\nവില: ₹{{digital_price}}/വർഷം\nലിങ്ക്: {{referral_link}}\nഎന്റെ പ്രൊഫൈൽ: {{profile_link}}"
            },
            {
                'id': 'ml_2',
                'title': '50% പ്രത്യേക ഇളവ്',
                'text': "PadosiAgent നാഷണൽ കാമ്പെയ്നിൽ 50% കിഴിവ് സ്വന്തമാക്കൂ:\n{{referral_link}}"
            },
            {
                'id': 'ml_3',
                'title': 'ബിസിനസ് വളർത്താം',
                'text': "കൂടുതൽ ഉപഭോക്താക്കളിലേക്ക് എത്താൻ ഇന്ന് തന്നെ രജിസ്റ്റർ ചെയ്യൂ:\n{{referral_link}}"
            },
            {
                'id': 'ml_4',
                'title': 'വെരിഫൈഡ് ബാഡ്ജ്',
                'text': "വിശ്വാസ്യതയും അംഗീകാരവും നേടൂ:\n{{referral_link}}"
            },
            {
                'id': 'ml_5',
                'title': 'നേരിട്ടുള്ള ക്ഷണം',
                'text': "എന്റെ റഫറൽ ലിങ്കിലൂടെ പങ്കുചേരൂ:\n{{referral_link}}"
            }
        ]
    },
    'kn': {
        'label': 'ಕನ್ನಡ (Kannada)',
        'templates': [
            {
                'id': 'kn_1',
                'title': 'ಡಿಜಿಟಲ್ ಗುರುತು',
                'text': "ನಮಸ್ಕಾರ, ನಾನು {{agent_name}}, ವಿಮಾ ಸಲಹೆಗಾರ.\n\nPadosiAgent ನಲ್ಲಿ ನಿಮ್ಮ ಡಿಜಿಟಲ್ ಪ್ರೊಫೈಲ್ ರಚಿಸಿ.\nಆಫರ್ ದರ: ₹{{digital_price}}/ವರ್ಷ\nಲಿಂಕ್: {{referral_link}}\nನನ್ನ ಪ್ರೊಫೈಲ್: {{profile_link}}"
            },
            {
                'id': 'kn_2',
                'title': '50% ರಿಯಾಯಿತಿ ಆಫರ್',
                'text': "PadosiAgent ಚಾಂಪಿಯನ್‌ಶಿಪ್‌ನಲ್ಲಿ 50% ರಿಯಾಯಿತಿ ಪಡೆಯಿರಿ:\n{{referral_link}}"
            },
            {
                'id': 'kn_3',
                'title': 'ಹೊಸ ಗ್ರಾಹಕರನ್ನು ತಲುಪಿ',
                'text': "ನಿಮ್ಮ ವಿಮಾ ವ್ಯವಹಾರವನ್ನು ಆನ್‌ಲೈನ್‌ನಲ್ಲಿ ಬೆಳೆಸಲು ನೋಂದಾಯಿಸಿ:\n{{referral_link}}"
            },
            {
                'id': 'kn_4',
                'title': 'ವೆರಿಫೈಡ್ ಬ್ಯಾಡ್ಜ್',
                'text': "ಗ್ರಾಹಕರ ನಂಬಿಕೆಯನ್ನು ಹೆಚ್ಚಿಸಲು ವೆರಿಫೈಡ್ ಏಜೆಂಟ್ ಆಗಿ ಗುರುತಿಸಿಕೊಳ್ಳಿ:\n{{referral_link}}"
            },
            {
                'id': 'kn_5',
                'title': 'ನೇರ ಆಹ್ವಾನ',
                'text': "ನನ್ನ ಆಹ್ವಾನ ಲಿಂಕ್ ಬಳಸಿ ಇಂದೇ ಸೇರಿ:\n{{referral_link}}"
            }
        ]
    }
}


def get_current_campaign(db: Session) -> ChampionshipCampaign:
    """Retrieve active live campaign, or create default if missing."""
    campaign = db.query(ChampionshipCampaign).filter(
        ChampionshipCampaign.is_active == True,
        ~ChampionshipCampaign.status.in_(['ended', 'archived'])
    ).first()

    if not campaign:
        campaign = ChampionshipCampaign(
            name="PadosiAgent Referral Championship",
            slug="championship-2026",
            start_date=datetime(2026, 9, 15, 0, 0, 0),
            end_date=datetime(2026, 10, 31, 23, 59, 59),
            status="live",
            is_active=True,
            pricing_config={
                "digital": {"regular_price": 1999, "campaign_price": 999, "renewal_price": 1999, "name": "Starter's Plan"},
                "professional": {"regular_price": 9999, "campaign_price": 4999, "renewal_price": 9999, "name": "Professional's Plan"},
                "discount_percent": 50
            },
            unlock_config={
                "min_profile_percent": 80,
                "min_reviews": 10
            },
            social_channels=[
                {"platform": "instagram", "name": "Instagram", "url": "https://instagram.com/padosiagent", "icon": "fa-instagram"},
                {"platform": "facebook", "name": "Facebook", "url": "https://facebook.com/padosiagent", "icon": "fa-facebook-f"}
            ],
            google_review_url="https://g.page/r/padosiagent/review"
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        # Seed default reward slabs
        seed_default_slabs(db, campaign)

    return campaign


def seed_default_slabs(db: Session, campaign: ChampionshipCampaign):
    """Seed standard reward slabs: 5, 10, 25, 50, 100, 200, Top 3."""
    defaults = [
        (5, "Membership Fee Back", "100% Membership Fee Back via Amazon or Flipkart Voucher", 'membership_fee_back', 'fa-gift', 999.00, 1),
        (10, "Professional's Plan Free", "Professional's Plan complimentary for 12 months", 'plan_upgrade', 'fa-crown', 9999.00, 2),
        (25, "25g Silver Coin", "Exclusive 25 Gram Minted Silver Coin dispatched to your address", 'silver', 'fa-coins', 2500.00, 3),
        (50, "1g Gold Coin + Lucky Draw Tier 1", "1 Gram 24K Gold Coin + Entry in Grand Lucky Draw Tier 1", 'gold', 'fa-medal', 7500.00, 4),
        (100, "Solo Domestic Trip + Lucky Draw Tier 2", "Solo Domestic Luxury Trip (flight + stay) + Tier 2 Draw", 'domestic_trip', 'fa-plane', 35000.00, 5),
        (200, "Solo International Trip + Lucky Draw Tier 3", "Solo International Luxury Vacation + Tier 3 Draw", 'international_trip', 'fa-globe-asia', 90000.00, 6),
        (999, "Top 3: Family International Trip", "Grand Family Vacation (2 Adults + 1 Child) for Top 3 Leaders", 'family_trip', 'fa-trophy', 250000.00, 7),
    ]

    for threshold, title, desc_text, r_type, icon, val, order in defaults:
        existing = db.query(ChampionshipRewardSlab).filter(
            ChampionshipRewardSlab.campaign_id == campaign.id,
            ChampionshipRewardSlab.threshold == threshold
        ).first()
        if not existing:
            slab = ChampionshipRewardSlab(
                campaign_id=campaign.id,
                threshold=threshold,
                title=title,
                description=desc_text,
                reward_type=r_type,
                badge_icon=icon,
                value=val,
                order=order,
                is_active=True,
                dispatch_date_default=date(2026, 12, 15)
            )
            db.add(slab)
    db.commit()


def get_or_create_participant(db: Session, agent_id: int, campaign: ChampionshipCampaign = None) -> ChampionshipParticipant:
    """Ensure agent has a permanent unique referral ID (PA-XXXXXX)."""
    if not campaign:
        campaign = get_current_campaign(db)

    participant = db.query(ChampionshipParticipant).filter(
        ChampionshipParticipant.agent_id == agent_id,
        ChampionshipParticipant.campaign_id == campaign.id
    ).first()

    if participant:
        return participant

    while True:
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        ref_id = f"PA-{suffix}"
        dup = db.query(ChampionshipParticipant).filter(ChampionshipParticipant.referral_id == ref_id).first()
        if not dup:
            break

    participant = ChampionshipParticipant(
        campaign_id=campaign.id,
        agent_id=agent_id,
        referral_id=ref_id,
        is_unlocked=False,
        qualifying_referrals_count=0
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


def get_reward_image(reward_type: str, threshold: int) -> str:
    """Return static asset path for milestone reward badge."""
    mapping = {
        5: 'championship/step-1-feeback.png',
        10: 'championship/step-2-profree.png',
        25: 'championship/step-3-silver.png',
        50: 'championship/step-4-gold.png',
        100: 'championship/step-5-domestictrip.png',
        200: 'championship/step-6-intltrip.png',
    }
    if threshold >= 900:
        return 'championship/step-7-topchampions.png'
    return mapping.get(threshold, 'championship/step-1-feeback.png')


def get_agent_profile_completion(db: Session, agent_id: int) -> int:
    """Calculate agent profile completion percentage using the platform standard 100-point rubric."""
    try:
        from fastapi_app.services.lock_unlock_service import LockUnlockService
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent:
            lock_service = LockUnlockService(db)
            return lock_service.profile_completion_percent(agent)
    except Exception as e:
        logger.warning(f"Error calculating profile completion: {e}")

    # Fallback heuristic if lock service fails
    prof = db.query(AgentProfile).filter(AgentProfile.agent_id == agent_id).first()
    if not prof:
        return 20
    score = 20
    if prof.address and prof.languages: score += 15
    if prof.profile_photo_path: score += 15
    if prof.license_number: score += 15
    if prof.service_pincodes: score += 15
    if prof.experience_years: score += 10
    if prof.desired_services: score += 10
    return min(100, score)


def get_agent_review_count(db: Session, agent_id: int) -> int:
    """Get count of verified/approved reviews for agent with fallback to agent record."""
    try:
        count = db.query(func.count(AgentReview.id)).filter(
            AgentReview.agent_id == agent_id,
            AgentReview.is_approved == True
        ).scalar()
        if count is not None and count > 0:
            return count
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        return int(getattr(agent, 'review_count', 0) or 0)
    except Exception as e:
        logger.warning(f"Error getting agent review count: {e}")
        return 0


def format_inr(val) -> str:
    """Format numeric values into Indian Rupee currency standard."""
    if not val:
        return "₹0"
    val_int = int(val)
    s = str(val_int)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return f"₹{','.join(parts)},{last3}"


def evaluate_participant_rewards(db: Session, participant: ChampionshipParticipant):
    """Auto unlock reward claims based on qualifying count."""
    campaign = participant.campaign
    slabs = db.query(ChampionshipRewardSlab).filter(
        ChampionshipRewardSlab.campaign_id == campaign.id,
        ChampionshipRewardSlab.is_active == True
    ).order_by(ChampionshipRewardSlab.threshold).all()

    count = participant.qualifying_referrals_count
    for slab in slabs:
        if slab.threshold >= 900:
            continue

        if count >= slab.threshold:
            claim = db.query(ChampionshipRewardClaim).filter(
                ChampionshipRewardClaim.participant_id == participant.id,
                ChampionshipRewardClaim.reward_slab_id == slab.id
            ).first()
            if not claim:
                claim = ChampionshipRewardClaim(
                    participant_id=participant.id,
                    reward_slab_id=slab.id,
                    status="unlocked"
                )
                db.add(claim)
            elif claim.status == "locked":
                claim.status = "unlocked"
    db.commit()


def get_participant_roadmap(db: Session, participant: ChampionshipParticipant) -> Dict[str, Any]:
    """Build dynamic 7-tier reward roadmap for agent dashboard."""
    campaign_id = participant.campaign_id
    slabs = db.query(ChampionshipRewardSlab).filter(
        ChampionshipRewardSlab.campaign_id == campaign_id,
        ChampionshipRewardSlab.is_active == True
    ).order_by(ChampionshipRewardSlab.threshold, ChampionshipRewardSlab.order).all()

    count = participant.qualifying_referrals_count or 0
    claims = db.query(ChampionshipRewardClaim).filter(
        ChampionshipRewardClaim.participant_id == participant.id
    ).all()
    claims_by_slab = {c.reward_slab_id: c for c in claims}

    roadmap = []
    next_reward = None
    referrals_needed = 0
    prev_threshold = 0

    for slab in slabs:
        if count < slab.threshold and next_reward is None and slab.threshold < 900:
            next_reward = slab
            referrals_needed = max(0, slab.threshold - count)

    for slab in slabs:
        is_reached = count >= slab.threshold if slab.threshold < 900 else False
        claim = claims_by_slab.get(slab.id)

        status = "locked"
        if claim:
            status = claim.status
        elif is_reached:
            status = "unlocked"

        is_unlocked = bool(is_reached or status in ['unlocked', 'claimed', 'approved', 'dispatched', 'delivered', 'redeemed'])
        is_current_target = bool(next_reward and slab.id == next_reward.id)

        if is_unlocked:
            progress_percent = 100
        elif is_current_target:
            span = max(1, slab.threshold - prev_threshold)
            completed_in_span = max(0, count - prev_threshold)
            progress_percent = min(99, int((completed_in_span / span) * 100))
        else:
            progress_percent = 0

        prev_threshold = slab.threshold if slab.threshold < 900 else prev_threshold

        roadmap.append({
            "id": slab.id,
            "threshold": slab.threshold,
            "title": slab.title,
            "description": slab.description or "",
            "reward_type": slab.reward_type,
            "badge_icon": slab.badge_icon,
            "value": float(slab.value or 0.0),
            "value_formatted": format_inr(slab.value),
            "is_reached": is_reached,
            "is_unlocked": is_unlocked,
            "is_current_target": is_current_target,
            "progress_percent": progress_percent,
            "referrals_needed": max(0, slab.threshold - count),
            "claim_status": status,
            "image_path": get_reward_image(slab.reward_type, slab.threshold),
        })

    next_title = next_reward.title if next_reward else ("Grand Family Trip (Top 3)" if count >= 200 else "All Slabs Achieved!")

    return {
        "roadmap": roadmap,
        "count": count,
        "next_reward_title": next_title,
        "referrals_needed": referrals_needed,
    }


def refresh_leaderboard_cache(db: Session, campaign: ChampionshipCampaign):
    """Recalculate leaderboard ranks and update cache table."""
    participants = db.query(ChampionshipParticipant).filter(
        ChampionshipParticipant.campaign_id == campaign.id,
        ChampionshipParticipant.is_fraud_blocked == False
    ).order_by(
        desc(ChampionshipParticipant.qualifying_referrals_count),
        asc(ChampionshipParticipant.last_qualification_time),
        asc(ChampionshipParticipant.created_at)
    ).all()

    rank = 1
    for p in participants:
        p.current_rank = rank
        
        cache_entry = db.query(ChampionshipLeaderboardCache).filter(
            ChampionshipLeaderboardCache.campaign_id == campaign.id,
            ChampionshipLeaderboardCache.participant_id == p.id
        ).first()

        if cache_entry:
            cache_entry.rank = rank
            cache_entry.referral_count = p.qualifying_referrals_count
            cache_entry.tie_breaker_ts = p.last_qualification_time or p.created_at
        else:
            cache_entry = ChampionshipLeaderboardCache(
                campaign_id=campaign.id,
                participant_id=p.id,
                rank=rank,
                referral_count=p.qualifying_referrals_count,
                tie_breaker_ts=p.last_qualification_time or p.created_at
            )
            db.add(cache_entry)
        rank += 1
    db.commit()


def get_leaderboard_data(db: Session, campaign: ChampionshipCampaign, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch Top N leaderboard entries with privacy-masked names."""
    entries = db.query(ChampionshipLeaderboardCache).filter(
        ChampionshipLeaderboardCache.campaign_id == campaign.id
    ).order_by(ChampionshipLeaderboardCache.rank).limit(limit).all()

    results = []
    for entry in entries:
        participant = entry.participant
        agent = participant.agent if participant else None
        if not agent:
            continue

        raw_name = (agent.fullname or f"Agent #{agent.id}").strip()
        parts = raw_name.split()
        if len(parts) > 1 and parts[1]:
            masked_name = f"{parts[0]} {parts[1][0]}."
        elif len(parts) > 0:
            masked_name = parts[0]
        else:
            masked_name = f"Agent #{agent.id}"

        city = "India"
        try:
            asc = db.query(AgentServiceableCity).filter(AgentServiceableCity.agent_id == agent.id).first()
            if asc and asc.city and asc.city.name:
                city = asc.city.name.title()
        except Exception:
            pass

        results.append({
            "rank": entry.rank,
            "agent_name": masked_name,
            "city": city,
            "referral_count": entry.referral_count,
            "referral_id": participant.referral_id,
        })

    return results


def get_campaign_aggregate_stats(db: Session, campaign: ChampionshipCampaign) -> Dict[str, int]:
    """Calculate overall live campaign aggregate metrics."""
    total_participants = db.query(func.count(ChampionshipParticipant.id)).filter(
        ChampionshipParticipant.campaign_id == campaign.id
    ).scalar() or 0

    total_paid = db.query(func.count(ChampionshipReferral.id)).filter(
        ChampionshipReferral.campaign_id == campaign.id,
        ChampionshipReferral.registration_state.in_(['paid', 'active'])
    ).scalar() or 0

    total_qualified = db.query(func.count(ChampionshipReferral.id)).filter(
        ChampionshipReferral.campaign_id == campaign.id,
        ChampionshipReferral.is_qualifying == True
    ).scalar() or 0

    total_referrals = db.query(func.count(ChampionshipReferral.id)).filter(
        ChampionshipReferral.campaign_id == campaign.id
    ).scalar() or 0

    return {
        "total_participants": total_participants,
        "total_paid": total_paid,
        "total_qualified": total_qualified,
        "total_referrals": total_referrals,
    }


def render_whatsapp_message(
    template_text: str,
    agent_name: str,
    referral_link: str,
    profile_link: str,
    digital_price: int = 999,
    professional_price: int = 4999,
    discount: int = 50
) -> str:
    """Dynamic variable interpolation into WhatsApp message template."""
    msg = template_text
    msg = msg.replace('{{agent_name}}', str(agent_name or 'Insurance Advisor'))
    msg = msg.replace('{{referral_link}}', str(referral_link or ''))
    msg = msg.replace('{{profile_link}}', str(profile_link or referral_link or ''))
    msg = msg.replace('{{digital_price}}', str(int(digital_price)))
    msg = msg.replace('{{professional_price}}', str(int(professional_price)))
    msg = msg.replace('{{discount}}', f"{discount}%")
    return msg


def get_whatsapp_share_url(rendered_message: str) -> str:
    """Generate pre-filled WhatsApp share URL."""
    return f"https://api.whatsapp.com/send?text={quote(rendered_message)}"


def generate_qr_base64(target_url: str) -> str:
    """Generate clean PNG QR code as base64 data URI."""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(target_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#1e3a8a", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        logger.warning(f"Failed to generate QR code: {e}")
        return ""


def generate_qr_bytes(target_url: str) -> bytes:
    """Generate raw PNG bytes for direct download."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=3,
    )
    qr.add_data(target_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1e3a8a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
