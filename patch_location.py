import re

with open(r'c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent\templates\public\find-agents.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace auto-trigger logic
old_trigger = '''        .ready(function() {
            if (!hasLocation) {
                locationPopupTimer = setTimeout(() => {
                    if (!isFindAgentsPage()) {
                        return;
                    }
                    if (typeof window.showLocationPopup === 'function') {
                        window.showLocationPopup('{% url 'home:find_agents' %}');
                    }
                }, 5000);
            }
        });'''

new_trigger = '''        .ready(function() {
            if (!hasLocation && isFindAgentsPage()) {
                const triggerPincodePopup = () => {
                    if (typeof window.showLocationPopup === 'function' && isFindAgentsPage()) {
                        window.showLocationPopup('{% url 'home:find_agents' %}');
                    }
                };

                if (typeof window.showGpsPopup === 'function') {
                    window.showGpsPopup('{% url 'home:find_agents' %}', () => {
                        if (locationPopupTimer) clearTimeout(locationPopupTimer);
                        locationPopupTimer = setTimeout(triggerPincodePopup, 5000);
                    });
                } else {
                    locationPopupTimer = setTimeout(triggerPincodePopup, 5000);
                }
            }
        });'''

html = html.replace(old_trigger, new_trigger)

gps_popup_js = '''
        window.showGpsPopup = function(baseUrl, onDismiss) {
            if (Swal.isVisible()) return;
            if (typeof window.closeMobileFilter === 'function') window.closeMobileFilter();
            const isMobilePopup = window.matchMedia('(max-width: 576px)').matches;
            let isRedirecting = false;

            Swal.fire({
                title: '',
                html: 
                    <div class="swal-welcome-content" style="font-family: 'Urbanist', sans-serif;">
                        <div class="guest-gate-brand" style="text-align: center;">
                            <img src="{% static 'img/logo.png' %}" alt="PadosiAgent" style="width: 120px; display: block; margin: 0 auto 10px;">
                        </div>
                        <h3 class="guest-gate-heading" style="font-size: 22px; font-weight: 800; color: #1e3a8a; text-align: center; margin-top: 15px; margin-bottom: 5px;">Find Agents Near You</h3>
                        <p class="guest-gate-subtext" style="color: #64748b; font-size: 13px; text-align: center; margin-bottom: 20px;">"Agents can serve you better when they are your Padosi"</p>
                        <div class="guest-gate-form mt-4">
                            <div id="swal-error-container-gps" class="alert alert-danger d-none" style="font-size: 13px; padding: 10px; border-radius: 8px; margin-bottom: 15px; border: none; background-color: #fef2f2; color: #991b1b; text-align: left;">
                                <i class="fas fa-exclamation-circle mr-2"></i> <span id="swal-error-message-gps"></span>
                            </div>
                            <div class="padosi-location-flow mt-2" style="font-family: 'Urbanist', sans-serif;">
                                <button id="allow-gps-btn" type="button" style="width: 100%; height: 60px; background: #fff; color: #273c8e; border: 2px solid #273c8e; border-radius: 16px; font-weight: 700; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 10px; transition: all 0.3s;">
                                    <i class="fas fa-location-arrow"></i> Use Current Location
                                </button>
                            </div>
                        </div>
                    </div>
                ,
                showConfirmButton: false,
                showCancelButton: true,
                cancelButtonText: 'Cancel',
                focusConfirm: false,
                padding: isMobilePopup ? '1rem' : '1.5rem',
                width: isMobilePopup ? '92vw' : '450px',
                customClass: { 
                    popup: 'guest-gate-popup',
                    cancelButton: 'btn btn-outline-secondary rounded-pill px-4 mt-2'
                },
                buttonsStyling: false,
                didOpen: () => {
                    let gpsRequestActive = false;
                    #allow-gps-btn.on('click', function() {
                        if (gpsRequestActive) return;
                        gpsRequestActive = true;
                        const btn = ;
                        const origHtml = btn.html();
                        btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Accessing GPS...');

                        if (!navigator.geolocation) {
                            #swal-error-message-gps.text('Geolocation is not supported by your browser.');
                            #swal-error-container-gps.removeClass('d-none');
                            btn.prop('disabled', false).html(origHtml);
                            gpsRequestActive = false;
                            return;
                        }

                        navigator.geolocation.getCurrentPosition((pos) => {
                            isRedirecting = true;
                            let targetUrl;
                            try {
                                targetUrl = new URL(baseUrl, window.location.origin);
                            } catch(err) {
                                targetUrl = new URL(window.location.origin + baseUrl);
                            }
                            targetUrl.searchParams.set('lat', pos.coords.latitude);
                            targetUrl.searchParams.set('lng', pos.coords.longitude);
                            targetUrl.searchParams.delete('page');
                            window.location.href = targetUrl.toString();
                        }, (err) => {
                            let errorMsg = 'Location access denied.';
                            if (err.code === err.PERMISSION_DENIED) errorMsg = 'Permission denied. Please enable location access.';
                            else if (err.code === err.POSITION_UNAVAILABLE) errorMsg = 'Location information is unavailable.';
                            else if (err.code === err.TIMEOUT) errorMsg = 'Location request timed out.';
                            #swal-error-message-gps.text(errorMsg);
                            #swal-error-container-gps.removeClass('d-none');
                            btn.prop('disabled', false).html(origHtml);
                            gpsRequestActive = false;
                            setTimeout(() => { Swal.close(); }, 1500);
                        }, { timeout: 10000 });
                    });
                }
            }).then((result) => {
                if (!isRedirecting && typeof onDismiss === 'function') {
                    onDismiss();
                }
            });
        };

        window.showLocationPopup = function(baseUrl) {
'''

html = html.replace('window.showLocationPopup = function(baseUrl) {', gps_popup_js)

with open(r'c:\Users\harsh\OneDrive\Desktop\10_6\padosi_agent\templates\public\find-agents.html', 'w', encoding='utf-8') as f:
    f.write(html)
