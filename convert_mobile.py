with open(r'c:\Users\harsh\OneDrive\Desktop\10_6\26_6\resources\views\layouts\partials\agent-card.blade.php', 'r', encoding='utf-8') as f:
    html = f.read()

# Remove the PHP block at the top
import re
html = re.sub(r'@php.*?@endphp', '', html, flags=re.DOTALL, count=1)

# Ensure we wrap the whole thing in {% with ... %}
with_block = '''{% with profile=agent.profile performance=agent.performanceStats display_name=agent.display_name active_sub=agent.activeSubscription is_trusted=agent.is_trusted is_approved_by_admin=agent.is_approved_by_admin is_verified_agent=agent.is_verified_agent agent_slug=agent.agent_slug whatsapp_digits=agent.profile.whatsapp_digits whatsapp_raw=agent.whatsapp_raw exp_years=agent.experience_years client_base=agent.client_base claims_processed=performance.claims_processed|default:0 claims_amount=performance.claims_amount|default:0 display_dist=agent.distance|default:0 has_distance=agent.has_distance rating=agent.average_rating smart_rank=agent.padosi_smart_rank calculated_match_percent=agent.calculated_match_percent badge=agent.badge|lower agent_city_display=agent.agent_city_display %}
'''
html = html.replace('<div class="react-agent-card find-agents-list-item">', '<div class="react-agent-card find-agents-list-item">\n' + with_block)
html += '\n{% endwith %}\n'

replacements = {
    "{{ ->profile?->profile_photo_url ?? asset('img/avatar-icon.jpg') }}": "{{ profile.profile_photo_url|default:'/static/img/avatar-icon.jpg' }}",
    "{{ asset('img/avatar-icon.jpg') }}": "{% static 'img/avatar-icon.jpg' %}",
    "{{  }}": "{{ display_name }}",
    "@if(count() > 0)": "{% if badge and badge != 'none' %}",
    "@foreach( as )\\n                                @php  = trim(strtolower());\\n                                 = [] ?? null; @endphp\\n                                @if()\\n                                    <span class=\\"agent-recognition-badge {{ ['class'] }}\\">\\n                                        <i class=\\"fas {{ ['icon'] }}\\"></i> {{ ['label'] }}\\n                                    </span>\\n                                @endif\\n                            @endforeach": '''
        {% if 'verified' in badge %}
            <span class="agent-recognition-badge badge-verified-official">
                <i class="fas fa-circle-check"></i> Verified
            </span>
        {% endif %}
        {% if 'irdai' in badge %}
            <span class="agent-recognition-badge badge-irdai-official">
                <i class="fas fa-medal"></i> Licensed
            </span>
        {% endif %}
        {% if 'trusted' in badge %}
            <span class="agent-recognition-badge badge-trusted-official">
                <i class="fas fa-award"></i> Trusted
            </span>
        {% endif %}
''',
    "{{  }}": "{{ rating|floatformat:1 }}",
    "{{ number_format(, 1) }}": "{{ rating|floatformat:1 }}",
    "{{ ->review_count }}": "{{ agent.review_count }}",
    "@php  = floor();\\n                     = ( - ) >= 0.5; @endphp\\n                    <div class=\\"rac-stars\\">\\n                        @for( = 1;  <= 5; ++)\\n                            @if( <= )\\n                                <svg class=\\"rac-star rac-star--full\\" xmlns=\\"http://www.w3.org/2000/svg\\"\\n                                    viewBox=\\"0 0 24 24\\">\\n                                    <path\\n                                        d=\\"M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z\\" />\\n                                </svg>\\n                            @elseif( ==  + 1 && )\\n                                <svg class=\\"rac-star rac-star--half\\" xmlns=\\"http://www.w3.org/2000/svg\\"\\n                                    viewBox=\\"0 0 24 24\\">\\n                                    <path\\n                                        d=\\"M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z\\" />\\n                                </svg>\\n                            @else\\n                                <svg class=\\"rac-star rac-star--empty\\" xmlns=\\"http://www.w3.org/2000/svg\\"\\n                                    viewBox=\\"0 0 24 24\\">\\n                                    <path\\n                                        d=\\"M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z\\" />\\n                                </svg>\\n                            @endif\\n                        @endfor\\n                    </div>": '''
                    <div class="rac-stars">
                        {% for star in agent.star_rating_list %}
                            {% if star == 'full' %}
                                <svg class="rac-star rac-star--full" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                                </svg>
                            {% elif star == 'half' %}
                                <svg class="rac-star rac-star--half" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                                </svg>
                            {% else %}
                                <svg class="rac-star rac-star--empty" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                                </svg>
                            {% endif %}
                        {% endfor %}
                    </div>
''',
    "@if()": "{% if has_distance %}",
    "@if( < 1)": "{% if display_dist < 1 %}",
    "@elseif( > 100)": "{% elif display_dist > 100 %}",
    "{{ number_format(, 1) }}": "{{ display_dist|floatformat:1 }}",
    "@if()": "{% if request.GET.pincode or request.GET.location or request.GET.lat or request.session.last_pincode or request.session.last_lat or request.session.last_location %}",
    "{{  }}": "{% if calculated_match_percent > 90 %}rac-match--green{% elif calculated_match_percent >= 51 %}rac-match--amber{% else %}rac-match--red{% endif %}",
    "{{  }}": "{{ calculated_match_percent }}",
    "@if()": "{% if agent_city_display %}",
    "{{  }}": "{{ agent_city_display }}",
    "{{  }}": "{{ exp_years }}",
    "{{  > 0 ?  . '+' : 'N/A' }}": "{{ agent.formatted_client_base }}",
    "{{ formatIndianNumber(->claims_amount ?? 0) }}": "{{ agent.formatted_claims_amount|default:'0' }}",
    "{{ formatIndianNumber(->claims_processed ?? 0) }}": "{{ agent.formatted_claims_processed|default:'0' }}",
    "@if(count() > 0)": "{% if agent.ordered_insurance_segments %}",
    "@foreach(array_slice(, 0, 4) as )\\n                            @php\\n                                 =  === 'sme' ? 'SME' : ucfirst();\\n                                 = 'rac-tag--default';\\n                                if (str_contains(, 'health')) {\\n                                     = 'rac-tag--health';\\n                                } elseif (str_contains(, 'life')) {\\n                                     = 'rac-tag--life';\\n                                } elseif (str_contains(, 'motor')) {\\n                                     = 'rac-tag--motor';\\n                                } elseif (str_contains(, 'sme')) {\\n                                     = 'rac-tag--sme';\\n                                }\\n                                 = 'fa-shield-alt';\\n                                if (str_contains(, 'health')) {\\n                                     = 'fa-heartbeat';\\n                                } elseif (str_contains(, 'life')) {\\n                                     = 'fa-user-shield';\\n                                } elseif (str_contains(, 'motor')) {\\n                                     = 'fa-car';\\n                                } elseif (str_contains(, 'sme')) {\\n                                     = 'fa-store';\\n                                }\\n                            @endphp\\n                            <span class=\\"rac-tag {{  }}\\">\\n                                <i class=\\"fas {{  }}\\" style=\\"font-size: 8px; margin-right: 3px;\\"></i>\\n                                {{  }}\\n                            </span>\\n                        @endforeach": '''
                        {% for seg in agent.ordered_insurance_segments|slice:":4" %}
                            <span class="rac-tag {% if 'health' in seg %}rac-tag--health{% elif 'life' in seg %}rac-tag--life{% elif 'motor' in seg %}rac-tag--motor{% elif 'sme' in seg %}rac-tag--sme{% else %}rac-tag--default{% endif %}">
                                <i class="fas {% if 'health' in seg %}fa-heartbeat{% elif 'life' in seg %}fa-user-shield{% elif 'motor' in seg %}fa-car{% elif 'sme' in seg %}fa-store{% else %}fa-shield-alt{% endif %}" style="font-size: 8px; margin-right: 3px;"></i>
                                {% if seg == 'sme' %}SME{% else %}{{ seg|capfirst }}{% endif %}
                            </span>
                        {% endfor %}
''',
    "@endif": "{% endif %}",
    "@else": "{% else %}",
    "{{ ->id }}": "{{ agent.id }}",
    "{{ ->experience_range ?? 'N/A' }}": "{{ agent.experience_range|default:'N/A' }}",
    "{{  ? implode(', ', ) : '' }}": "{{ agent.ordered_insurance_segments|join:', ' }}",
    "{{ ->city ?? 'N/A' }}": "{{ profile.city|default:'N/A' }}",
    "{{  }}": "{{ agent_slug }}",
    "{{ ->mobile }}": "{{ agent.mobile }}",
    "{{ route('agent.profile', ) }}": "{% url 'home:agent_profile' agent_slug %}",
    "{{  }}": "{{ whatsapp_raw }}",
    "{{  }}": "{{ whatsapp_digits }}"
}

for old, new in replacements.items():
    html = html.replace(old, new)

with open(r'c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent\templates\partials\agent-card-converted-2.html', 'w', encoding='utf-8') as f:
    f.write(html)
