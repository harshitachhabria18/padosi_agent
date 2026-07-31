document.addEventListener('DOMContentLoaded', () => {
    const triggerBtn = document.getElementById('chatbot-trigger');
    const closeBtn = document.getElementById('chatbot-close');
    const panel = document.getElementById('chatbot-panel');
    const input = document.getElementById('chatbot-input');
    const sendBtn = document.getElementById('chatbot-send');
    const messagesContainer = document.getElementById('chatbot-messages');
    const suggestionsContainer = document.getElementById('chatbot-suggestions');
    let chips = document.querySelectorAll('.chatbot-chip');

    if (!triggerBtn || !panel) return; // fail gracefully if not on page

    let sessionId = localStorage.getItem('chatbot_session_id') || "";

    const loadChips = () => {
        fetch('/api/chatbot/chips/')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.data && suggestionsContainer) {
                    suggestionsContainer.innerHTML = '';
                    data.data.forEach(chipText => {
                        const chip = document.createElement('button');
                        chip.className = 'chatbot-chip';
                        chip.textContent = chipText;
                        chip.addEventListener('click', (e) => {
                            sendMessage(e.target.textContent);
                        });
                        suggestionsContainer.appendChild(chip);
                    });
                }
            }).catch(err => console.error("Error loading chips", err));
    };

    const loadHistory = async () => {
        if (!sessionId) {
            loadChips();
            return;
        }
        try {
            const res = await fetch(`/api/chatbot/history/${sessionId}/`);
            const data = await res.json();
            if (data.success && data.data && data.data.length > 0) {
                // Clear welcome message and chips
                messagesContainer.innerHTML = ''; 
                
                data.data.forEach(msg => {
                    const msgDiv = document.createElement('div');
                    msgDiv.className = `chatbot-message ${msg.role === 'user' ? 'user-message' : 'bot-message'}`;
                    if (msg.role === 'assistant') {
                        let htmlContent = msg.content.replace(/\n/g, '<br>');
                        htmlContent = htmlContent.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color: #2563eb; text-decoration: underline; font-weight: 500;">$1</a>');
                        msgDiv.innerHTML = htmlContent;
                    } else {
                        msgDiv.textContent = msg.content;
                    }
                    messagesContainer.appendChild(msgDiv);
                    
                    if (msg.role === 'assistant') {
                        renderBotExtras(msgDiv, msg.agent_links, null, null, msg.agent_cards);
                    }
                });
                
                // Scroll to bottom
                messagesContainer.scrollTop = messagesContainer.scrollHeight;
            } else {
                loadChips();
            }
        } catch (err) {
            console.error("Error loading history", err);
            loadChips();
        }
    };

    loadHistory();

    const newChatBtn = document.getElementById('chatbot-header-icon');
    if (newChatBtn) {
        newChatBtn.addEventListener('click', () => {
            sessionId = 'session_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('chatbot_session_id', sessionId);
            
            messagesContainer.innerHTML = `
                <div class="chatbot-message bot-message">
                    Hi! I'm PadosiAgent Assistant. Ask me anything about insurance, investments, or finding the right agent.
                </div>
                <div class="chatbot-suggestions" id="chatbot-suggestions"></div>
            `;
            
            setTimeout(() => {
                const newSuggestions = document.getElementById('chatbot-suggestions');
                fetch('/api/chatbot/chips/')
                    .then(res => res.json())
                    .then(data => {
                        if (data.success && data.data && newSuggestions) {
                            newSuggestions.innerHTML = '';
                            data.data.forEach(chipText => {
                                const chip = document.createElement('button');
                                chip.className = 'chatbot-chip';
                                chip.textContent = chipText;
                                chip.addEventListener('click', (e) => {
                                    sendMessage(e.target.textContent);
                                });
                                newSuggestions.appendChild(chip);
                            });
                        }
                    }).catch(err => console.error("Error loading chips", err));
            }, 0);
        });
    }

    // Toggle panel
    triggerBtn.addEventListener('click', () => {
        panel.classList.remove('hidden');
        triggerBtn.style.display = 'none';
        input.focus();
    });

    closeBtn.addEventListener('click', () => {
        panel.classList.add('hidden');
        setTimeout(() => {
            triggerBtn.style.display = 'flex';
        }, 300); // Wait for transition
    });

    // Auto-scroll
    const scrollToBottom = () => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    };

    // ---- Helper: log a lead (fire-and-forget, no SweetAlert/jQuery dependency) ----
    const logAgentLead = (agentId, interactionType) => {
        // Reuses the existing lead-capture endpoint — same one used by the find-agents page.
        // Fire-and-forget: we don't block navigation on the result.
        fetch('/agent/leads/capture/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ''
            },
            body: new URLSearchParams({
                agent_id: agentId,
                interaction_type: interactionType,
                source_page: '/chatbot-widget'
            })
        }).catch(() => {}); // swallow errors silently — lead logging must never block the user
    };
    // Expose for the inline onclick handlers in renderAgentCards HTML template strings
    window._chatbotLogLead = logAgentLead;

    // ---- Helper: render rich agent cards (new) ----
    const renderAgentCards = (agentCards) => {
        if (!agentCards || agentCards.length === 0) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'chatbot-agent-cards';

        agentCards.forEach(card => {
            const badge = (card.badge || '').toLowerCase();
            const hasBadgeVerified = badge.includes('verified');
            const hasBadgeIrdai = badge.includes('irdai');
            const hasBadgeTrusted = badge.includes('trusted');

            // Match colour
            const matchClass = card.match_percent > 90
                ? 'chatbot-match--green'
                : card.match_percent >= 51
                    ? 'chatbot-match--amber'
                    : 'chatbot-match--red';

            // Stars (integer 0-5)
            const fullStars = Math.floor(card.rating || 0);
            const halfStar = ((card.rating || 0) - fullStars) >= 0.5;
            let starsHtml = '';
            for (let i = 0; i < 5; i++) {
                if (i < fullStars) starsHtml += '<span class="chatbot-star chatbot-star--full">★</span>';
                else if (i === fullStars && halfStar) starsHtml += '<span class="chatbot-star chatbot-star--half">★</span>';
                else starsHtml += '<span class="chatbot-star chatbot-star--empty">★</span>';
            }

            // Segment tags
            const segColour = { health: '#0ea5e9', life: '#8b5cf6', motor: '#f59e0b', sme: '#10b981' };
            const segsHtml = (card.segments || []).map(s => {
                const col = segColour[s.toLowerCase()] || '#64748b';
                const label = s === 'sme' ? 'SME' : (s.charAt(0).toUpperCase() + s.slice(1));
                return `<span class="chatbot-seg-tag" style="background:${col}1a;color:${col};border-color:${col}40">${label}</span>`;
            }).join('');

            // Whatsapp & Call hrefs
            const waHref = card.whatsapp_digits ? `https://wa.me/${card.whatsapp_digits}` : '#';
            const callHref = card.mobile ? `tel:${card.mobile}` : '#';

            const cardEl = document.createElement('div');
            cardEl.className = 'chatbot-agent-card';
            cardEl.innerHTML = `
                <div class="chatbot-ac-header">
                    <img class="chatbot-ac-avatar" src="${card.photo_url || '/static/img/avatar-icon.jpg'}"
                         onerror="this.src='/static/img/avatar-icon.jpg'" alt="${card.name}">
                    <div class="chatbot-ac-info">
                        <div class="chatbot-ac-name">
                            ${card.name}
                            ${hasBadgeVerified ? '<span class="chatbot-ac-badge chatbot-badge--verified">✓ Verified</span>' : ''}
                            ${hasBadgeIrdai ? '<span class="chatbot-ac-badge chatbot-badge--irdai">🏅 Licensed</span>' : ''}
                            ${hasBadgeTrusted ? '<span class="chatbot-ac-badge chatbot-badge--trusted">🏆 Trusted</span>' : ''}
                        </div>
                        <div class="chatbot-ac-stars">
                            ${starsHtml} 
                            <span class="chatbot-ac-rating-val">${(card.rating || 0).toFixed(1)}</span> 
                            <span class="chatbot-ac-review-count">(${card.review_count || 0})</span>
                            ${card.experience_years ? `<span style="margin-left:4px;color:#6b7280;">· ${card.experience_years}+ yrs</span>` : ''}
                        </div>
                    </div>
                    <div class="chatbot-ac-match ${matchClass}">${card.match_percent}%<br><span style="font-size:9px;font-weight:500;opacity:.85">Match</span></div>
                </div>
                ${segsHtml ? `<div class="chatbot-ac-segs">${segsHtml}</div>` : ''}
                <div class="chatbot-ac-actions">
                    <a href="${callHref}" class="chatbot-ac-btn chatbot-ac-btn--call"
                       data-agent-id="${card.agent_id}" data-service-type="${card.service_type || ''}" data-insurance-type="${card.insurance_type || ''}"
                       onclick="window.handleChatbotAgentContactClick && window.handleChatbotAgentContactClick(event, this, 'call')">
                        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13.832 16.568a1 1 0 0 0 1.213-.303l.355-.465A2 2 0 0 1 17 15h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2A18 18 0 0 1 2 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-.8 1.6l-.468.351a1 1 0 0 0-.292 1.233 14 14 0 0 0 6.392 6.384"/></svg>
                        Call
                    </a>
                    <a href="${waHref}" target="_blank" class="chatbot-ac-btn chatbot-ac-btn--wa"
                       data-agent-id="${card.agent_id}" data-service-type="${card.service_type || ''}" data-insurance-type="${card.insurance_type || ''}"
                       onclick="window.handleChatbotAgentContactClick && window.handleChatbotAgentContactClick(event, this, 'whatsapp')">
                        <svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 448 512" width="13" height="13"><path d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-30.3 1.8-3.7.9-6.9-.5-9.7-1.4-2.8-12.5-30.1-17.1-41.2-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z"/></svg>
                        WhatsApp
                    </a>
                    <a href="${card.profile_url}" target="_blank" class="chatbot-ac-btn chatbot-ac-btn--profile">
                        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                        Profile
                    </a>
                </div>
            `;
            wrapper.appendChild(cardEl);
        });

        messagesContainer.appendChild(wrapper);
    };

    // ---- Helper: render agent links + quick options on a bot message ----
    const renderBotExtras = (botMsgDiv, agentLinks, quickOptions, quickOptionGroups, agentCards) => {
        // Agent cards take priority over pills when present
        renderAgentCards(agentCards);

        const hasCards = agentCards && agentCards.length > 0;
        
        if (!hasCards && agentLinks && agentLinks.length > 0) {
            const linksDiv = document.createElement('div');
            linksDiv.className = 'chatbot-quick-options chatbot-suggestions-row';
            linksDiv.style.marginTop = '4px';
            agentLinks.forEach(link => {
                const btn = document.createElement('a');
                btn.className = 'chatbot-agent-link';
                btn.href = link.url;
                btn.target = '_blank';
                btn.innerHTML = `<svg fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" width="14" height="14" style="margin-right: 6px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>${link.name}`;
                linksDiv.appendChild(btn);
            });
            messagesContainer.appendChild(linksDiv);
        }

        if (quickOptions && quickOptions.length > 0) {
            const quickOptionsDiv = document.createElement('div');
            quickOptionsDiv.className = 'chatbot-quick-options chatbot-suggestions-row';
            quickOptionsDiv.style.marginTop = '8px';
            quickOptions.forEach(optText => {
                const chip = document.createElement('button');
                chip.className = 'chatbot-chip';
                chip.textContent = optText;
                chip.addEventListener('click', (e) => { sendMessage(e.target.textContent); });
                quickOptionsDiv.appendChild(chip);
            });
            messagesContainer.appendChild(quickOptionsDiv);
        }

        if (quickOptionGroups && quickOptionGroups.length > 0) {
            quickOptionGroups.forEach(group => {
                if (group.options && group.options.length > 0) {
                    const groupLabel = document.createElement('div');
                    groupLabel.className = 'chatbot-quick-options';
                    groupLabel.style.fontSize = '12px';
                    groupLabel.style.color = '#6b7280';
                    groupLabel.style.marginTop = '8px';
                    groupLabel.style.marginBottom = '4px';
                    groupLabel.style.marginLeft = '4px';
                    groupLabel.textContent = group.group_name || '';
                    messagesContainer.appendChild(groupLabel);

                    const groupDiv = document.createElement('div');
                    groupDiv.className = 'chatbot-quick-options chatbot-suggestions-row';
                    group.options.forEach(optText => {
                        const chip = document.createElement('button');
                        chip.className = 'chatbot-chip';
                        chip.textContent = optText;
                        chip.addEventListener('click', (e) => { sendMessage(e.target.textContent); });
                        groupDiv.appendChild(chip);
                    });
                    messagesContainer.appendChild(groupDiv);
                }
            });
        }
    };


    // ---- Helper: convert raw text to display HTML (newlines + markdown links) ----
    const toDisplayHtml = (text) => {
        let html = text.replace(/\n/g, '<br>');
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color: #2563eb; text-decoration: underline; font-weight: 500;">$1</a>');
        return html;
    };

    // Send message functionality
    const sendMessage = async (text) => {
        if (!text || text.trim() === '') return;

        // Hide suggestions if they exist
        const currentSuggestions = document.getElementById('chatbot-suggestions');
        if (currentSuggestions) {
            currentSuggestions.style.display = 'none';
        }
        
        // Remove old quick options
        const oldOptions = messagesContainer.querySelectorAll('.chatbot-quick-options');
        oldOptions.forEach(opt => opt.remove());

        // Add user message
        const userMsgDiv = document.createElement('div');
        userMsgDiv.className = 'chatbot-message user-message';
        userMsgDiv.textContent = text;
        messagesContainer.appendChild(userMsgDiv);
        scrollToBottom();

        // Add typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'chatbot-message bot-message typing-indicator';
        typingDiv.innerHTML = '<span></span><span></span><span></span>';
        messagesContainer.appendChild(typingDiv);
        scrollToBottom();

        // Bot message div — created once, filled progressively for streaming or all at once for full responses
        const botMsgDiv = document.createElement('div');
        botMsgDiv.className = 'chatbot-message bot-message';

        try {
            const response = await fetch('/api/chatbot/message/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text, session_id: sessionId })
            });

            if (messagesContainer.contains(typingDiv)) {
                messagesContainer.removeChild(typingDiv);
            }
            messagesContainer.appendChild(botMsgDiv);

            if (!response.ok) {
                if (response.status === 429) {
                    botMsgDiv.textContent = "You're sending messages too quickly, please wait a moment and try again.";
                } else {
                    botMsgDiv.textContent = "Something went wrong, please try again.";
                }
                scrollToBottom();
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let sseBuffer = '';
            let streamedText = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                sseBuffer += decoder.decode(value, { stream: true });
                const lines = sseBuffer.split('\n');
                sseBuffer = lines.pop(); // keep any incomplete line buffered

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    let event;
                    try {
                        event = JSON.parse(line.slice(6));
                    } catch (_) { continue; }

                    if (event.type === 'chunk') {
                        // Progressive streaming: append raw text, re-render as display HTML
                        streamedText += event.delta;
                        botMsgDiv.innerHTML = toDisplayHtml(streamedText);
                        scrollToBottom();

                    } else if (event.type === 'done') {
                        if (event.session_id) {
                            sessionId = event.session_id;
                            localStorage.setItem('chatbot_session_id', sessionId);
                        }
                        // Streaming complete: finalise display and attach extras
                        botMsgDiv.innerHTML = toDisplayHtml(event.reply || streamedText);
                        renderBotExtras(botMsgDiv, event.agent_links, event.quick_options, event.quick_option_groups, event.agent_cards);
                        renderDebugInfo(botMsgDiv, event);
                        scrollToBottom();

                    } else if (event.type === 'full_response') {
                        // Tool-call (agent search) path — render exactly as before, all at once
                        if (event.session_id) {
                            sessionId = event.session_id;
                            localStorage.setItem('chatbot_session_id', sessionId);
                        }
                        botMsgDiv.innerHTML = toDisplayHtml(event.reply || '');
                        renderBotExtras(botMsgDiv, event.agent_links, event.quick_options, event.quick_option_groups, event.agent_cards);
                        renderDebugInfo(botMsgDiv, event);
                        scrollToBottom();

                    } else if (event.type === 'error') {
                        botMsgDiv.textContent = event.message || 'Something went wrong.';
                        scrollToBottom();
                    }
                }
            }

        } catch (err) {
            if (messagesContainer.contains(typingDiv)) {
                messagesContainer.removeChild(typingDiv);
            }
            if (!messagesContainer.contains(botMsgDiv)) {
                messagesContainer.appendChild(botMsgDiv);
            }
            botMsgDiv.textContent = 'Error connecting to assistant.';
        }
        scrollToBottom();
    };


    // Input active state
    const updateSendBtnState = () => {
        if (input.value.trim().length > 0) {
            sendBtn.classList.add('send-btn--active');
        } else {
            sendBtn.classList.remove('send-btn--active');
        }
    };

    input.addEventListener('input', updateSendBtnState);

    // Event listeners for sending
    sendBtn.addEventListener('click', () => {
        const text = input.value;
        if (text.trim()) {
            sendMessage(text);
            input.value = '';
            updateSendBtnState();
        }
    });

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const text = input.value;
            if (text.trim()) {
                sendMessage(text);
                input.value = '';
                updateSendBtnState();
            }
        }
    });

    // Chip clicks
    chips.forEach(chip => {
        chip.addEventListener('click', (e) => {
            const text = e.target.textContent;
            sendMessage(text);
        });
    });
});

function renderDebugInfo(container, event) {
    const isDebug = new URLSearchParams(window.location.search).get('debug') === '1' || localStorage.getItem('chatbot_debug') === '1';
    if (!isDebug) return;

    const debugDiv = document.createElement('div');
    debugDiv.style.fontSize = '10px';
    debugDiv.style.color = '#888';
    debugDiv.style.marginTop = '4px';
    debugDiv.style.textAlign = 'right';
    
    let txt = `Total: ${event.total_time ? event.total_time.toFixed(3) : '?'}s`;
    if (event.ttft && event.ttft > 0) {
        txt = `TTFT: ${event.ttft.toFixed(3)}s | ` + txt;
    }
    debugDiv.textContent = txt;
    container.appendChild(debugDiv);
}

// Expose lead-logger globally so the inline onclick handlers in renderAgentCards can reach it.
// The actual function is defined inside DOMContentLoaded scope, so we hook it lazily
// via the widget's own init sequence (see widget.js DOMContentLoaded block).
// This stub is replaced by the real closure once the widget initialises.
window._chatbotLogLead = window._chatbotLogLead || function() {};
