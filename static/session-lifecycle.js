/**
 * session-lifecycle.js
 * 
 * Enforces session destruction when:
 * 1. The server restarts (detected via server_boot_id mismatch).
 * 2. The browser is closed (detected via sessionStorage wipe).
 * 
 * Preserves session when:
 * - The page is refreshed (F5, Ctrl+R, reload button, location.reload()).
 * - The user navigates between website pages (/ -> /portfolioDashboard -> /scheme/...).
 */
(function () {
    const STORAGE_ACTIVE_KEY = "folio_session_active";
    const STORAGE_BOOT_KEY = "folio_server_boot_id";

    // Read injected server configuration
    const configEl = document.getElementById("sessionLifecycleConfig");
    const serverBootId = configEl ? configEl.dataset.serverBootId : null;
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
            // Server was restarted! Clear local storage and reset server session
            sessionStorage.clear();
            if (isPortfolioLoaded) {
                fetch("/reset", { method: "POST" }).then(() => {
                    window.location.reload();
                });
                return;
            }
        }
        sessionStorage.setItem(STORAGE_BOOT_KEY, serverBootId);
    }

    // 2. BROWSER CLOSE LIFECYCLE
    // sessionStorage is automatically cleared when the browser / tab is closed.
    // If the server session still holds a portfolio (e.g. cookie retained by browser restore),
    // but sessionStorage is empty AND this was NOT a page reload, the browser was closed!
    const isTabActive = sessionStorage.getItem(STORAGE_ACTIVE_KEY) === "1";

    if (isPortfolioLoaded) {
        if (!isTabActive && !isReload) {
            console.log("[SessionLifecycle] Browser closed detected. Destroying session...");
            sessionStorage.clear();
            fetch("/reset", { method: "POST" }).then(() => {
                window.location.reload();
            });
            return;
        }

        // Mark tab session active for subsequent reloads & internal navigations
        sessionStorage.setItem(STORAGE_ACTIVE_KEY, "1");
    } else {
        // No portfolio loaded on server, ensure clean storage
        sessionStorage.removeItem(STORAGE_ACTIVE_KEY);
    }

    // Expose helpers globally
    window.markSessionActive = function () {
        sessionStorage.setItem(STORAGE_ACTIVE_KEY, "1");
        if (serverBootId) {
            sessionStorage.setItem(STORAGE_BOOT_KEY, serverBootId);
        }
    };

    window.markSessionDestroyed = function () {
        sessionStorage.removeItem(STORAGE_ACTIVE_KEY);
    };
})();