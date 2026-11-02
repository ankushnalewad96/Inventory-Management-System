/*
 * Print / Download PDF for printable documents.
 *
 * The sheet is #docSheet with data-file-name="...".
 * <body data-auto-download="1"> downloads the PDF on load,
 * <body data-auto-print="1"> opens the print dialog on load.
 * Needs html2pdf (loaded from the CDN); falls back to the browser's
 * "Save as PDF" print dialog if it is not available.
 */
(function () {
    'use strict';

    var sheet = document.getElementById('docSheet');
    var button = document.getElementById('downloadPdfBtn');
    var printButton = document.getElementById('printBtn');

    if (!sheet) {
        return;
    }

    var fileName = (sheet.getAttribute('data-file-name') || 'document')
        .replace(/[^\w\-. ]+/g, '')
        .trim()
        .replace(/\s+/g, '-') + '.pdf';

    function downloadPdf() {
        if (typeof window.html2pdf !== 'function') {
            window.print();
            return;
        }

        if (button) button.disabled = true;

        window.html2pdf()
            .set({
                margin: 10,
                filename: fileName,
                image: { type: 'jpeg', quality: 0.98 },
                html2canvas: { scale: 2, useCORS: true },
                jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
                pagebreak: { mode: ['css', 'legacy'] }
            })
            .from(sheet)
            .save()
            .then(function () { if (button) button.disabled = false; })
            .catch(function () {
                if (button) button.disabled = false;
                window.print();
            });
    }

    if (button) button.addEventListener('click', downloadPdf);
    if (printButton) printButton.addEventListener('click', function () { window.print(); });

    window.addEventListener('load', function () {
        if (document.body.getAttribute('data-auto-download') === '1') {
            downloadPdf();
        } else if (document.body.getAttribute('data-auto-print') === '1') {
            window.print();
        }
    });
})();
