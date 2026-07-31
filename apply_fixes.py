import os

base_dir = r"c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent"

# 1. Fix find-agents.html (remove rogue } and fix missing mobile CSS properties)
find_agents_file = os.path.join(base_dir, "templates", "public", "find-agents.html")
with open(find_agents_file, "r", encoding="utf-8") as f:
    content = f.read()

# Fix rogue brace
content = content.replace("    /* --- Sticky Filter FAB --- */\n    }\n\n    /* --- Mobile Filter Floating Card",
                          "    /* --- Sticky Filter FAB --- */\n\n    /* --- Mobile Filter Floating Card")

# Replace the find-agents-filter-wrapper CSS
old_css = """        .find-agents-filter-wrapper {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            width: 100% !important;
            min-width: 100% !important;
            height: auto !important;
            max-height: 92vh !important;
            background: #ffffff !important; 
            z-index: 10001 !important;
            border-radius: 28px 28px 0 0 !important;
            border: 2px solid #047857 !important;
            border-bottom: none !important;
            box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.6) !important;
            transform: translateY(115%);
            transition: transform 0.4s cubic-bezier(0.165, 0.84, 0.44, 1) !important;
        }"""

new_css = """        .find-agents-filter-wrapper {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            width: 100% !important;
            min-width: 100% !important;
            height: auto !important;
            max-height: 92vh !important;
            background: #ffffff !important; 
            z-index: 10001 !important;
            border-radius: 28px 28px 0 0 !important;
            border: 2px solid #047857 !important;
            border-bottom: none !important;
            box-shadow: 0 -10px 40px rgba(0, 0, 0, 0.6) !important;
            transform: translateY(115%);
            transition: transform 0.4s cubic-bezier(0.165, 0.84, 0.44, 1) !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
            margin: 0 !important;
            pointer-events: auto !important;
        }"""

content = content.replace(old_css, new_css)

with open(find_agents_file, "w", encoding="utf-8") as f:
    f.write(content)


# 2. Fix agent-card.html
agent_card_file = os.path.join(base_dir, "templates", "partials", "agent-card.html")
with open(agent_card_file, "r", encoding="utf-8") as f:
    content = f.read()

old_html = """                {% if agent.ordered_insurance_segments %}
                    <div class="rac-tags">
                        {% for seg in agent.ordered_insurance_segments|slice:":4" %}
                            <span class="rac-tag {% if 'health' in seg %}rac-tag--health{% elif 'life' in seg %}rac-tag--life{% elif 'motor' in seg %}rac-tag--motor{% elif 'sme' in seg %}rac-tag--sme{% else %}rac-tag--default{% endif %}">
                                <i class="fas {% if 'health' in seg %}fa-heartbeat{% elif 'life' in seg %}fa-user-shield{% elif 'motor' in seg %}fa-car{% elif 'sme' in seg %}fa-store{% else %}fa-shield-alt{% endif %}" style="font-size: 8px; margin-right: 3px;"></i>
                                {% if seg == 'sme' %}SME{% else %}{{ seg|capfirst }}{% endif %}
                            </span>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>

            <div class="rac-stats-col">
                
                <div class="rac-stat">
                    <span class="rac-stat-num">{{ exp_years }}+</span>
                    <span class="rac-stat-lbl">yrs exp</span>
                </div>
                <div class="rac-stat">
                    <span class="rac-stat-num">{{ agent.formatted_client_base }}</span>
                    <span class="rac-stat-lbl">clients</span>
                </div>
                <div class="rac-stat">
                    <span class="rac-stat-num">{{ performance.formatted_claims_processed|default:"0" }}</span>
                    <span class="rac-stat-lbl">claims</span>
                </div>
            </div>
        </div>"""

new_html = """                <div class="rac-stats-grid" style="margin-top: 8px;">
                    <div class="rac-stat-box">
                        <div class="rac-stat-num">{{ exp_years }}+</div>
                        <div class="rac-stat-lbl">YEARS</div>
                    </div>
                    <div class="rac-stat-box">
                        <div class="rac-stat-num">{{ agent.formatted_client_base }}</div>
                        <div class="rac-stat-lbl">CLIENTS</div>
                    </div>
                    <div class="rac-stat-box">
                        <div class="rac-stat-num">₹{{ performance.formatted_claims_amount|default:"0" }}</div>
                        <div class="rac-stat-lbl">CLAIMS</div>
                    </div>
                    <div class="rac-stat-box">
                        <div class="rac-stat-num">{{ performance.formatted_claims_processed|default:"0" }}</div>
                        <div class="rac-stat-lbl">SETTLED</div>
                    </div>
                </div>

                {% if agent.ordered_insurance_segments %}
                    <div class="rac-tags" style="margin-top: 10px; flex-wrap: nowrap;">
                        {% for seg in agent.ordered_insurance_segments|slice:":4" %}
                            <span class="rac-tag {% if 'health' in seg %}rac-tag--health{% elif 'life' in seg %}rac-tag--life{% elif 'motor' in seg %}rac-tag--motor{% elif 'sme' in seg %}rac-tag--sme{% else %}rac-tag--default{% endif %}">
                                <i class="fas {% if 'health' in seg %}fa-heartbeat{% elif 'life' in seg %}fa-user-shield{% elif 'motor' in seg %}fa-car{% elif 'sme' in seg %}fa-store{% else %}fa-shield-alt{% endif %}" style="font-size: 8px; margin-right: 3px;"></i>
                                {% if seg == 'sme' %}SME{% else %}{{ seg|capfirst }}{% endif %}
                            </span>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>
        </div>"""

content = content.replace(old_html, new_html)

with open(agent_card_file, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixes applied successfully!")
