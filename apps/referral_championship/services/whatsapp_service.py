from urllib.parse import quote

# 9 Supported Languages with 5 tailored templates each
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
                'title': '५०% विशेष सवलત',
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


def render_whatsapp_message(template_text, agent_name, referral_link, profile_link, digital_price=999, professional_price=4999, discount=50):
    """Substitute dynamic variables in WhatsApp template text."""
    msg = template_text
    msg = msg.replace('{{agent_name}}', str(agent_name or 'Insurance Advisor'))
    msg = msg.replace('{{referral_link}}', str(referral_link or ''))
    msg = msg.replace('{{profile_link}}', str(profile_link or referral_link or ''))
    msg = msg.replace('{{digital_price}}', str(int(digital_price)))
    msg = msg.replace('{{professional_price}}', str(int(professional_price)))
    msg = msg.replace('{{discount}}', f"{discount}%")
    return msg


def get_whatsapp_share_url(rendered_message):
    """Generate the pre-filled WhatsApp share URL."""
    return f"https://api.whatsapp.com/send?text={quote(rendered_message)}"
