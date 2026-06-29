/**
 * Form Handler Utility - Prevents Button Freezing
 * 
 * This utility ensures buttons are never left in a disabled state
 * even if fetch requests timeout or fail.
 */

(function() {
    // Prevent multiple definitions
    if (window.FormHandler) return;

    window.FormHandler = class FormHandler {
        constructor(options = {}) {
            this.timeout = options.timeout || 30000; // 30 seconds
            this.autoEnable = options.autoEnable !== false; // Auto re-enable button after timeout
            this.showLoadingText = options.showLoadingText !== false;
            this.loadingText = options.loadingText || 'Processing...';
        }

        /**
         * Handle form submission with automatic button state management
         */
        async handleSubmit(form, submitHandler) {
            const submitBtn = form.querySelector('button[type="submit"]');
            if (!submitBtn) return;

            // Store original state
            const originalText = submitBtn.textContent;
            const originalDisabled = submitBtn.disabled;

            // Disable button
            submitBtn.disabled = true;
            if (this.showLoadingText) {
                submitBtn.textContent = this.loadingText;
            }
            submitBtn.classList.add('loading');

            try {
                // Run the actual submission handler
                const result = await this.withTimeout(
                    submitHandler(),
                    this.timeout
                );
                return result;
            } catch (error) {
                console.error('Form submission error:', error);
                throw error;
            } finally {
                // CRITICAL: Always restore button state
                this.restoreButton(submitBtn, originalText, originalDisabled);
            }
        }

        /**
         * Execute async operation with timeout
         */
        withTimeout(promise, timeout) {
            return Promise.race([
                promise,
                new Promise((_, reject) =>
                    setTimeout(() => reject(new Error('Request timeout')), timeout)
                )
            ]);
        }

        /**
         * Restore button to original state
         */
        restoreButton(btn, originalText, originalDisabled) {
            btn.disabled = originalDisabled;
            btn.textContent = originalText;
            btn.classList.remove('loading');
        }

        /**
         * Fetch with built-in timeout
         */
        async fetchWithTimeout(url, options = {}) {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), this.timeout);

            try {
                const response = await fetch(url, {
                    ...options,
                    signal: controller.signal
                });
                return response;
            } catch (error) {
                if (error.name === 'AbortError') {
                    throw new Error('Request timeout - please try again');
                }
                throw error;
            } finally {
                clearTimeout(timeoutId);
            }
        }
    };

    /**
     * Global instance for use throughout the app
     */
    window.formHandler = new window.FormHandler({
        timeout: 30000,
        loadingText: 'Please wait...'
    });

    /**
     * Monitor all fetch requests and ensure preloader is hidden
     * Hijack global fetch to add safety checks
     */
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        // After fetch completes (success or error), hide preloader
        return originalFetch.apply(this, args)
            .finally(() => {
                if (window.$ && typeof window.$ === 'function') {
                    // Hide any stuck preloaders
                    if ($('.loader-mask').is(':visible')) {
                        try {
                            $('.loader').fadeOut(200);
                            $('.loader-mask').fadeOut(200);
                        } catch (e) {
                            // Ignore errors
                        }
                    }
                }
            });
    };

    /**
     * Safety: Auto-hide preloader if stuck for too long
     */
    setInterval(function() {
        if (window.$ && typeof window.$ === 'function') {
            const loaderMask = $('.loader-mask');
            if (loaderMask.is(':visible')) {
                // Preloader visible for more than a short time
                // Add a safety timeout to hide it
                loaderMask.each(function() {
                    const $this = $(this);
                    if (!$this.data('hideTimeout')) {
                        $this.data('hideTimeout', setTimeout(() => {
                            $this.fadeOut(200);
                            $this.data('hideTimeout', null);
                        }, 5000)); // Hide after 5 seconds if still visible
                    }
                });
            }
        }
    }, 2000);

    /**
     * Auto-attach to forms with class "auto-form-handler"
     * Using delegation to handle HTMX swaps
     */
    document.addEventListener('submit', function(e) {
        const form = e.target.closest('form.auto-form-handler');
        if (form) {
            e.preventDefault();
            
            // This will automatically restore button state even if submission fails
            window.formHandler.handleSubmit(form, () => {
                // Submit form normally
                return new Promise((resolve) => {
                    form.submit();
                    resolve();
                });
            }).catch(error => {
                console.error('Form error:', error);
            });
        }
    });

})();

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    if (typeof FormHandler !== 'undefined') {
        module.exports = { FormHandler: window.FormHandler, formHandler: window.formHandler };
    }
}
