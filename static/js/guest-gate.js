/**
 * Guest Gate and Lead Capture
 * 
 * Reusable flow for collecting lead information (Name, Email, Mobile)
 * when a guest user tries to contact an agent (via Call or WhatsApp).
 * 
 * Dependencies: SweetAlert2 (Swal), jQuery ($)
 * Relies on window.PADOSI_GLOBALS for Django template values.
 */

window.showQuickRegisterPopup = function(redirectUrl, onSuccessCallback) {
    if (Swal.isVisible()) return;

    const isMobilePopup = window.matchMedia('(max-width: 576px)').matches;

    let welcomeHtml = `
        <div class="swal-welcome-content" style="font-family: 'Urbanist', sans-serif; text-align: left;">
            <div class="guest-gate-brand" style="text-align: center;">
                <img src="${window.PADOSI_GLOBALS.logoUrl}" alt="PadosiAgent" style="width: 120px; display: block; margin: 0 auto 10px;">
            </div>
            <h3 class="guest-gate-heading" style="font-size: 22px; font-weight: 800; color: #1e3a8a; text-align: center; margin-top: 15px; margin-bottom: 5px;">Welcome to PadosiAgent! 👋</h3>
            <p class="guest-gate-subtext" style="color: #64748b; font-size: 13px; text-align: center; margin-bottom: 20px;">
                "Agents can serve you better when they are your Padosi"
            </p>

            <div id="swal-error-container" class="alert alert-danger d-none" style="font-size: 13px; padding: 10px; border-radius: 8px; margin-bottom: 15px; border: none; background-color: #fef2f2; color: #991b1b; text-align: left;">
                <i class="fas fa-exclamation-circle mr-2"></i> <span id="swal-error-message"></span>
            </div>

            <div class="guest-gate-form">
                <div class="guest-gate-group" style="margin-bottom: 15px;">
                    <label class="guest-gate-label" style="font-weight: 700; font-size: 12px; color: #475569; display: block; margin-bottom: 5px;">
                        <i class="far fa-user mr-2"></i> Name *
                    </label>
                    <input type="text" id="swal-fullname" class="form-control guest-gate-input" placeholder="Enter your full name" style="height: 48px; border-radius: 12px; border: 1.5px solid #cbd5e1; outline: none; padding: 10px 14px; font-size: 14px; font-weight: 600; width: 100%;">
                </div>
                
                <div class="guest-gate-group" style="margin-bottom: 15px;">
                    <label class="guest-gate-label" style="font-weight: 700; font-size: 12px; color: #475569; display: block; margin-bottom: 5px;">
                        <i class="far fa-envelope mr-2"></i> Email *
                    </label>
                    <input type="email" id="swal-email" class="form-control guest-gate-input" placeholder="your.email@example.com" style="height: 48px; border-radius: 12px; border: 1.5px solid #cbd5e1; outline: none; padding: 10px 14px; font-size: 14px; font-weight: 600; width: 100%;">
                </div>
                
                <div class="guest-gate-group" style="margin-bottom: 20px;">
                    <label class="guest-gate-label" style="font-weight: 700; font-size: 12px; color: #475569; display: block; margin-bottom: 5px;">
                        <i class="fas fa-phone-volume mr-2"></i> Mobile Number *
                    </label>
                    <div class="guest-gate-mobile-wrap" style="position: relative; display: flex; align-items: center; border: 1.5px solid #cbd5e1; border-radius: 12px; height: 48px; overflow: hidden; background: #fff; width: 100%;">
                        <span class="guest-gate-prefix" style="padding: 0 14px; background: #f1f5f9; border-right: 1.5px solid #cbd5e1; font-weight: 700; color: #475569; font-size: 14px; height: 100%; display: flex; align-items: center;">+91</span>
                        <input type="tel" id="swal-mobile" class="form-control guest-gate-mobile" placeholder="98765 43210" maxlength="10" inputmode="numeric" oninput="this.value = this.value.replace(/[^0-9]/g, '')" style="flex: 1; border: none; outline: none; padding: 0 14px; font-size: 14px; font-weight: 600; background: transparent; height: 100%;">
                    </div>
                </div>
                
                <input type="hidden" id="swal-pincode" value="${new URLSearchParams(window.location.search).get('pincode') || ''}">
            </div>
        </div>
    `;

    Swal.fire({
        title: '',
        html: welcomeHtml,
        showCancelButton: false,
        confirmButtonText: 'Get Started',
        confirmButtonColor: '#273c8e',
        padding: isMobilePopup ? '0.75rem' : '1.25rem',
        width: isMobilePopup ? '88vw' : '430px',
        customClass: {
            popup: 'guest-gate-popup',
            confirmButton: 'btn btn-primary btn-lg rounded-pill px-5 w-100',
            title: 'p-0 mb-2'
        },
        preConfirm: () => {
            const fullname = $('#swal-fullname').val().trim();
            const email = $('#swal-email').val().trim();
            const mobile = $('#swal-mobile').val().trim();
            const pincode = $('#swal-pincode').val().trim();

            const showError = (msg) => {
                $('#swal-error-message').text(msg);
                $('#swal-error-container').removeClass('d-none').hide().fadeIn();
                setTimeout(() => {
                    $('#swal-error-container').fadeOut(function() {
                        $(this).addClass('d-none');
                    });
                }, 3000);
            };

            $('#swal-error-container').addClass('d-none');

            if (!fullname) { showError('Full Name is required'); return false; }
            if (!email) { showError('Email Address is required'); return false; }
            if (!/^\S+@\S+\.\S+$/.test(email)) { showError('Please enter a valid email address'); return false; }
            if (!mobile) { showError('Mobile Number is required'); return false; }
            if (mobile.length < 10) { showError('Please enter a valid 10-digit mobile number'); return false; }

            return { fullname, email, mobile, pincode };
        },
        allowOutsideClick: true,
        allowEscapeKey: true,
        backdrop: `rgba(0,0,0,0.6)`
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Connecting you...',
                allowOutsideClick: false,
                allowEscapeKey: false,
                didOpen: () => {
                    Swal.showLoading();
                    $.ajax({
                        url: window.PADOSI_GLOBALS.quickRegisterUrl,
                        type: "POST",
                        headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                        contentType: "application/json",
                        dataType: "json",
                        timeout: 30000,
                        data: JSON.stringify({
                            ...result.value,
                            redirect_url: redirectUrl || (function() {
                                var u = new URL(window.location.href);
                                u.searchParams.set('openFilter', '1');
                                return u.pathname + u.search;
                            })()
                        }),
                        success: function(response) {
                            if (response.status === 'success' || response.success) {
                                Swal.fire({
                                    icon: 'success',
                                    title: 'Welcome!',
                                    text: 'We found matching agents for you.',
                                    timer: 2500,
                                    showConfirmButton: false,
                                    padding: '2rem'
                                }).then(() => {
                                    if (typeof onSuccessCallback === 'function') {
                                        onSuccessCallback(response);
                                    } else {
                                        window.location.reload();
                                    }
                                });
                            } else {
                                Swal.fire('Oops!', response.message || 'Something went wrong. Please try again.', 'warning');
                            }
                        },
                        error: function(xhr) {
                            const message = xhr.status === 0
                                ? 'Request timed out. Please check your internet and try again.'
                                : (xhr.responseJSON ? xhr.responseJSON.message : 'An error occurred');
                            Swal.fire('Oops!', message || 'We couldn\'t process that. Please refresh and try again.', 'warning');
                        }
                    });
                }
            });
        }
    });
};

window.proceedToDestination = function(url, target) {
    if (target === '_blank') {
        window.open(url, '_blank', 'noopener');
        return;
    }
    window.location.href = url;
};

// Extracted from find-agents.html to be shared across pages (like Chatbot widget)
window.handleAgentContactClick = function(event, element, interactionType, skipReload) {
    if (!element) return true;
    if (event) event.preventDefault();

    const isAuth = window.PADOSI_GLOBALS.isAuthenticated;
    const agentId = element.getAttribute('data-agent-id');
    const serviceType = element.getAttribute('data-service-type') || '';
    const insuranceType = element.getAttribute('data-insurance-type') || '';
    const insuranceCompany = element.getAttribute('data-insurance-company') || '';
    const target = element.getAttribute('target');

    const captureLeadAndProceed = (guestData) => {
        var postData = {
            agent_id: agentId,
            interaction_type: interactionType,
            service_type: serviceType,
            insurance_type: insuranceType,
            insurance_company: insuranceCompany,
            source_page: window.location.pathname
        };

        if (guestData) {
            postData.fullname = guestData.fullname;
            postData.email = guestData.email;
            postData.mobile = guestData.mobile;
        }

        const captureLead = function() {
            $.ajax({
                url: window.PADOSI_GLOBALS.leadsCaptureUrl,
                type: "POST",
                headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                data: postData,
                success: function(resp) {
                    Swal.close();
                    if (resp.success && resp.url && resp.url !== '#') {
                        window.proceedToDestination(resp.url, target);
                        if (!skipReload) { setTimeout(() => { window.location.reload(); }, 1500); }
                    } else if (resp.message) {
                        const errMsg = resp.message || 'This agent has not provided contact details for this format.';
                        Swal.fire('Notice', errMsg, 'info').then(() => { if (!skipReload) window.location.reload(); });
                    } else {
                        if (!skipReload) window.location.reload();
                    }
                },
                error: function(xhr) {
                    Swal.close();
                    let msg = 'Something went wrong. Please refresh the page and try again.';
                    if (xhr.status === 403) {
                        msg = 'Access denied. Suspicious activity has been detected from your IP.';
                    }
                    Swal.fire('Oops!', msg, 'warning').then(() => { if (!skipReload) window.location.reload(); });
                }
            });
        };

        Swal.fire({
            title: 'Connecting you...',
            allowOutsideClick: false,
            didOpen: () => {
                Swal.showLoading();
                if (!isAuth && guestData) {
                    $.ajax({
                        url: window.PADOSI_GLOBALS.quickRegisterUrl,
                        type: "POST",
                        headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                        contentType: "application/json",
                        dataType: "json",
                        data: JSON.stringify(guestData),
                        success: function() {
                            captureLead();
                        },
                        error: function() {
                            Swal.close();
                            Swal.fire('Almost there!', 'We had a small hiccup during registration. Please try again.', 'info');
                        }
                    });
                } else {
                    captureLead();
                }
            }
        });
    };

    if (!isAuth) {
        window.showQuickRegisterPopup(window.location.pathname + window.location.search, function(response) {
            var postData = {
                agent_id: agentId,
                interaction_type: interactionType,
                service_type: serviceType,
                insurance_type: insuranceType,
                insurance_company: insuranceCompany,
                source_page: window.location.pathname
            };
            
            Swal.fire({
                title: 'Connecting you...',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    $.ajax({
                        url: window.PADOSI_GLOBALS.leadsCaptureUrl,
                        type: "POST",
                        headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                        data: postData,
                        success: function(resp) {
                            Swal.close();
                            if (resp.success && resp.url && resp.url !== '#') {
                                window.proceedToDestination(resp.url, target);
                                if (!skipReload) { setTimeout(() => { window.location.reload(); }, 1500); }
                            } else if (resp.message) {
                                const errMsg = resp.message || 'This agent has not provided contact details for this format.';
                                Swal.fire('Notice', errMsg, 'info').then(() => { if (!skipReload) window.location.reload(); });
                            } else {
                                if (!skipReload) window.location.reload();
                            }
                        },
                        error: function() {
                            Swal.close();
                            if (!skipReload) window.location.reload();
                        }
                    });
                }
            });
        });
    } else {
        captureLeadAndProceed();
    }
};

window.showChatbotQuickRegisterPopup = function(redirectUrl, onSuccessCallback) {
    if (Swal.isVisible()) return;

    const isMobilePopup = window.matchMedia('(max-width: 576px)').matches;

    let welcomeHtml = `
        <div class="swal-welcome-content" style="font-family: 'Urbanist', sans-serif; text-align: left;">
            <div class="guest-gate-brand" style="text-align: center;">
                <img src="${window.PADOSI_GLOBALS.logoUrl}" alt="PadosiAgent" style="width: 120px; display: block; margin: 0 auto 10px;">
            </div>
            <h3 class="guest-gate-heading" style="font-size: 22px; font-weight: 800; color: #1e3a8a; text-align: center; margin-top: 15px; margin-bottom: 5px;">Welcome to PadosiAgent! 👋</h3>
            <p class="guest-gate-subtext" style="color: #64748b; font-size: 13px; text-align: center; margin-bottom: 20px;">
                "Agents can serve you better when they are your Padosi"
            </p>

            <div id="swal-error-container" class="alert alert-danger d-none" style="font-size: 13px; padding: 10px; border-radius: 8px; margin-bottom: 15px; border: none; background-color: #fef2f2; color: #991b1b; text-align: left;">
                <i class="fas fa-exclamation-circle mr-2"></i> <span id="swal-error-message"></span>
            </div>

            <div class="guest-gate-form">
                <div class="guest-gate-group" style="margin-bottom: 15px;">
                    <label class="guest-gate-label" style="font-weight: 700; font-size: 12px; color: #475569; display: block; margin-bottom: 5px;">
                        <i class="far fa-user mr-2"></i> Name *
                    </label>
                    <input type="text" id="swal-fullname" class="form-control guest-gate-input" placeholder="Enter your full name" style="height: 48px; border-radius: 12px; border: 1.5px solid #cbd5e1; outline: none; padding: 10px 14px; font-size: 14px; font-weight: 600; width: 100%;">
                </div>
                
                <div class="guest-gate-group" style="margin-bottom: 20px;">
                    <label class="guest-gate-label" style="font-weight: 700; font-size: 12px; color: #475569; display: block; margin-bottom: 5px;">
                        <i class="fas fa-phone-volume mr-2"></i> Mobile Number *
                    </label>
                    <div class="guest-gate-mobile-wrap" style="position: relative; display: flex; align-items: center; border: 1.5px solid #cbd5e1; border-radius: 12px; height: 48px; overflow: hidden; background: #fff; width: 100%;">
                        <span class="guest-gate-prefix" style="padding: 0 14px; background: #f1f5f9; border-right: 1.5px solid #cbd5e1; font-weight: 700; color: #475569; font-size: 14px; height: 100%; display: flex; align-items: center;">+91</span>
                        <input type="tel" id="swal-mobile" class="form-control guest-gate-mobile" placeholder="98765 43210" maxlength="10" inputmode="numeric" oninput="this.value = this.value.replace(/[^0-9]/g, '')" style="flex: 1; border: none; outline: none; padding: 0 14px; font-size: 14px; font-weight: 600; background: transparent; height: 100%;">
                    </div>
                </div>
                
                <input type="hidden" id="swal-pincode" value="${new URLSearchParams(window.location.search).get('pincode') || ''}">
            </div>
        </div>
    `;

    Swal.fire({
        title: '',
        html: welcomeHtml,
        showCancelButton: false,
        confirmButtonText: 'Get Started',
        confirmButtonColor: '#273c8e',
        padding: isMobilePopup ? '0.75rem' : '1.25rem',
        width: isMobilePopup ? '88vw' : '430px',
        customClass: {
            popup: 'guest-gate-popup swal-chatbot-zindex',
            confirmButton: 'btn btn-primary btn-lg rounded-pill px-5 w-100',
            title: 'p-0 mb-2'
        },
        preConfirm: () => {
            const fullname = $('#swal-fullname').val().trim();
            const mobile = $('#swal-mobile').val().trim();
            const pincode = $('#swal-pincode').val().trim();
            const email = ''; // Sent as blank so backend generates synthetic email

            const showError = (msg) => {
                $('#swal-error-message').text(msg);
                $('#swal-error-container').removeClass('d-none').hide().fadeIn();
                setTimeout(() => {
                    $('#swal-error-container').fadeOut(function() {
                        $(this).addClass('d-none');
                    });
                }, 3000);
            };

            $('#swal-error-container').addClass('d-none');

            if (!fullname) { showError('Full Name is required'); return false; }
            if (!mobile) { showError('Mobile Number is required'); return false; }
            if (mobile.length < 10) { showError('Please enter a valid 10-digit mobile number'); return false; }

            return { fullname, email, mobile, pincode };
        },
        allowOutsideClick: true,
        allowEscapeKey: true,
        backdrop: `rgba(0,0,0,0.6)`
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Connecting you...',
                allowOutsideClick: false,
                allowEscapeKey: false,
                customClass: {
                    popup: 'swal-chatbot-zindex'
                },
                didOpen: () => {
                    Swal.showLoading();
                    $.ajax({
                        url: window.PADOSI_GLOBALS.quickRegisterUrl,
                        type: "POST",
                        headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                        contentType: "application/json",
                        dataType: "json",
                        timeout: 30000,
                        data: JSON.stringify({
                            ...result.value,
                            redirect_url: redirectUrl || window.location.href
                        }),
                        success: function(response) {
                            if (response.status === 'success' || response.success) {
                                // Mark authenticated state locally so further clicks bypass registration
                                window.PADOSI_GLOBALS.isAuthenticated = true;
                                Swal.fire({
                                    icon: 'success',
                                    title: 'Welcome!',
                                    text: 'We found matching agents for you.',
                                    timer: 2500,
                                    showConfirmButton: false,
                                    padding: '2rem',
                                    customClass: { popup: 'swal-chatbot-zindex' }
                                }).then(() => {
                                    if (typeof onSuccessCallback === 'function') {
                                        onSuccessCallback(response);
                                    }
                                });
                            } else {
                                Swal.fire({
                                    title: 'Oops!', 
                                    text: response.message || 'Something went wrong. Please try again.', 
                                    icon: 'warning',
                                    customClass: { popup: 'swal-chatbot-zindex' }
                                });
                            }
                        },
                        error: function(xhr) {
                            const message = xhr.status === 0
                                ? 'Request timed out. Please check your internet and try again.'
                                : (xhr.responseJSON ? xhr.responseJSON.message : 'An error occurred');
                            Swal.fire({
                                title: 'Oops!', 
                                text: message || 'We couldn\'t process that. Please refresh and try again.', 
                                icon: 'warning',
                                customClass: { popup: 'swal-chatbot-zindex' }
                            });
                        }
                    });
                }
            });
        }
    });
};

window.handleChatbotAgentContactClick = function(event, element, interactionType) {
    if (!element) return true;
    if (event) event.preventDefault();

    const isAuth = window.PADOSI_GLOBALS.isAuthenticated;
    const agentId = element.getAttribute('data-agent-id');
    const serviceType = element.getAttribute('data-service-type') || '';
    const insuranceType = element.getAttribute('data-insurance-type') || '';
    const insuranceCompany = element.getAttribute('data-insurance-company') || '';
    const target = element.getAttribute('target');

    const captureLeadAndProceed = () => {
        var postData = {
            agent_id: agentId,
            interaction_type: interactionType,
            service_type: serviceType,
            insurance_type: insuranceType,
            insurance_company: insuranceCompany,
            source_page: window.location.pathname
        };

        Swal.fire({
            title: 'Connecting you...',
            allowOutsideClick: false,
            customClass: { popup: 'swal-chatbot-zindex' },
            didOpen: () => {
                Swal.showLoading();
                $.ajax({
                    url: window.PADOSI_GLOBALS.leadsCaptureUrl,
                    type: "POST",
                    headers: { 'X-CSRFToken': window.PADOSI_GLOBALS.csrfToken },
                    data: postData,
                    success: function(resp) {
                        Swal.close();
                        if (resp.success && resp.url && resp.url !== '#') {
                            window.proceedToDestination(resp.url, target);
                        } else if (resp.message) {
                            const errMsg = resp.message || 'This agent has not provided contact details for this format.';
                            Swal.fire({title: 'Notice', text: errMsg, icon: 'info', customClass: { popup: 'swal-chatbot-zindex' }});
                        }
                    },
                    error: function(xhr) {
                        Swal.close();
                        let msg = 'Something went wrong. Please refresh the page and try again.';
                        if (xhr.status === 403) {
                            msg = 'Access denied. Suspicious activity has been detected from your IP.';
                        }
                        Swal.fire({title: 'Oops!', text: msg, icon: 'warning', customClass: { popup: 'swal-chatbot-zindex' }});
                    }
                });
            }
        });
    };

    if (!isAuth) {
        window.showChatbotQuickRegisterPopup(window.location.pathname + window.location.search, function(response) {
            captureLeadAndProceed();
        });
    } else {
        captureLeadAndProceed();
    }
};
