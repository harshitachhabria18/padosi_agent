// Hide preloader on page load
$(window).on('load', function () {
    hidePreloader();
});

// Function to hide preloader
function hidePreloader() {
    $('.loader').fadeOut(300);
    $('.loader-mask').delay(300).fadeOut(300);
}

// Hide preloader after button clicks (for form submissions and navigation)
$(document).on('click', 'button, input[type="submit"], .btn', function() {
    // Don't hide if button has 'no-preloader' or 'data-no-loader' class
    if ($(this).hasClass('no-preloader') || $(this).hasClass('data-no-loader')) {
        return;
    }
    
    // Delay showing preloader slightly to avoid flickers
    setTimeout(function() {
        if ($('.loader-mask').is(':visible')) {
            // Already showing, do nothing
        } else {
            // Only show if it's expected to take longer (arbitrary 500ms)
            // This prevents blocking for quick responses
        }
    }, 500);
});

// Auto-hide preloader if it's stuck (safety timeout)
setTimeout(function() {
    if ($('.loader-mask').is(':visible:not(.hidden)')) {
        hidePreloader();
    }
}, 15000); // 15 second safety timeout
