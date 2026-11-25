/* EuphoriaDJ storefront interactions — no jQuery required. */
(function () {
    'use strict';

    var body = document.body;

    function qs(selector, scope) {
        return (scope || document).querySelector(selector);
    }

    function qsa(selector, scope) {
        return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
    }

    function setExpanded(button, expanded) {
        if (button) {
            button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        }
    }

    /* Sticky header */
    var header = qs('[data-site-header]');
    var backToTop = qs('[data-back-to-top]');

    function onScroll() {
        if (header) {
            header.classList.toggle('is-scrolled', window.scrollY > 12);
        }
        if (backToTop) {
            backToTop.hidden = window.scrollY < 420;
        }
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if (backToTop) {
        backToTop.addEventListener('click', function () {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }

    /* Header search panel */
    var searchToggle = qs('[data-search-toggle]');
    var searchPanel = qs('[data-search-panel]');
    var searchClose = qs('[data-search-close]');
    var searchInput = searchPanel ? qs('input[type="search"]', searchPanel) : null;

    function openSearch() {
        if (!searchPanel) return;
        searchPanel.hidden = false;
        setExpanded(searchToggle, true);
        window.setTimeout(function () {
            if (searchInput) searchInput.focus();
        }, 40);
    }

    function closeSearch(returnFocus) {
        if (!searchPanel) return;
        searchPanel.hidden = true;
        setExpanded(searchToggle, false);
        if (returnFocus && searchToggle) searchToggle.focus();
    }

    if (searchToggle && searchPanel) {
        searchToggle.addEventListener('click', function () {
            if (searchPanel.hidden) openSearch();
            else closeSearch(false);
        });
    }
    if (searchClose) {
        searchClose.addEventListener('click', function () { closeSearch(true); });
    }

    /* Mobile navigation drawer */
    var menuToggle = qs('[data-menu-toggle]');
    var mobileNav = qs('[data-mobile-nav]');
    var menuClosers = qsa('[data-menu-close]');

    function openNav() {
        if (!mobileNav) return;
        mobileNav.hidden = false;
        body.classList.add('nav-open');
        setExpanded(menuToggle, true);
        window.requestAnimationFrame(function () {
            mobileNav.classList.add('is-open');
        });
        var firstLink = qs('a, button', mobileNav);
        if (firstLink) {
            window.setTimeout(function () { firstLink.focus(); }, 120);
        }
    }

    function closeNav(returnFocus) {
        if (!mobileNav || mobileNav.hidden) return;
        mobileNav.classList.remove('is-open');
        body.classList.remove('nav-open');
        setExpanded(menuToggle, false);
        window.setTimeout(function () {
            mobileNav.hidden = true;
            if (returnFocus && menuToggle) menuToggle.focus();
        }, 420);
    }

    if (menuToggle && mobileNav) {
        menuToggle.addEventListener('click', openNav);
        mobileNav.addEventListener('click', function (event) {
            if (event.target.closest('a')) closeNav(false);
        });
    }
    menuClosers.forEach(function (closer) {
        closer.addEventListener('click', function () { closeNav(true); });
    });

    /* Shop filter drawer */
    var filterTrigger = qs('[data-filter-toggle]');
    var filterDrawer = qs('[data-filter-drawer]');
    var filterOverlay = qs('[data-filter-overlay]');
    var filterClose = qs('[data-filter-close]');

    function openFilters() {
        if (!filterDrawer || !filterOverlay) return;
        filterOverlay.hidden = false;
        filterDrawer.classList.add('is-open');
        body.classList.add('filter-open');
        setExpanded(filterTrigger, true);
        var firstField = qs('input, select', filterDrawer);
        if (firstField) {
            window.setTimeout(function () { firstField.focus(); }, 120);
        }
    }

    function closeFilters(returnFocus) {
        if (!filterDrawer || !filterOverlay) return;
        filterDrawer.classList.remove('is-open');
        filterOverlay.hidden = true;
        body.classList.remove('filter-open');
        setExpanded(filterTrigger, false);
        if (returnFocus && filterTrigger) filterTrigger.focus();
    }

    if (filterTrigger && filterDrawer) {
        filterTrigger.addEventListener('click', openFilters);
    }
    if (filterClose) {
        filterClose.addEventListener('click', function () { closeFilters(true); });
    }
    if (filterOverlay) {
        filterOverlay.addEventListener('click', function () { closeFilters(true); });
    }

    /* Small auto-submit selects (shop sorting) */
    qsa('[data-auto-submit]').forEach(function (select) {
        select.addEventListener('change', function () {
            if (select.form) select.form.submit();
        });
    });

    window.addEventListener('resize', function () {
        if (window.innerWidth > 991) {
            if (filterDrawer && filterDrawer.classList.contains('is-open')) closeFilters(false);
            if (mobileNav && !mobileNav.hidden) closeNav(false);
        }
    });

    /* Global escape handling */
    document.addEventListener('keydown', function (event) {
        if (event.key !== 'Escape') return;
        if (mobileNav && !mobileNav.hidden) {
            closeNav(true);
            return;
        }
        if (filterDrawer && filterDrawer.classList.contains('is-open')) {
            closeFilters(true);
            return;
        }
        if (searchPanel && !searchPanel.hidden) {
            closeSearch(true);
        }
    });

    /* Close / coordinate native disclosure menus */
    var disclosures = qsa('details.nav-disclosure, details.account-menu');

    disclosures.forEach(function (details) {
        details.addEventListener('toggle', function () {
            if (!details.open) return;
            disclosures.forEach(function (other) {
                if (other !== details) other.open = false;
            });
        });
    });

    document.addEventListener('click', function (event) {
        disclosures.forEach(function (details) {
            if (details.open && !details.contains(event.target)) details.open = false;
        });
    });

    /* Quantity controls */
    qsa('[data-quantity]').forEach(function (quantity) {
        var input = qs('input[type="number"]', quantity);
        if (!input) return;
        var min = parseInt(input.getAttribute('min') || '1', 10);
        var max = parseInt(input.getAttribute('max') || '5', 10);

        qsa('[data-quantity-step]', quantity).forEach(function (button) {
            button.addEventListener('click', function () {
                var step = parseInt(button.getAttribute('data-quantity-step') || '0', 10);
                var current = parseInt(input.value || String(min), 10);
                if (isNaN(current)) current = min;
                var next = Math.min(max, Math.max(min, current + step));
                input.value = String(next);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });

        input.addEventListener('change', function () {
            var value = parseInt(input.value || String(min), 10);
            if (isNaN(value)) value = min;
            input.value = String(Math.min(max, Math.max(min, value)));
        });
    });

    /* Dismiss flash messages */
    qsa('[data-alert-close]').forEach(function (button) {
        button.addEventListener('click', function () {
            var alert = button.closest('.alert');
            if (!alert) return;
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-0.35rem)';
            window.setTimeout(function () { alert.remove(); }, 260);
        });
    });

    /* Respect reduced motion for the mobile drawer */
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        document.documentElement.style.scrollBehavior = 'auto';
    }
})();
