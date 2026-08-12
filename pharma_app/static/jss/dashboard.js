// ===== SIDEBAR TOGGLE =====
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');
const sidebarOverlay = document.getElementById('sidebarOverlay');

function toggleSidebar() {
    sidebar.classList.toggle('collapsed');
    mainContent.classList.toggle('expanded');
    localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
}

function openMobileSidebar() {
    sidebar.classList.add('open');
    sidebarOverlay.classList.add('active');
}

function closeMobileSidebar() {
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('active');
}

// Restore sidebar state
if (localStorage.getItem('sidebarCollapsed') === 'true' && window.innerWidth > 768) {
    sidebar.classList.add('collapsed');
    mainContent.classList.add('expanded');
}

// ===== THEME TOGGLE =====
const html = document.documentElement;
const themeIcon = document.getElementById('themeIcon');

function toggleTheme() {
    const current = html.getAttribute('data-theme');
    const next = current === 'light' ? 'dark' : 'light';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    themeIcon.className = next === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
}

// Restore theme
const savedTheme = localStorage.getItem('theme') || 'light';
html.setAttribute('data-theme', savedTheme);
themeIcon.className = savedTheme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';

// ===== DOWNLOAD CSV =====
function downloadCSV() {
    const rows = [
        ['Order No.', 'Supplier', 'Date', 'Payment Type', 'Amount', 'Balance', 'Due Date', 'Status'],
        ['BILL-2026-001', 'nova', '27 Jul 2026', 'Cash', '570.78', '320.78', '13 Aug 2026', 'Unpaid'],
        ['BILL-2026-001', 'orion', '27 Jul 2026', 'Cash', '490.14', '240.14', '11 Aug 2026', 'Unpaid']
    ];
    let csv = rows.map(r => r.map(c => '"' + c + '"').join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'purchases_' + new Date().toISOString().split('T')[0] + '.csv';
    a.click();
    URL.revokeObjectURL(url);
}


/* ============================================================
    USER PROFILE DROPDOWN
    ============================================================ */
const userProfile = document.getElementById('userProfile');
const userDropdownMenu = document.getElementById('userDropdownMenu');

userProfile.addEventListener('click', function (e) {
    e.stopPropagation();
    userDropdownMenu.classList.toggle('show');
    userProfile.classList.toggle('open');
});

// Close dropdown when clicking anywhere else
document.addEventListener('click', function (e) {
    if (!userProfile.contains(e.target)) {
        userDropdownMenu.classList.remove('show');
        userProfile.classList.remove('open');
    }
});

// Close dropdown on Escape
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        userDropdownMenu.classList.remove('show');
        userProfile.classList.remove('open');
        closeMobileSidebar();
    }
});


// Close mobile sidebar on resize to desktop
window.addEventListener('resize', () => {
    if (window.innerWidth > 768) {
        closeMobileSidebar();
    }
});