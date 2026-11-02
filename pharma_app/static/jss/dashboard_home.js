/*
 * Dashboard: hover / keyboard-focus tooltip for the daily sales chart.
 * Values come from data-* attributes and are written with textContent.
 */
(function () {
    'use strict';

    var plot = document.querySelector('.db-chart-plot');
    var tooltip = document.getElementById('chartTooltip');

    if (!plot || !tooltip) {
        return;
    }

    var valueEl = tooltip.querySelector('strong');
    var dateEl = tooltip.querySelector('.db-tooltip-date');
    var countEl = tooltip.querySelector('.db-tooltip-count');

    function show(column) {
        var bar = column.querySelector('.db-bar');
        var plotBox = plot.getBoundingClientRect();
        var colBox = column.getBoundingClientRect();
        var barBox = bar.getBoundingClientRect();

        valueEl.textContent = column.getAttribute('data-value');
        dateEl.textContent = column.getAttribute('data-date');
        countEl.textContent = column.getAttribute('data-count');

        tooltip.hidden = false;

        // Centre over the column, keep inside the plot.
        var half = tooltip.offsetWidth / 2;
        var x = colBox.left - plotBox.left + colBox.width / 2;
        x = Math.max(half, Math.min(plotBox.width - half, x));

        var top = (barBox.height > 0 ? barBox.top : colBox.bottom) - plotBox.top - 8;
        tooltip.style.left = x + 'px';
        tooltip.style.top = Math.max(top, tooltip.offsetHeight) + 'px';
    }

    function hide() {
        tooltip.hidden = true;
    }

    plot.querySelectorAll('.db-col').forEach(function (column) {
        column.addEventListener('pointerenter', function () { show(column); });
        column.addEventListener('focus', function () { show(column); });
        column.addEventListener('pointerleave', hide);
        column.addEventListener('blur', hide);
    });
})();
