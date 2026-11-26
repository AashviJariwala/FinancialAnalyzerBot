/**
 * session-lifecycle.js
 * 
 * Enforces session destruction when:
 * 1. The server restarts (detected via server_boot_id mismatch).
 * 2. The browser is closed (detected via sessionStorage wipe).
 * 
 * Enforces tab isolation:
 * - When a URL is copy-pasted into a new tab, the new tab directly shows the client login page.
 * - The existing client continues running in the old tab.
 * 
 * Preserves session when:
 * - The page is refreshed (F5, Ctrl+R, reload button, location.reload()).
 * - The user navigates between website pages (/ -> /portfolioDashboard -> /scheme/...).
 */
(function () {
    const STORAGE_ACTIVE_KEY = "folio_session_active";
    const STORAGE_BOOT_KEY = "folio_server_boot_id";
    const STORAGE_TAB_TOKEN = "folio_active_tab_token";

    // Read injected server configuration
    const configEl = document.getElementById("sessionLifecycleConfig");
    const serverBootId = configEl ? configEl.dataset.serverBootId : null;
    const serverPortfolioId = configEl ? configEl.dataset.portfolioId : null;
    const isPortfolioLoaded = configEl ? configEl.dataset.portfolioLoaded === "true" : false;

    // Detect if current page load is a reload / refresh (F5 / location.reload)
    let isReload = false;
    try {
        const navEntries = performance.getEntriesByType("navigation");
        if (navEntries && navEntries.length > 0) {
            isReload = navEntries[0].type === "reload";
        } else if (window.performance && window.performance.navigation) {
            isReload = window.performance.navigation.type === 1; // 1 = TYPE_RELOAD
        }
    } catch (e) {
        // Fallback for older browsers
    }

    // 1. SERVER RESTART LIFECYCLE
    // If the server restarted, serverBootId has changed on the backend
    const storedBootId = sessionStorage.getItem(STORAGE_BOOT_KEY);
    if (serverBootId) {
        if (storedBootId && storedBootId !== serverBootId) {
            // Server was restarted! Clear local storage
            sessionStorage.clear();
        }
        sessionStorage.setItem(STORAGE_BOOT_KEY, serverBootId);
    }

    // 2. ACTIVE TAB PORTFOLIO SYNCHRONIZATION
    // Check if this tab is the one that loaded this active portfolio
    const localTabToken = sessionStorage.getItem(STORAGE_TAB_TOKEN);
    if (isPortfolioLoaded && serverPortfolioId) {
        if (localTabToken === serverPortfolioId) {
            // Tab is legitimately active
            document.documentElement.classList.remove("tab-client-empty");
            document.documentElement.classList.add("tab-client-active");
            sessionStorage.setItem(STORAGE_ACTIVE_KEY, "1");
        } else {
            // Different tab or newly pasted tab -> keep tab-client-empty
            document.documentElement.classList.remove("tab-client-active");
            document.documentElement.classList.add("tab-client-empty");
        }
    } else {
        document.documentElement.classList.remove("tab-client-active");
        document.documentElement.classList.add("tab-client-empty");
        sessionStorage.removeItem(STORAGE_ACTIVE_KEY);
        sessionStorage.removeItem(STORAGE_TAB_TOKEN);
    }

    // Expose helpers globally
    window.markSessionActive = function (portfolioId) {
        sessionStorage.setItem(STORAGE_ACTIVE_KEY, "1");
        const tokenToStore = portfolioId || serverPortfolioId;
        if (tokenToStore) {
            sessionStorage.setItem(STORAGE_TAB_TOKEN, tokenToStore);
        }
        if (serverBootId) {
            sessionStorage.setItem(STORAGE_BOOT_KEY, serverBootId);
        }
        document.documentElement.classList.remove("tab-client-empty");
        document.documentElement.classList.add("tab-client-active");
    };

    window.markSessionDestroyed = function () {
        sessionStorage.removeItem(STORAGE_ACTIVE_KEY);
        sessionStorage.removeItem(STORAGE_TAB_TOKEN);
        document.documentElement.classList.remove("tab-client-active");
        document.documentElement.classList.add("tab-client-empty");
    };
})();