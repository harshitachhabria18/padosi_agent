// Countdown Timer
function calculateTimeLeft() {
    const targetDate = new Date('2026-01-20T00:00:00').getTime();
    const now = new Date().getTime();
    const difference = targetDate - now;

    if (difference > 0) {
        return {
            days: Math.floor(difference / (1000 * 60 * 60 * 24)),
            hours: Math.floor((difference / (1000 * 60 * 60)) % 24),
            minutes: Math.floor((difference / 1000 / 60) % 60),
            seconds: Math.floor((difference / 1000) % 60)
        };
    }

    return { days: 0, hours: 0, minutes: 0, seconds: 0 };
}

function formatNumber(num) {
    return num.toString().padStart(2, '0');
}

function updateCountdown() {
    const timeLeft = calculateTimeLeft();

    document.getElementById('days').textContent = formatNumber(timeLeft.days);
    document.getElementById('hours').textContent = formatNumber(timeLeft.hours);
    document.getElementById('minutes').textContent = formatNumber(timeLeft.minutes);
    document.getElementById('seconds').textContent = formatNumber(timeLeft.seconds);
}

// Initialize countdown
updateCountdown();

// Update countdown every second
setInterval(updateCountdown, 1000);

// Button click handlers (you can customize these)
document.addEventListener('DOMContentLoaded', function () {
    const primaryBtn = document.querySelector('.btn-primary');
    const secondaryBtn = document.querySelector('.btn-secondary');

    // if (primaryBtn) {
    //     primaryBtn.addEventListener('click', function () {
    //         alert('Thank you for your interest in becoming an Agent! Registration will open on December 1st, 2025.');
    //     });
    // }

    // if (secondaryBtn) {
    //     secondaryBtn.addEventListener('click', function () {
    //         alert('Thank you for your interest in becoming a Customer! Registration will open on December 1st, 2025.');
    //     });
    // }
});

// Smooth scroll animation on load
window.addEventListener('load', function () {
    document.body.style.opacity = '0';
    setTimeout(function () {
        document.body.style.transition = 'opacity 0.5s ease-in';
        document.body.style.opacity = '1';
    }, 100);
});



class FacebookAutoPost {
    constructor() {
        this.appId = '759405373797845';
        this.version = 'v19.0';
        this.scopes = ['public_profile', 'email', 'publish_to_groups'];
        this.isLocalhost = this.checkIsLocalhost();

        // CORRECTED API endpoints
        this.endpoints = {
            autoPost: '/api/facebook/auto-post',
            storeToken: '/api/facebook/store-token',
            connectionStatus: '/api/facebook/connection-status',
            manualShare: '/api/facebook/confirm-manual-share'
        };
    }

    checkIsLocalhost() {
        return window.location.hostname === 'localhost' ||
            window.location.hostname === '127.0.0.1' ||
            window.location.hostname.endsWith('.test') ||
            window.location.hostname.endsWith('.local');
    }

    async autoPostToFacebook(participant, contestPost) {
        // Localhost detection and handling
        if (this.isLocalhost) {
            if (window.location.protocol !== 'https:') {
                return this.handleLocalhostHttp(participant, contestPost);
            }
            return this.handleLocalhostHttps(participant, contestPost);
        }

        // Production flow
        return this.handleProductionFlow(participant, contestPost);
    }

    async handleLocalhostHttp(participant, contestPost) {
        const useMock = confirm(
            '🚧 Localhost Development Mode 🚧\n\n' +
            'Facebook requires HTTPS. For now, we can:\n\n' +
            '• Use MOCK auto-post (simulated success)\n' +
            '• Switch to manual sharing\n\n' +
            'Click OK for mock auto-post, Cancel for manual sharing.'
        );

        if (useMock) {
            return this.mockAutoPost(participant, contestPost);
        } else {
            throw new Error('Switching to manual sharing');
        }
    }

    async mockAutoPost(participant, contestPost) {
        return new Promise((resolve) => {
            setTimeout(() => {
                const mockPostId = 'mock_' + Date.now();

                // REMOVED the logSuccessfulPost call
                resolve({
                    success: true,
                    postId: mockPostId,
                    message: '✅ Mock Auto-Post Successful!',
                    simulated: true
                });
            }, 2000);
        });
    }

    async handleProductionFlow(participant, contestPost) {
        try {
            const response = await fetch(this.endpoints.autoPost, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content
                },
                body: JSON.stringify({
                    participant_id: participant.id,
                    message: this.generatePostContent(contestPost, participant),
                    link: contestPost.website_url
                })
            });

            return await response.json();

        } catch (error) {
            throw new Error('Auto-post failed: ' + error.message);
        }
    }

    // REMOVE THIS METHOD - it's using wrong endpoint
    // async logSuccessfulPost(participantId, facebookPostId) {
    //     try {
    //         const response = await fetch('/api/facebook-posts/log', { // WRONG ENDPOINT
    //             method: 'POST',
    //             headers: {
    //                 'Content-Type': 'application/json',
    //                 'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content
    //             },
    //             body: JSON.stringify({
    //                 participant_id: participantId,
    //                 facebook_post_id: facebookPostId,
    //                 posted_at: new Date().toISOString()
    //             })
    //         });
    //         return await response.json();
    //     } catch (error) {
    //         console.error('Error logging post:', error);
    //     }
    // }

    generatePostContent(contestPost, participant) {
        return `🎉 Join Me in the PadosiAgent Community! 🎉

🌟 Discover PadosiAgent - Your Trusted Local Services Platform!

I just joined PadosiAgent and found amazing local professionals:
• Insurance Agents 🛡️
• Mutual Fund Agents 📈  
• Chartered Accountants 💼
• Lawyers ⚖️
• And many more!

🏆 Why I Love PadosiAgent:
✅ Verified & Trusted Professionals
✅ Easy Local Search
✅ Transparent Reviews
✅ Secure Connections

💫 Special Offer:
Use my referral code: ${participant.referral_code}

🔗 Join Now: ${contestPost.website_url}

Let's build a stronger community together! 🚀

#PadosiAgent #LocalServices #TrustedProfessionals #CommunityFirst`;
    }

    // Store Facebook access token
    async storeAccessToken(participantId, accessToken, userId) {
        try {
            const response = await fetch(this.endpoints.storeToken, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-TOKEN': document.querySelector('meta[name="csrf-token"]').content
                },
                body: JSON.stringify({
                    participant_id: participantId,
                    access_token: accessToken,
                    user_id: userId
                })
            });
            return await response.json();
        } catch (error) {
            console.error('Error storing token:', error);
            return { success: false, message: error.message };
        }
    }

    // Check connection status
    async getConnectionStatus(participantId) {
        try {
            const response = await fetch(`${this.endpoints.connectionStatus}/${participantId}`);
            return await response.json();
        } catch (error) {
            console.error('Error getting connection status:', error);
            return { success: false, message: error.message };
        }
    }
}