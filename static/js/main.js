const api = {
  async request(url, options = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
    };
    const config = { ...defaults, ...options };
    if (config.body && typeof config.body === 'object' && !(config.body instanceof FormData)) {
      config.body = JSON.stringify(config.body);
    }
    if (config.body instanceof FormData) {
      delete config.headers['Content-Type'];
    }
    try {
      const res = await fetch(url, config);
      if (res.status === 401) {
        window.location.href = '/login';
        return null;
      }
      const data = await res.json().catch(() => null);
      if (res.status === 429 || data?.rate_limited) {
        const retryAfter = data?.retry_after || 30;
        const msg = data?.message || "Rate limit reached: Maximum 15 requests per 30 seconds.";
        showRateLimitBadge(retryAfter, msg);
        showToast(msg, "warning");
        unblockButtons();
        return { ok: false, status: 429, rate_limited: true, error: msg, data };
      }
      if (!res.ok) {
        const msg = data?.error || `Request failed (${res.status})`;
        showToast(msg, "error");
        return { ok: false, status: res.status, error: msg, data };
      }
      return { ok: true, status: res.status, data };
    } catch (err) {
      showToast('Network error. Please check your connection.', 'error');
      return { ok: false, error: err.message };
    }
  },
  get: (url) => api.request(url),
  post: (url, body) => api.request(url, { method: 'POST', body }),
  put: (url, body) => api.request(url, { method: 'PUT', body }),
  delete: (url) => api.request(url, { method: 'DELETE' }),
};

let _rlInterval = null;
let _clientReqTracker = [];

function unblockButtons() {
  const btns = document.querySelectorAll(".btn-loading, button[data-original-text], input[data-original-text]");
  btns.forEach((btn) => {
    btn.disabled = false;
    btn.classList.remove("btn-loading");
    const orig = btn.getAttribute("data-original-text");
    if (orig) {
      if (btn.tagName.toLowerCase() === "input") {
        btn.value = orig;
      } else {
        btn.innerHTML = orig;
      }
      btn.removeAttribute("data-original-text");
    }
  });
}
window.unblockButtons = unblockButtons;

function checkClientThrottling(targetUrl) {
  const now = Date.now();
  _clientReqTracker = _clientReqTracker.filter(item => now - item.time < 30000);
  const hits = _clientReqTracker.filter(item => item.url === targetUrl);
  if (hits.length >= 15) {
    const oldest = hits[0].time;
    const retrySec = Math.max(1, Math.ceil((30000 - (now - oldest)) / 1000));
    return { limited: true, retrySec };
  }
  _clientReqTracker.push({ url: targetUrl, time: now });
  return { limited: false, retrySec: 0 };
}

function showRateLimitBadge(seconds = 30, message = null) {
  let badge = document.getElementById("rate-limit-badge");
  if (!badge) {
    badge = document.createElement("div");
    badge.id = "rate-limit-badge";
    badge.className = "rate-limit-floating-badge";
    badge.setAttribute("role", "alert");
    badge.setAttribute("aria-live", "assertive");
    badge.innerHTML = `
      <div class="rl-badge-card">
        <div class="rl-badge-header">
          <span class="rl-badge-pulse" id="rl-pulse-indicator"></span>
          <span class="rl-badge-icon">&#9203;</span>
          <span class="rl-badge-title">Rate Limit Active</span>
          <button type="button" class="rl-badge-close" onclick="dismissRateLimitBadge()" aria-label="Dismiss">&times;</button>
        </div>
        <div class="rl-badge-body">
          <p class="rl-badge-desc" id="rate-limit-badge-desc">${message || "Maximum 15 requests per 30 seconds allowed."}</p>
          <div class="rl-timer-row">
            <span>Cooldown remaining:</span>
            <span id="rate-limit-countdown" class="rl-countdown-pill">${seconds}s</span>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(badge);
  }

  badge.style.display = "block";
  badge.style.opacity = "1";

  const descEl = document.getElementById("rate-limit-badge-desc");
  if (descEl && message) {
    descEl.textContent = message;
  }

  unblockButtons();

  if (_rlInterval) clearInterval(_rlInterval);

  let remaining = parseInt(seconds, 10) || 30;
  const countEl = document.getElementById("rate-limit-countdown");
  const pulseEl = document.getElementById("rl-pulse-indicator");
  if (countEl) countEl.textContent = `${remaining}s`;

  _rlInterval = setInterval(() => {
    remaining -= 1;
    if (countEl) countEl.textContent = `${Math.max(0, remaining)}s`;

    if (remaining <= 0) {
      clearInterval(_rlInterval);
      _rlInterval = null;
      if (pulseEl) pulseEl.classList.add("green");
      if (countEl) countEl.textContent = "Ready";
      if (descEl) descEl.textContent = "Rate limit reset. You can now continue.";
      unblockButtons();
      setTimeout(() => {
        dismissRateLimitBadge();
      }, 2000);
    }
  }, 1000);
}

function dismissRateLimitBadge() {
  if (_rlInterval) {
    clearInterval(_rlInterval);
    _rlInterval = null;
  }
  const badge = document.getElementById("rate-limit-badge");
  if (badge) {
    badge.style.transition = "opacity 0.25s ease";
    badge.style.opacity = "0";
    setTimeout(() => {
      badge.style.display = "none";
      const pulseEl = document.getElementById("rl-pulse-indicator");
      if (pulseEl) pulseEl.classList.remove("green");
    }, 250);
  }
}

window.showRateLimitBadge = showRateLimitBadge;
window.dismissRateLimitBadge = dismissRateLimitBadge;

function showToast(message, type = 'info', duration = 4000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  const icons = { info: '', success: '', warning: '', error: '' };
  toast.innerHTML = `<span>${icons[type] || ''}</span><span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('removing');
    toast.addEventListener('animationend', () => toast.remove());
  }, duration);
}

function openModal(modalId) {
  const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
  if (modal) {
    modal.style.display = '';
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const firstInput = modal.querySelector('input:not([type=hidden]), select, textarea');
    if (firstInput) {
      setTimeout(() => firstInput.focus(), 100);
    }
  }
}

function closeModal(modalId) {
  const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
  if (modal) {
    modal.style.display = '';
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    const remainingOpen = document.querySelectorAll('.modal.open');
    if (remainingOpen.length === 0) {
      document.body.style.overflow = '';
    }
  }
}

window.openModal = openModal;
window.closeModal = closeModal;

document.addEventListener('click', (e) => {
  const closeBtn = e.target.closest('[data-modal-close], .modal-close');
  if (closeBtn) {
    const modalId = closeBtn.getAttribute('data-modal-close');
    if (modalId) {
      closeModal(modalId);
    } else {
      const parentModal = closeBtn.closest('.modal');
      if (parentModal) closeModal(parentModal);
    }
    return;
  }

  const openBtn = e.target.closest('[data-modal-target]');
  if (openBtn) {
    const modalId = openBtn.getAttribute('data-modal-target');
    if (modalId) openModal(modalId);
    return;
  }

  if (e.target.classList.contains('modal') && e.target.classList.contains('open')) {
    closeModal(e.target);
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const openModals = document.querySelectorAll('.modal.open');
    openModals.forEach((m) => {
      closeModal(m);
    });
    toggleSidebar(false);
  }
});

function initOfflineDetection() {
  const banner = document.querySelector('.offline');
  if (!banner) return;

  function updateStatus() {
    if (navigator.onLine) {
      banner.classList.remove('show');
    } else {
      banner.classList.add('show');
    }
  }

  window.addEventListener('online', () => {
    updateStatus();
    showToast('Back online! Syncing data...', 'success');
  });
  window.addEventListener('offline', () => {
    updateStatus();
    showToast('You are offline. Changes will sync later.', 'warning');
  });

  updateStatus();
}

let notifInterval = null;

function initNotifications() {
  const bell = document.querySelector('.notif-bell');
  if (!bell) return;

  async function pollNotifications() {
    const res = await api.get('/api/notifications?unread=1');
    if (res?.ok && res.data) {
      const count = res.data.count || 0;
      const badge = bell.querySelector('.badge');
      if (count > 0) {
        if (badge) {
          badge.textContent = count > 9 ? '9+' : count;
          badge.style.display = 'flex';
        }
      } else if (badge) {
        badge.style.display = 'none';
      }
    }
  }

  pollNotifications();
  notifInterval = setInterval(pollNotifications, 30000);
}

function toggleSidebar(forceState) {
  const sidebar = document.getElementById('sidebar') || document.querySelector('.sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!sidebar) return;

  const isOpen = forceState !== undefined ? forceState : !sidebar.classList.contains('open');
  if (isOpen) {
    sidebar.classList.add('open');
    if (backdrop) backdrop.classList.add('show');
    document.documentElement.classList.add('sidebar-open');
    document.body.classList.add('sidebar-open');
    document.body.style.overflow = 'hidden';
    if (window.AndroidBridge && typeof window.AndroidBridge.setSwipeRefreshEnabled === 'function') {
      window.AndroidBridge.setSwipeRefreshEnabled(false);
    }
  } else {
    sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('show');
    document.documentElement.classList.remove('sidebar-open');
    document.body.classList.remove('sidebar-open');
    document.body.style.overflow = '';
    if (window.AndroidBridge && typeof window.AndroidBridge.setSwipeRefreshEnabled === 'function') {
      const isAtTop = (window.scrollY || document.documentElement.scrollTop || 0) === 0;
      window.AndroidBridge.setSwipeRefreshEnabled(isAtTop);
    }
  }
}

function switchLanguage(lang) {
  fetch('/api/auth/set-lang', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lang: lang })
  }).then(() => {
    window.location.reload();
  }).catch(() => {
    window.location.reload();
  });
}

function confirmAction(message) {
  return window.confirm(message);
}

function validateForm(formEl) {
  let valid = true;
  const fields = formEl.querySelectorAll('[required]');
  fields.forEach((field) => {
    const err = field.closest('.field')?.querySelector('.error-text');
    if (!field.value.trim()) {
      field.classList.add('error');
      if (err) err.textContent = 'This field is required';
      valid = false;
    } else {
      field.classList.remove('error');
      if (err) err.textContent = '';
    }
  });
  return valid;
}

document.addEventListener('DOMContentLoaded', () => {
  initOfflineDetection();
  initNotifications();
  InstantNav.init();

  const toggleBtn = document.getElementById('sidebar-toggle') || document.getElementById('mobileNavToggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleSidebar();
    });
  }

  const backdrop = document.getElementById('sidebar-backdrop');
  if (backdrop) {
    backdrop.addEventListener('click', () => {
      toggleSidebar(false);
    });
  }

  const navItems = document.querySelectorAll('.sidebar .navitem');
  navItems.forEach((item) => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 768) {
        toggleSidebar(false);
      }
    });
  });
});


document.addEventListener('DOMContentLoaded', () => {
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (!form || form.hasAttribute('data-no-block')) return;

    const actionUrl = form.getAttribute("action") || window.location.pathname;
    const throttled = checkClientThrottling(actionUrl);
    if (typeof InstantNav !== "undefined") {
      InstantNav.clearCache();
    }

    if (throttled.limited) {
      e.preventDefault();
      e.stopPropagation();
      showRateLimitBadge(throttled.retrySec, "Rate limit reached: Maximum 15 requests per 30 seconds. Please wait before submitting again.");
      showToast(`Rate limit reached. Please wait ${throttled.retrySec}s.`, "warning");
      unblockButtons();
      return false;
    }

    const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
    if (submitBtn && !submitBtn.disabled) {
      setTimeout(() => {
        submitBtn.disabled = true;
        submitBtn.classList.add('btn-loading');
        
        const isInput = submitBtn.tagName.toLowerCase() === 'input';
        const originalText = isInput ? submitBtn.value : submitBtn.innerHTML;
        submitBtn.setAttribute('data-original-text', originalText);
        
        if (isInput) {
          submitBtn.value = 'Please wait...';
        } else {
          submitBtn.innerHTML = '<span style="display:inline-flex; align-items:center; gap:8px; justify-content:center;"><span class="btn-spinner"></span> <span>Please wait...</span></span>';
        }
      }, 10);
    }
  });
});

// Instant Navigation (Fast-Swap / Pjax) Engine with Touchstart Prefetching
const InstantNav = (function () {
  const _cache = new Map();
  const CACHE_TTL_MS = 60000;
  let _progressBar = null;
  let _progressTimer = null;
  let _currentFetchController = null;

  function getProgressBar() {
    if (!_progressBar) {
      _progressBar = document.getElementById('instant-progress-bar');
      if (!_progressBar) {
        _progressBar = document.createElement('div');
        _progressBar.id = 'instant-progress-bar';
        document.body.appendChild(_progressBar);
      }
    }
    return _progressBar;
  }

  function startProgress() {
    const bar = getProgressBar();
    bar.style.opacity = '1';
    bar.style.width = '30%';
    clearTimeout(_progressTimer);
    _progressTimer = setTimeout(() => {
      bar.style.width = '70%';
    }, 120);
  }

  function finishProgress() {
    const bar = getProgressBar();
    clearTimeout(_progressTimer);
    bar.style.width = '100%';
    setTimeout(() => {
      bar.style.opacity = '0';
      setTimeout(() => {
        bar.style.width = '0%';
      }, 250);
    }, 150);
  }

  function isEligibleLink(anchor) {
    if (!anchor || !anchor.href) return false;
    if (anchor.target && anchor.target !== '_self' && anchor.target !== '') return false;
    if (anchor.hasAttribute('download') || anchor.hasAttribute('data-no-instant')) return false;
    if (anchor.hasAttribute('data-modal-target')) return false;

    const href = anchor.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('tel:') || href.startsWith('mailto:') || href.startsWith('sms:')) {
      return false;
    }

    try {
      const url = new URL(anchor.href, window.location.origin);
      if (url.origin !== window.location.origin) return false;
      const path = url.pathname;
      if (path.includes('/auth/logout') || path.includes('/export') || path.endsWith('.csv') || path.endsWith('.pdf')) {
        return false;
      }
      return true;
    } catch (e) {
      return false;
    }
  }

  async function prefetch(url) {
    try {
      const cleanUrl = new URL(url, window.location.origin).href;
      const cached = _cache.get(cleanUrl);
      if (cached && (Date.now() - cached.timestamp < CACHE_TTL_MS)) {
        return;
      }
      const res = await fetch(cleanUrl, {
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-Instant-Nav': 'true' },
        credentials: 'same-origin'
      });
      if (!res.ok) return;
      const html = await res.text();
      _cache.set(cleanUrl, { html, timestamp: Date.now() });
    } catch (e) {
      // Ignore prefetch network errors
    }
  }

  async function navigate(url, push = true) {
    const targetUrl = new URL(url, window.location.origin).href;
    if (targetUrl === window.location.href && !targetUrl.includes('#')) {
      return;
    }

    startProgress();

    let html = null;
    const cached = _cache.get(targetUrl);
    if (cached && (Date.now() - cached.timestamp < CACHE_TTL_MS)) {
      html = cached.html;
    } else {
      if (_currentFetchController) {
        _currentFetchController.abort();
      }
      _currentFetchController = new AbortController();
      try {
        const res = await fetch(targetUrl, {
          headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-Instant-Nav': 'true' },
          credentials: 'same-origin',
          signal: _currentFetchController.signal
        });
        if (!res.ok) {
          window.location.href = targetUrl;
          return;
        }
        html = await res.text();
        _cache.set(targetUrl, { html, timestamp: Date.now() });
      } catch (err) {
        if (err.name === 'AbortError') return;
        window.location.href = targetUrl;
        return;
      }
    }

    renderPage(html, targetUrl, push);
    finishProgress();
  }

  function renderPage(html, targetUrl, push = true) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    const newPageContent = doc.querySelector('.page-content') || doc.querySelector('.main-content');
    const currentPageContent = document.querySelector('.page-content') || document.querySelector('.main-content');

    if (!newPageContent || !currentPageContent) {
      window.location.href = targetUrl;
      return;
    }

    if (doc.title) {
      document.title = doc.title;
    }

    const newPageTitle = doc.querySelector('.page-title');
    const curPageTitle = document.querySelector('.page-title');
    if (newPageTitle && curPageTitle) {
      curPageTitle.innerHTML = newPageTitle.innerHTML;
    }

    currentPageContent.innerHTML = newPageContent.innerHTML;

    const newSidebarNav = doc.querySelector('.sidebar-nav');
    const curSidebarNav = document.querySelector('.sidebar-nav');
    if (newSidebarNav && curSidebarNav) {
      curSidebarNav.innerHTML = newSidebarNav.innerHTML;
    } else {
      const parsedUrl = new URL(targetUrl);
      const activePath = parsedUrl.pathname;
      document.querySelectorAll('.sidebar-nav a.navitem').forEach(link => {
        const href = link.getAttribute('href');
        if (href && (href === activePath || (href.length > 2 && activePath.startsWith(href)))) {
          link.classList.add('active');
        } else {
          link.classList.remove('active');
        }
      });
    }

    if (push) {
      window.history.pushState({ instantUrl: targetUrl }, doc.title, targetUrl);
    }

    if (typeof toggleSidebar === 'function') {
      toggleSidebar(false);
    }
    document.documentElement.classList.remove('sidebar-open');
    document.body.classList.remove('sidebar-open');
    document.body.style.overflow = '';
    window.scrollTo(0, 0);

    executeScripts(currentPageContent);

    // Reattach sidebar link listener on any newly rendered navitems
    document.querySelectorAll('.sidebar .navitem').forEach((item) => {
      item.addEventListener('click', () => {
        if (window.innerWidth <= 768 && typeof toggleSidebar === 'function') {
          toggleSidebar(false);
        }
      });
    });

    document.dispatchEvent(new CustomEvent('page:loaded', { detail: { url: targetUrl } }));
  }

  function executeScripts(container) {
    const scripts = container.querySelectorAll('script');
    scripts.forEach(oldScript => {
      const newScript = document.createElement('script');
      Array.from(oldScript.attributes).forEach(attr => newScript.setAttribute(attr.name, attr.value));
      newScript.textContent = oldScript.textContent;
      oldScript.parentNode.replaceChild(newScript, oldScript);
    });
  }

  function init() {
    // Touchstart / Pointerenter prefetching for 0ms transitions
    document.addEventListener('pointerenter', (e) => {
      const link = e.target.closest('a');
      if (isEligibleLink(link)) {
        prefetch(link.href);
      }
    }, { passive: true, capture: true });

    document.addEventListener('touchstart', (e) => {
      const link = e.target.closest('a');
      if (isEligibleLink(link)) {
        prefetch(link.href);
      }
    }, { passive: true, capture: true });

    // Intercept clicks on eligible links
    document.addEventListener('click', (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
        return;
      }
      const link = e.target.closest('a');
      if (isEligibleLink(link)) {
        e.preventDefault();
        navigate(link.href, true);
      }
    });

    // Handle back / forward browser & APK navigation
    window.addEventListener('popstate', () => {
      navigate(window.location.href, false);
    });
  }

  return {
    init,
    navigate,
    prefetch,
    clearCache: () => _cache.clear()
  };
})();

// Mobile Double-Tap & Rapid Click Protection on SAME element
(function () {
  let lastClickTime = 0;
  let lastTarget = null;

  document.addEventListener('click', (e) => {
    const clickable = e.target.closest('a, button, input[type="submit"], [role="button"], .navitem');
    if (!clickable) return;

    const now = Date.now();

    // Prevent duplicate rapid double-tap on the exact same element within 350ms
    if (clickable === lastTarget && now - lastClickTime < 350) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }

    lastClickTime = now;
    lastTarget = clickable;
  }, true);
})();

// Real-Time Dashboard Live Invalidation & Sync
(function initDashboardAutoSync() {
  const path = window.location.pathname;
  const isDashboard = path.includes('/dashboard') || path === '/phc' || path.startsWith('/phc/');
  if (!isDashboard) return;

  let currentVer = null;

  async function checkVersion() {
    try {
      const res = await fetch('/api/dashboard/version', { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !data.version) return;

      if (currentVer === null) {
        currentVer = data.version;
      } else if (data.version > currentVer) {
        currentVer = data.version;
        showToast('Database updated. Refreshing dashboard...', 'info', 2000);
        setTimeout(() => {
          window.location.reload();
        }, 1200);
      }
    } catch (e) {
      // Ignore network blips during polling
    }
  }

  // Initial check
  checkVersion();

  // Poll every 25s
  setInterval(checkVersion, 25000);

  // Check immediately when user switches back to this tab
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      checkVersion();
    }
  });
})();
