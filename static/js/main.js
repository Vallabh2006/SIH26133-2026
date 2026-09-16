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
      if (!res.ok) {
        const msg = data?.error || `Request failed (${res.status})`;
        showToast(msg, 'error');
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
    if (window.innerWidth <= 768) {
      document.body.style.overflow = 'hidden';
    }
  } else {
    sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('show');
    document.body.style.overflow = '';
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
