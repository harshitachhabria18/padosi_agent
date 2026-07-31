import re

file_path = r'c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent\templates\partials\agent-card.html'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove match pill from rac-stats-col (mobile)
content = re.sub(
    r'{% if request\.GET\.pincode[^}]*%}[ \t\n\r]*<div class=\"rac-stat rac-stat--match.*?</div>[ \t\n\r]*{% endif %}',
    '',
    content,
    flags=re.DOTALL
)

# 2. Re-wrap dist-pill and add match pill (mobile)
dist_pill_html = '''                {% if has_distance or request.GET.pincode or request.GET.location or request.GET.lat or request.session.last_pincode or request.session.last_lat %}
                    <div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:2px;">
                        {% if has_distance %}
                            <div class="rac-dist-pill">
                                <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none"
                                    stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                    <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
                                    <circle cx="12" cy="10" r="3" />
                                </svg>
                                {% if display_dist < 1 %}
                                    Nearby
                                {% elif display_dist > 100 %}
                                    <span style="color:#b45309;font-weight:700;">?? Far Away</span>
                                {% else %}
                                    {{ display_dist|floatformat:1 }}km away
                                {% endif %}
                            </div>
                        {% endif %}

                        {% if request.GET.pincode or request.GET.location or request.GET.lat or request.session.last_pincode or request.session.last_lat or request.session.last_location %}
                            <div class="rac-match-pill {% if calculated_match_percent > 90 %}rac-match--green{% elif calculated_match_percent >= 51 %}rac-match--amber{% else %}rac-match--red{% endif %}">
                                <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                                    <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                                </svg>
                                <span>{{ calculated_match_percent }}% Match</span>
                            </div>
                        {% endif %}
                    </div>
                {% endif %}'''

content = re.sub(
    r'{% if has_distance %}\s*<div class="rac-dist-pill">.*?</div>\s*{% endif %}',
    dist_pill_html,
    content,
    flags=re.DOTALL
)


# Add CSS for rac-match-pill
match_css = '''        .rac-match-pill {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 3px 6px;
            border-radius: 12px;
            font-size: 9.5px;
            font-weight: 700;
            line-height: 1;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .rac-match--green { background: #f0fdf4; color: #16a34a; border-color: #bbf7d0; }
        .rac-match--amber { background: #fffbeb; color: #d97706; border-color: #fde68a; }
        .rac-match--red { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
'''

if '.rac-match-pill' not in content:
    content = content.replace('.rac-dist-pill {', match_css + '\n        .rac-dist-pill {')


with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated agent-card.html")
