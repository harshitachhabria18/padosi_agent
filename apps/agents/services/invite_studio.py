"""
Invite & Share Studio service for Agent Dashboard.

Supports:
- Section 1: Review & Rating (Asking clients for 5-star reviews & testimonials)
- Section 2: Share on Social Media (Sharing digital visiting card, profile & referral campaign offer)
- Multi-language support (English, Hindi, Gujarati, Marathi)
- Pre-drafted templates with dynamic placeholder replacement
"""
import json
import logging
from urllib.parse import quote
from django.urls import reverse

logger = logging.getLogger(__name__)

STUDIO_TEMPLATES = {
    'review': {
        'label': 'Review & Rating',
        'languages': {
            'en': {
                'label': 'English',
                'templates': [
                    {
                        'id': 'rev_en_1',
                        'title': '⭐ Client Review Request (Recommended)',
                        'text': (
                            "Hi! Thank you for trusting me as your insurance advisor.\n\n"
                            "Could you please take 30 seconds to share your valuable review and 5-star rating on my official PadosiAgent profile?\n\n"
                            "⭐ Leave your review here:\n"
                            "{{review_link}}\n\n"
                            "You can also view my complete profile:\n"
                            "{{profile_link}}\n\n"
                            "Your feedback helps me serve you and others even better!\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_en_2',
                        'title': '⚡ Quick 30-Sec Rating',
                        'text': (
                            "Dear client, your experience matters to me!\n\n"
                            "Please rate my insurance service and share quick feedback on PadosiAgent:\n"
                            "⭐ Rate now: {{review_link}}\n\n"
                            "Thank you for your continuous support and trust.\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_en_3',
                        'title': '🤝 Professional Service Feedback',
                        'text': (
                            "Hello, I strive to provide the best insurance guidance for you and your family.\n\n"
                            "If you're satisfied with my service, I would truly appreciate your rating and review on PadosiAgent:\n"
                            "{{review_link}}\n\n"
                            "Warm regards,\n"
                            "{{agent_name}}"
                        )
                    }
                ]
            },
            'hi': {
                'label': 'हिन्दी (Hindi)',
                'templates': [
                    {
                        'id': 'rev_hi_1',
                        'title': '⭐ समीक्षा और रेटिंग अनुरोध (अनुशंसित)',
                        'text': (
                            "नमस्ते! अपने बीमा सलाहकार के रूप में मुझ पर विश्वास करने के लिए धन्यवाद।\n\n"
                            "कृपया PadosiAgent पर मेरी आधिकारिक प्रोफाइल पर 30 सेकंड निकालकर अपना बहुमूल्य रिव्यू और 5-स्टार रेटिंग दें:\n\n"
                            "⭐ रिव्यू यहाँ दें:\n"
                            "{{review_link}}\n\n"
                            "मेरी पूरी प्रोफाइल देखें:\n"
                            "{{profile_link}}\n\n"
                            "आपकी प्रतिक्रिया मुझे और बेहतर सेवा देने में मदद करती है!\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_hi_2',
                        'title': '⚡ त्वरित 5-स्टार रेटिंग',
                        'text': (
                            "नमस्ते, आपका अनुभव मेरे लिए अत्यंत महत्वपूर्ण है!\n\n"
                            "कृपया PadosiAgent पर मेरी सेवा को रेट करें और अपना अनुभव साझा करें:\n"
                            "⭐ अभी रेट करें: {{review_link}}\n\n"
                            "आपके विश्वास और सहयोग के लिए धन्यवाद।\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_hi_3',
                        'title': '🤝 पेशेवर सेवा फीडबैक',
                        'text': (
                            "नमस्ते, मैं आपके और आपके परिवार के लिए सर्वोत्तम बीमा सलाह देने के लिए सदैव तत्पर हूँ।\n\n"
                            "यदि आप मेरी सेवा से संतुष्ट हैं, तो कृपया एक समीक्षा अवश्य लिखें:\n"
                            "{{review_link}}\n\n"
                            "सस्नेह,\n"
                            "{{agent_name}}"
                        )
                    }
                ]
            },
            'gu': {
                'label': 'ગુજરાતી (Gujarati)',
                'templates': [
                    {
                        'id': 'rev_gu_1',
                        'title': '⭐ રિવ્યૂ અને રેટિંગ વિનંતી (ભલામણ કરેલ)',
                        'text': (
                            "નમસ્તે! તમારા ઇન્સ્યોરન્સ એડવાઇઝર તરીકે મારા પર વિશ્વાસ મૂકવા બદલ આભાર.\n\n"
                            "PadosiAgent પર મારી ઓફિશિયલ પ્રોફાઇલ પર ફક્ત 30 સેકન્ડ ફાળવીને તમારો કિંમતી રિવ્યૂ અને 5-સ્ટાર રેટિંગ આપવા વિનંતી છે:\n\n"
                            "⭐ અહીં રિવ્યૂ આપો:\n"
                            "{{review_link}}\n\n"
                            "મારી સંપૂર્ણ પ્રોફાઇલ જુઓ:\n"
                            "{{profile_link}}\n\n"
                            "તમારો સારો પ્રતિભાવ મને વધુ સારી સેવા આપવા પ્રોત્સાહિત કરશે!\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_gu_2',
                        'title': '⚡ ઝડપી 5-સ્ટાર રેટિંગ',
                        'text': (
                            "નમસ્તે, તમારો અનુભવ મારા માટે ખૂબ મૂલ્યવાન છે!\n\n"
                            "કૃપા કરીને PadosiAgent પર મારી સેવાને રેટ કરો અને તમારો અનુભવ શેર કરો:\n"
                            "⭐ અત્યારે રેટ કરો: {{review_link}}\n\n"
                            "તમારા સહકાર અને વિશ્વાસ બદલ આભાર.\n"
                            "— {{agent_name}}"
                        )
                    },
                    {
                        'id': 'rev_gu_3',
                        'title': '🤝 વિશ્વાસુ સલાહકાર ફીડબેક',
                        'text': (
                            "નમસ્તે, હું તમારા અને તમારા પરિવાર માટે શ્રેષ્ઠ વીમા માર્ગદર્શન આપવા કટિબદ્ધ છું.\n\n"
                            "જો તમે મારી સેવાથી સંતુષ્ટ હોવ તો કૃપા કરીને PadosiAgent પર એક રિવ્યૂ ચોક્કસ આપશો:\n"
                            "{{review_link}}\n\n"
                            "આપનો સ્નેહી,\n"
                            "{{agent_name}}"
                        )
                    }
                ]
            },
            'mr': {
                'label': 'मराठी (Marathi)',
                'templates': [
                    {
                        'id': 'rev_mr_1',
                        'title': '⭐ रिव्ह्यू आणि रेटिंग विनंती',
                        'text': (
                            "नमस्कार! आपला विमा सल्लागार म्हणून माझ्यावर विश्वास ठेवल्याबद्दल धन्यवाद.\n\n"
                            "कृपया PadosiAgent वर माझ्या प्रोफाइलवर ३० सेकंद काढून आपला बहुमूल्य अभिप्राय आणि ५-स्टार रेटिंग द्या:\n\n"
                            "⭐ येथे रिव्ह्यू द्या:\n"
                            "{{review_link}}\n\n"
                            "माझे प्रोफाइल पहा:\n"
                            "{{profile_link}}\n\n"
                            "— {{agent_name}}"
                        )
                    }
                ]
            }
        }
    },
    'social': {
        'label': 'Share on Social Media',
        'languages': {
            'en': {
                'label': 'English',
                'templates': [
                    {
                        'id': 'soc_en_1',
                        'title': '📢 Campaign Offer & Invite (Recommended)',
                        'text': (
                            "Hi, I'm {{agent_name}}, an Insurance Agent.\n\n"
                            "Join PadosiAgent and build your digital presence with better online visibility.\n\n"
                            "Current campaign offer:\n"
                            "• Starter's Plan: ₹{{digital_price}}/year\n"
                            "• Professional's Plan: ₹{{professional_price}}/year\n\n"
                            "Join through my referral:\n"
                            "{{referral_link}}\n\n"
                            "You can also view my profile:\n"
                            "{{profile_link}}"
                        )
                    },
                    {
                        'id': 'soc_en_2',
                        'title': '🪪 Digital Business Card & Contact',
                        'text': (
                            "Hi! I'm {{agent_name}}, your neighbourhood insurance advisor.\n\n"
                            "Save my digital visiting card, explore insurance plans, and connect with me directly:\n\n"
                            "🪪 My Digital Visiting Card:\n"
                            "{{card_link}}\n\n"
                            "🌐 View Complete Profile:\n"
                            "{{profile_link}}\n\n"
                            "Feel free to reach out for any life, health, or motor insurance queries!"
                        )
                    },
                    {
                        'id': 'soc_en_3',
                        'title': '🛡️ Trusted Insurance Advisor',
                        'text': (
                            "Looking for trusted and personalized insurance guidance for your family?\n\n"
                            "I'm {{agent_name}}, verified Insurance Advisor on PadosiAgent.\n\n"
                            "Check my verified credentials, client reviews, and services here:\n"
                            "{{profile_link}}\n\n"
                            "Always happy to help you protect what matters most!"
                        )
                    }
                ]
            },
            'hi': {
                'label': 'हिन्दी (Hindi)',
                'templates': [
                    {
                        'id': 'soc_hi_1',
                        'title': '📢 डिजिटल पहचान और ऑफर (अनुशंसित)',
                        'text': (
                            "नमस्ते, मैं {{agent_name}}, एक इंश्योरेंस एडवाइजर हूँ।\n\n"
                            "PadosiAgent से जुड़ें और बेहतर ऑनलाइन विजिबिलिटी के साथ अपनी डिजिटल पहचान बनाएं।\n\n"
                            "ऑफर:\n"
                            "• डिजिटल प्लान: ₹{{digital_price}}/वर्ष\n"
                            "• प्रोफेशनल प्लान: ₹{{professional_price}}/वर्ष\n\n"
                            "मेरे रेफरल लिंक से जुड़ें:\n"
                            "{{referral_link}}\n\n"
                            "मेरी प्रोफाइल देखें:\n"
                            "{{profile_link}}"
                        )
                    },
                    {
                        'id': 'soc_hi_2',
                        'title': '🪪 डिजिटल विजिटिंग कार्ड',
                        'text': (
                            "नमस्ते! मैं {{agent_name}}, आपका विश्वसनीय इंश्योरेंस सलाहकार।\n\n"
                            "मेरा डिजिटल विजिटिंग कार्ड सेव करें और बीमा संबंधी सलाह के लिए संपर्क करें:\n\n"
                            "🪪 डिजिटल कार्ड:\n"
                            "{{card_link}}\n\n"
                            "🌐 मेरी प्रोफाइल देखें:\n"
                            "{{profile_link}}\n\n"
                            "लाइफ, हेल्थ और मोटर इंश्योरेंस के लिए कभी भी संपर्क करें!"
                        )
                    },
                    {
                        'id': 'soc_hi_3',
                        'title': '🛡️ विश्वसनीय बीमा सलाहकार',
                        'text': (
                            "क्या आप अपने परिवार के लिए सही बीमा योजना की तलाश में हैं?\n\n"
                            "मैं {{agent_name}}, PadosiAgent पर वेरिफाइड इंश्योरेंस एडवाइजर हूँ।\n\n"
                            "मेरी प्रोफाइल, सेवाएं और ग्राहकों के रिव्यूज देखें:\n"
                            "{{profile_link}}"
                        )
                    }
                ]
            },
            'gu': {
                'label': 'ગુજરાતી (Gujarati)',
                'templates': [
                    {
                        'id': 'soc_gu_1',
                        'title': '📢 ડિજિટલ ઓળખ અને ઓફર (ભલામણ કરેલ)',
                        'text': (
                            "નમસ્તે, હું {{agent_name}}, ઇન્સ્યોરન્સ એડવાઇઝર છું.\n\n"
                            "PadosiAgent સાથે જોડાઈને તમારી ડિજિટલ હાજરી અને બિઝનેસ ગ્રોથ વધારો.\n\n"
                            "કેમ્પેઇન ઓફર:\n"
                            "• Starter's Plan: ₹{{digital_price}}/વર્ષ\n"
                            "• Professional's Plan: ₹{{professional_price}}/વર્ષ\n\n"
                            "મારા રેફરલ લિંકથી જોડાઓ:\n"
                            "{{referral_link}}\n\n"
                            "મારી પ્રોફાઇલ જુઓ:\n"
                            "{{profile_link}}"
                        )
                    },
                    {
                        'id': 'soc_gu_2',
                        'title': '🪪 ડિજિટલ વિઝિટિંગ કાર્ડ',
                        'text': (
                            "નમસ્તે! હું {{agent_name}}, તમારો વિશ્વાસુ ઇન્સ્યોરન્સ એડવાઇઝર.\n\n"
                            "મારું ડિજિટલ વિઝિટિંગ કાર્ડ સેવ કરો અને વીમા સેવાઓ માટે મારો સીધો સંપર્ક કરો:\n\n"
                            "🪪 મારું ડિજિટલ કાર્ડ:\n"
                            "{{card_link}}\n\n"
                            "🌐 સંપૂર્ણ પ્રોફાઇલ જુઓ:\n"
                            "{{profile_link}}\n\n"
                            "લાઇફ, હેલ્થ કે વાહન વીમાની માહિતી માટે આજે જ સંપર્ક કરો!"
                        )
                    },
                    {
                        'id': 'soc_gu_3',
                        'title': '🛡️ વિશ્વાસુ ઇન્સ્યોરન્સ એડવાઇઝર',
                        'text': (
                            "તમારા અને તમારા પરિવાર માટે શ્રેષ્ઠ વીમા આયોજન શોધી રહ્યા છો?\n\n"
                            "હું {{agent_name}}, PadosiAgent પર વેરિફાઇડ ઇન્સ્યોરન્સ એડવાઇઝર છું.\n\n"
                            "મારી પ્રોફાઇલ, ક્લાયન્ટ રિવ્યૂઝ અને સેવાઓ અહીં જુઓ:\n"
                            "{{profile_link}}"
                        )
                    }
                ]
            },
            'mr': {
                'label': 'मराठी (Marathi)',
                'templates': [
                    {
                        'id': 'soc_mr_1',
                        'title': '📢 डिजिटल ओळख व ऑफर',
                        'text': (
                            "नमस्कार, मी {{agent_name}}, विमा सल्लागार.\n\n"
                            "PadosiAgent सोबत जोडून आपली डिजिटल ओळख तयार करा.\n\n"
                            "ऑफर:\n"
                            "• Digital: ₹{{digital_price}}/वर्ष\n"
                            "• Professional: ₹{{professional_price}}/वर्ष\n\n"
                            "माझ्या लिंकवरून जॉइन करा:\n"
                            "{{referral_link}}\n\n"
                            "माझे प्रोफाइल पहा:\n"
                            "{{profile_link}}"
                        )
                    }
                ]
            }
        }
    }
}


def get_invite_studio_config():
    """
    Fetches the dynamic Invite & Share Studio config from SiteSetting DB table.
    Falls back to STUDIO_TEMPLATES default dictionary if not set.
    """
    from apps.home.models.site_setting import SiteSetting
    default_config = {
        'modal_title': 'PadosiAgent Invite & Share Studio',
        'modal_subtitle': 'Send pre-drafted or customized invites to collect 5-star client reviews or share your digital presence across social networks.',
        'tab_review_label': 'Review & Rating',
        'tab_social_label': 'Social Media Share',
        'digital_price': '999',
        'professional_price': '4999',
        'templates': STUDIO_TEMPLATES,
    }
    config = SiteSetting.get_value('invite_studio_config', default_config)
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            config = default_config
    if not isinstance(config, dict):
        config = default_config

    for k, v in default_config.items():
        if k not in config or config[k] is None or config[k] == '':
            config[k] = v
    return config


def render_template_text(raw_text, agent_name, profile_link, review_link, card_link, referral_link, digital_price="999", professional_price="4999"):
    """
    Replaces template variables with real agent values.
    """
    if not raw_text:
        return ""
    return (
        str(raw_text)
        .replace("{{agent_name}}", agent_name or "Insurance Advisor")
        .replace("{{profile_link}}", profile_link or "")
        .replace("{{review_link}}", review_link or "")
        .replace("{{card_link}}", card_link or "")
        .replace("{{referral_link}}", referral_link or "")
        .replace("{{digital_price}}", str(digital_price))
        .replace("{{professional_price}}", str(professional_price))
    )


def get_studio_context(request, agent, profile=None, champ_participant=None):
    """
    Builds all context variables needed for the WhatsApp & Social Invite Studio.
    Integrates dynamic admin configuration from SiteSetting.
    """
    config = get_invite_studio_config()
    templates = config.get('templates') or STUDIO_TEMPLATES
    dig_price = str(config.get('digital_price', '999'))
    prof_price = str(config.get('professional_price', '4999'))

    slug = (profile.slug if profile and profile.slug else '') or getattr(agent, 'agent_slug', '') or str(agent.id)
    state_code = agent.state_code() if callable(getattr(agent, 'state_code', None)) else getattr(agent, 'state_code', 'gj')
    
    # Profile link
    if slug:
        profile_url = request.build_absolute_uri(
            reverse('agents:agent_public_profile_state_direct', kwargs={'state_code': state_code, 'slug': slug})
        )
    else:
        profile_url = request.build_absolute_uri('/')

    # Review link
    if slug:
        review_url = request.build_absolute_uri(
            reverse('agents:agent_public_review', kwargs={'slug': slug})
        )
    else:
        review_url = profile_url

    # Card link
    if slug:
        card_url = request.build_absolute_uri(
            reverse('agents:agent_public_card', kwargs={'slug': slug})
        )
    else:
        card_url = profile_url

    # Referral link
    domain = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    if champ_participant and getattr(champ_participant, 'referral_id', None):
        referral_url = f"{scheme}://{domain}/agent-registration/join/{champ_participant.referral_id}/"
    else:
        ref_id = getattr(agent, 'referral_id', None) or slug
        referral_url = f"{scheme}://{domain}/agent-registration/join/{ref_id}/"

    agent_name = (profile.display_name if profile and profile.display_name else '') or agent.fullname or 'Insurance Agent'

    # Initial template text resolution
    rev_tpl_text = ''
    try:
        rev_tpl_text = templates['review']['languages']['en']['templates'][0]['text']
    except Exception:
        rev_tpl_text = STUDIO_TEMPLATES['review']['languages']['en']['templates'][0]['text']

    soc_tpl_text = ''
    try:
        soc_tpl_text = templates['social']['languages']['en']['templates'][0]['text']
    except Exception:
        soc_tpl_text = STUDIO_TEMPLATES['social']['languages']['en']['templates'][0]['text']

    default_review_text = render_template_text(
        rev_tpl_text,
        agent_name=agent_name,
        profile_link=profile_url,
        review_link=review_url,
        card_link=card_url,
        referral_link=referral_url,
        digital_price=dig_price,
        professional_price=prof_price,
    )

    default_social_text = render_template_text(
        soc_tpl_text,
        agent_name=agent_name,
        profile_link=profile_url,
        review_link=review_url,
        card_link=card_url,
        referral_link=referral_url,
        digital_price=dig_price,
        professional_price=prof_price,
    )

    return {
        'studio_config': config,
        'studio_templates_json': json.dumps(templates, ensure_ascii=False),
        'studio_modal_title': config.get('modal_title', 'PadosiAgent Invite & Share Studio'),
        'studio_modal_subtitle': config.get('modal_subtitle', 'Send pre-drafted or customized invites to collect 5-star client reviews or share your digital presence across social networks.'),
        'studio_tab_review_label': config.get('tab_review_label', 'Review & Rating'),
        'studio_tab_social_label': config.get('tab_social_label', 'Social Media Share'),
        'studio_profile_url': profile_url,
        'studio_review_url': review_url,
        'studio_card_url': card_url,
        'studio_referral_url': referral_url,
        'studio_agent_name': agent_name,
        'studio_dig_price': dig_price,
        'studio_prof_price': prof_price,
        'studio_default_review_text': default_review_text,
        'studio_default_social_text': default_social_text,
        'studio_default_review_encoded': quote(default_review_text),
        'studio_default_social_encoded': quote(default_social_text),
    }
