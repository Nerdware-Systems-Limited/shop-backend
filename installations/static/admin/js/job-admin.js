/**
 * Installation Job Admin - JavaScript Enhancements
 */

(function($) {
    'use strict';

    $(document).ready(function() {

        // ============================================
        // AUTO-RESIZE TEXTAREAS
        // ============================================

        function autoResize(el) {
            el.style.height = 'auto';
            el.style.height = (el.scrollHeight + 10) + 'px';
        }

        $('textarea[name="description"], textarea[name="meta_description"], textarea[name="seo_keywords"]').each(function() {
            autoResize(this);
        }).on('input', function() {
            autoResize(this);
        });

        // ============================================
        // RESPONSIVE COLUMN CLASSES
        // ============================================

        function applyResponsiveClasses() {
            var windowWidth = $(window).width();

            $('.form-row').each(function() {
                var $row = $(this);
                var $fields = $row.find('> div, > .field-box');

                if ($fields.length >= 3 && windowWidth >= 1200) {
                    $row.addClass('three-columns').removeClass('two-columns');
                } else if ($fields.length >= 2 && windowWidth >= 1024) {
                    $row.addClass('two-columns').removeClass('three-columns');
                } else {
                    $row.removeClass('two-columns three-columns');
                }
            });
        }

        applyResponsiveClasses();
        $(window).on('resize', applyResponsiveClasses);

        // ============================================
        // SEO FIELD PREVIEW TOGGLES
        // ============================================

        $('.seo-fieldset .readonly').each(function() {
            var $readonlyDiv = $(this);
            if ($readonlyDiv.closest('.preview-wrapper').length) return; // already wrapped

            $readonlyDiv.wrap('<div class="preview-wrapper" style="display:none;"></div>');

            var $toggle = $('<a href="#" class="preview-toggle" style="font-size:12px;">Show Preview</a>');
            $readonlyDiv.parent('.preview-wrapper').before($toggle);

            $toggle.on('click', function(e) {
                e.preventDefault();
                var $wrapper = $(this).next('.preview-wrapper');
                if ($wrapper.is(':hidden')) {
                    $wrapper.slideDown();
                    $(this).text('Hide Preview');
                } else {
                    $wrapper.slideUp();
                    $(this).text('Show Preview');
                }
            });
        });

        // ============================================
        // IMAGE CLICK TO OPEN
        // ============================================

        $('.image-preview-box img, .readonly img').not('.no-zoom').each(function() {
            var src = $(this).attr('src');
            if (src) {
                $(this).css('cursor', 'zoom-in').on('click', function() {
                    window.open(src, '_blank');
                });
            }
        });

        // ============================================
        // COST CALCULATOR
        // ============================================

        var $labourCost = $('input[name="labour_cost"]');
        var $partsCost  = $('input[name="parts_cost"]');
        var $discount   = $('input[name="discount"]');

        function updateCostPreview() {
            var labour   = parseFloat($labourCost.val())  || 0;
            var parts    = parseFloat($partsCost.val())   || 0;
            var discount = parseFloat($discount.val())    || 0;
            var total    = labour + parts - discount;

            var $display = $('#total-cost-display');
            var html     = 'Total: KSh ' + total.toLocaleString('en-KE', {minimumFractionDigits: 2});

            if (!$display.length) {
                $discount.closest('.form-row').after(
                    '<div id="total-cost-display" style="font-weight:bold;font-size:16px;color:#1976d2;'
                    + 'margin:8px 20px;padding:10px;background:#e3f2fd;border-radius:4px;">' + html + '</div>'
                );
            } else {
                $display.html(html);
            }
        }

        if ($labourCost.length && $partsCost.length) {
            $labourCost.on('input', updateCostPreview);
            $partsCost.on('input', updateCostPreview);
            if ($discount.length) $discount.on('input', updateCostPreview);
            updateCostPreview();
        }

        // ============================================
        // INLINE ROW COUNTS
        // ============================================

        $('.inline-group').each(function() {
            var $group = $(this);
            var count  = $group.find('tbody tr').not('.empty-form').length;
            if (count > 0) {
                $group.find('h3').append(' <span class="row-count" style="font-weight:normal;color:#666;">(' + count + ' items)</span>');
            }
        });

        // ============================================
        // STICKY SAVE BUTTONS ON MOBILE
        // ============================================

        if ($(window).width() < 768) {
            var $submitRow = $('.submit-row');
            if ($submitRow.length) {
                $submitRow.css({
                    'position':   'fixed',
                    'bottom':     '0',
                    'left':       '0',
                    'right':      '0',
                    'z-index':    '1000',
                    'background': '#fff',
                    'padding':    '10px 20px',
                    'box-shadow': '0 -2px 10px rgba(0,0,0,0.1)'
                });
                $('#content-main').css('padding-bottom', '80px');
            }
        }

    });

})(django.jQuery);