/*
 * Payment popup used on the purchase bill and customer account pages.
 *
 *   <div class="pay-modal-overlay" id="payModal" data-due="120.50" data-auto-open="1">
 *   [data-open-pay]  opens it, [data-close-pay] closes it,
 *   [data-fill-due]  fills the full due amount.
 */
(function () {
    'use strict';

    var modal = document.getElementById('payModal');

    if (!modal) {
        return;
    }

    var form = modal.querySelector('form');
    var amountInput = modal.querySelector('[name="amount"]');
    var due = parseFloat(modal.getAttribute('data-due')) || 0;

    function open() {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        setTimeout(function () { if (amountInput) amountInput.focus(); }, 50);
    }

    function close() {
        modal.classList.remove('active');
        document.body.style.overflow = '';
    }

    document.querySelectorAll('[data-open-pay]').forEach(function (button) {
        button.addEventListener('click', open);
    });

    modal.querySelectorAll('[data-close-pay]').forEach(function (button) {
        button.addEventListener('click', close);
    });

    modal.addEventListener('click', function (event) {
        if (event.target === modal) close();
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape' && modal.classList.contains('active')) close();
    });

    modal.querySelectorAll('[data-fill-due]').forEach(function (button) {
        button.addEventListener('click', function () {
            if (amountInput) amountInput.value = due.toFixed(2);
        });
    });

    if (form && amountInput) {
        form.addEventListener('submit', function (event) {
            var amount = parseFloat(amountInput.value) || 0;

            if (amount <= 0 || amount > due + 0.001) {
                event.preventDefault();
                amountInput.setCustomValidity('Enter an amount between 0.01 and ' + due.toFixed(2) + '.');
                amountInput.reportValidity();
                return;
            }

            var submit = form.querySelector('[type="submit"]') || modal.querySelector('[type="submit"]');
            if (submit) submit.disabled = true;
        });

        amountInput.addEventListener('input', function () {
            amountInput.setCustomValidity('');
        });
    }

    if (modal.getAttribute('data-auto-open') === '1') {
        open();
    }
})();
