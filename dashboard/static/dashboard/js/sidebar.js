// Sidebar initialization: wait for DOM ready so elements are present
document.addEventListener('DOMContentLoaded', function () {
    // Debug: indicate the script has loaded (remove or lower verbosity in production)
    try { console.debug && console.debug('sidebar.js: DOMContentLoaded'); } catch (e) {}
    // Initialize Lucide icons
    if (window.lucide && typeof lucide.createIcons === 'function') {
        lucide.createIcons();
    }

    // Get DOM elements (null-safe)
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
    const sidebarExpandBtn = document.getElementById('sidebar-expand-btn');
    const mainContent = document.getElementById('main-content');

    // Mobile sidebar toggle functionality
    function toggleSidebar() {
        if (!sidebar || !sidebarOverlay) return;
        sidebar.classList.toggle('-translate-x-full');
        sidebarOverlay.classList.toggle('hidden');
    }

    // Desktop sidebar collapse/expand functionality
    function toggleSidebarCollapse() {
        if (!sidebar) return;
        sidebar.classList.toggle('sidebar-collapsed');
        sidebar.classList.toggle('sidebar-expanded');
        if (mainContent) mainContent.classList.toggle('main-content-collapsed');

        // Close all submenus when collapsing
        if (sidebar.classList.contains('sidebar-collapsed')) {
            // hide submenu elements
            document.querySelectorAll('.submenu').forEach(menu => {
                menu.classList.remove('show');
                menu.classList.add('hidden');
                menu.style.display = '';
            });
            // reset toggle buttons and chevrons
            document.querySelectorAll('.menu-toggle').forEach(btn => {
                btn.classList.remove('open');
                try { btn.setAttribute('aria-expanded', 'false'); } catch (e) {}
                const ch = btn.querySelector('.chevron-icon') || btn.querySelector('svg') || btn.querySelector('[data-lucide]');
                if (ch) ch.style.transform = 'rotate(0deg)';
            });
        }

        // Reinitialize icons (safe guard)
        if (window.lucide && typeof lucide.createIcons === 'function') {
            lucide.createIcons();
        }
    }

    // Submenu toggle functionality
    function openSubmenu(submenu) {
        if (!submenu) return;
        submenu.classList.remove('hidden');
        submenu.classList.add('show');
        submenu.style.display = 'block';
        submenu.style.overflow = 'hidden';
        submenu.style.transition = 'max-height 220ms ease, opacity 180ms ease';
        submenu.style.maxHeight = '0px';
        submenu.style.opacity = '0';

        const targetHeight = submenu.scrollHeight;
        requestAnimationFrame(() => {
            submenu.style.maxHeight = `${targetHeight}px`;
            submenu.style.opacity = '1';
        });

        const onEnd = (e) => {
            if (e.propertyName !== 'max-height') return;
            submenu.style.maxHeight = 'none';
            submenu.style.overflow = '';
            submenu.removeEventListener('transitionend', onEnd);
        };
        submenu.addEventListener('transitionend', onEnd);
    }

    function closeSubmenu(submenu) {
        if (!submenu) return;
        submenu.style.overflow = 'hidden';
        submenu.style.transition = 'max-height 220ms ease, opacity 180ms ease';
        submenu.style.maxHeight = `${submenu.scrollHeight}px`;
        submenu.style.opacity = '1';

        requestAnimationFrame(() => {
            submenu.style.maxHeight = '0px';
            submenu.style.opacity = '0';
        });

        submenu.classList.remove('show');

        const onEnd = (e) => {
            if (e.propertyName !== 'max-height') return;
            submenu.classList.add('hidden');
            submenu.style.display = '';
            submenu.style.maxHeight = '';
            submenu.style.opacity = '';
            submenu.style.overflow = '';
            submenu.style.transition = '';
            submenu.removeEventListener('transitionend', onEnd);
        };
        submenu.addEventListener('transitionend', onEnd);
    }

    function toggleSubmenu(button) {
        if (!sidebar || !button) return;
        const menuId = button.getAttribute('data-menu');
        const submenu = document.getElementById(menuId);
        // find chevron robustly (lucide may replace <i> with <svg>)
        const chevron = button.querySelector('.chevron-icon') || button.querySelector('svg') || button.querySelector('[data-lucide]');

        // If sidebar is collapsed, expand it first and open the submenu
        if (sidebar.classList.contains('sidebar-collapsed')) {
            toggleSidebarCollapse();
            // Small delay to allow sidebar expansion animation to start
            setTimeout(() => {
                // Open the clicked submenu
                if (submenu) {
                    openSubmenu(submenu);
                    button.classList.add('open');
                    try { button.setAttribute('aria-expanded', 'true'); } catch (e) {}
                    if (chevron) chevron.style.transform = 'rotate(90deg)';
                }
            }, 50);
            return;
        }

        // Check if current submenu is open (based on DOM state, not just classes)
        if (!submenu) return;
        const isCurrentlyOpen = !submenu.classList.contains('hidden');

        // Close other open submenus and reset their toggle buttons
        document.querySelectorAll('.menu-toggle').forEach(btn => {
            if (btn === button) return;
            const otherMenuId = btn.getAttribute('data-menu');
            const otherMenu = document.getElementById(otherMenuId);
            if (otherMenu && !otherMenu.classList.contains('hidden')) {
                closeSubmenu(otherMenu);
            }
            btn.classList.remove('open');
            try { btn.setAttribute('aria-expanded', 'false'); } catch (e) {}
            const ch = btn.querySelector('.chevron-icon') || btn.querySelector('svg') || btn.querySelector('[data-lucide]');
            if (ch) ch.style.transform = 'rotate(0deg)';
        });

        // Toggle current submenu
        if (isCurrentlyOpen) {
            // close
            closeSubmenu(submenu);
            button.classList.remove('open');
            try { button.setAttribute('aria-expanded', 'false'); } catch (e) {}
            if (chevron) chevron.style.transform = 'rotate(0deg)';
        } else {
            // open
            openSubmenu(submenu);
            button.classList.add('open');
            try { button.setAttribute('aria-expanded', 'true'); } catch (e) {}
            if (chevron) chevron.style.transform = 'rotate(90deg)';
        }
    }

    // Initialize submenu states based on DOM (for server-rendered open states)
    function initializeSubmenuStates() {
        document.querySelectorAll('.menu-toggle').forEach(button => {
            const menuId = button.getAttribute('data-menu');
            const submenu = document.getElementById(menuId);
            const chevron = button.querySelector('.chevron-icon') || button.querySelector('svg') || button.querySelector('[data-lucide]');
            
            if (submenu && !submenu.classList.contains('hidden')) {
                // Submenu is open in the DOM, sync button state and ensure visibility
                submenu.classList.add('show');
                submenu.style.display = 'block';
                submenu.style.maxHeight = 'none';
                submenu.style.opacity = '1';
                button.classList.add('open');
                try { button.setAttribute('aria-expanded', 'true'); } catch (e) {}
                if (chevron) chevron.style.transform = 'rotate(90deg)';
            } else if (submenu) {
                // Submenu is closed, ensure it's hidden
                submenu.classList.add('hidden');
                submenu.classList.remove('show');
                submenu.style.display = '';
                submenu.style.maxHeight = '';
                submenu.style.opacity = '';
                button.classList.remove('open');
                try { button.setAttribute('aria-expanded', 'false'); } catch (e) {}
                if (chevron) chevron.style.transform = 'rotate(0deg)';
            }
        });
    }

    // Event listeners (null-safe)
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', toggleSidebar);
        try { console.debug && console.debug('sidebar.js: sidebarToggle bound'); } catch (e) {}
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', toggleSidebar);
    }

    if (sidebarCollapseBtn) {
        sidebarCollapseBtn.addEventListener('click', toggleSidebarCollapse);
        try { console.debug && console.debug('sidebar.js: sidebarCollapseBtn bound'); } catch (e) {}
    }

    if (sidebarExpandBtn) {
        sidebarExpandBtn.addEventListener('click', toggleSidebarCollapse);
        try { console.debug && console.debug('sidebar.js: sidebarExpandBtn bound'); } catch (e) {}
    }

    // Initialize submenu states on page load
    initializeSubmenuStates();

    // Add event listeners to menu toggle buttons
    document.querySelectorAll('.menu-toggle').forEach(button => {
        button.addEventListener('click', function () {
            toggleSubmenu(this);
        });
    });

    // User dropdown toggle
    const userMenuToggle = document.getElementById('user-menu-toggle');
    const userDropdown = document.getElementById('user-dropdown');

    if (userMenuToggle && userDropdown) {
        userMenuToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            userDropdown.classList.toggle('hidden');
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', function (e) {
            if (!userMenuToggle.contains(e.target)) {
                userDropdown.classList.add('hidden');
            }
        });
    }

    // Handle window resize
    window.addEventListener('resize', function () {
        if (!sidebar || !sidebarOverlay) return;
        if (window.innerWidth >= 1024) {
            // Desktop view
            sidebar.classList.remove('-translate-x-full');
            sidebarOverlay.classList.add('hidden');

            // Ensure sidebar is expanded on desktop unless explicitly collapsed
            if (!sidebar.classList.contains('sidebar-collapsed')) {
                sidebar.classList.add('sidebar-expanded');
                if (mainContent) mainContent.classList.remove('main-content-collapsed');
            }
        } else {
            // Mobile view - reset sidebar state
            sidebar.classList.remove('sidebar-collapsed');
            sidebar.classList.add('sidebar-expanded');
            if (mainContent) mainContent.classList.remove('main-content-collapsed');
        }
    });

    // Initialize sidebar state on load
    if (sidebar) {
        if (window.innerWidth >= 1024) {
            sidebar.classList.add('sidebar-expanded');
            sidebar.classList.remove('-translate-x-full');
        } else {
            sidebar.classList.remove('sidebar-collapsed');
            sidebar.classList.add('sidebar-expanded');
        }
    }
});