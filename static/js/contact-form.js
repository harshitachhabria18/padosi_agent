function initContactForm() {
	var $form = jQuery("#contactpage");
	if (!$form.length) return;

	// Initialize validation if plugin is available
	if (jQuery.fn.validate) {
		$form.validate({
			rules: {
				name: { required: true, minlength: 2 },
				email: { required: true, email: true },
				mobile: { required: true, digits: true, minlength: 10, maxlength: 10 },
				subject: { required: true, minlength: 5 },
				message: { required: true, minlength: 10 }
			},
			errorElement: "span",
			errorPlacement: function (e, t) {
				e.appendTo(t.parent());
			}
		});
	}
}

// Use event delegation for form submission so it works after HTMX swaps
jQuery(document).on("submit", "#contactpage", function (e) {
	var $form = jQuery(this);
	e.preventDefault();

	// If jQuery Validate exists and form is invalid, stop here.
	if (jQuery.fn.validate && $form.data("validator") && !$form.valid()) {
		return false;
	}

	submitContactForm($form);
	return false;
});

function submitContactForm($form) {
	var payload = $form.serialize();
	var $btn = $form.find("#submit");
	var originalHtml = $btn.html();
	var $result = jQuery("#form_result");
	$btn.prop("disabled", true).addClass("disabled").html("Sending...");

	jQuery.ajax({
		url: $form.attr("action") || "/contact/submit",
		type: $form.attr("method") || "POST",
		data: payload,
		success: function (res) {
			var msg = res.message || "Message sent successfully.";
			$result.stop(true, true)
				.html('<span class="form-success alert alert-success d-block">' + msg + "</span>")
				.show();

			// Scroll to the result message so the user sees it at the top
			jQuery('html, body').animate({
				scrollTop: $result.offset().top - 150
			}, 500);

			$result.delay(4000).fadeOut(400);
			$form[0].reset();
		},
		error: function (xhr) {
			var msg = "Failed to send message. Please try again.";
			if (xhr.responseJSON && xhr.responseJSON.message) {
				msg = xhr.responseJSON.message;
			}

			var errorsHtml = "";
			if (xhr.responseJSON && xhr.responseJSON.errors) {
				errorsHtml += "<ul class=\"mb-0\">";
				jQuery.each(xhr.responseJSON.errors, function (field, messages) {
					if (messages && messages.length) {
						jQuery.each(messages, function (_, text) {
							errorsHtml += "<li>" + text + "</li>";
						});
					}
				});
				errorsHtml += "</ul>";
			}

			var fullMsg = "<span class=\"form-error alert alert-danger d-block\">" + msg + (errorsHtml ? "<br>" + errorsHtml : "") + "</span>";
			$result.stop(true, true)
				.html(fullMsg)
				.show();

			// Scroll to the result message so the user sees it at the top
			jQuery('html, body').animate({
				scrollTop: $result.offset().top - 150
			}, 500);

			$result.delay(6000).fadeOut(400);
		},
		complete: function () {
			$btn.prop("disabled", false).removeClass("disabled").html(originalHtml);
		}
	});
	return false;
}

// Run on initial load
jQuery(document).ready(function () {
	initContactForm();
});

// Re-run after HTMX page swaps
document.addEventListener('htmx:afterSwap', function(evt) {
    if (evt.detail && evt.detail.target && evt.detail.target.id === 'app-content') {
        initContactForm();
    } else if (jQuery('#contactpage').length) {
        initContactForm();
    }
});
