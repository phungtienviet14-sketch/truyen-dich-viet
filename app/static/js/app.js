'use strict';

// Treat remote text, localStorage and model output as text at every DOM boundary.
window.ui = Object.freeze({
    element(tag, className = '', text = null) {
        const element = document.createElement(tag);
        element.className = className;
        if (text !== null) element.textContent = String(text);
        return element;
    },
    safeImageURL(value) {
        try {
            const url = new URL(value, window.location.origin);
            return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
        } catch {
            return '';
        }
    },
    toastContents(toast, message, iconName, iconColor) {
        const icon = this.element('i', `w-4 h-4 flex-shrink-0 ${iconColor}`);
        icon.setAttribute('data-lucide', iconName);
        const close = this.element('button', 'text-slate-400 hover:text-white text-xs pl-1', '✕');
        close.type = 'button';
        close.setAttribute('aria-label', 'Đóng thông báo');
        close.addEventListener('click', () => toast.remove());
        toast.setAttribute('role', 'status');
        toast.replaceChildren(icon, this.element('div', 'flex-1 leading-snug', message), close);
    },
});

// Cookies stay HttpOnly; only the per-session CSRF value is exposed to page JS.
(() => {
    const originalFetch = window.fetch.bind(window);
    let csrfPromise = null;
    window.fetch = async (input, options = {}) => {
        const url = new URL(input instanceof Request ? input.url : input, window.location.origin);
        const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
        const authenticated = document.querySelector('meta[name="admin-authenticated"]')?.content === 'true';
        if (authenticated && url.origin === window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
            csrfPromise ||= originalFetch('/api/auth/csrf', { credentials: 'same-origin' }).then(async response => {
                if (!response.ok) throw new Error('Phiên quản trị đã hết hạn. Hãy đăng nhập lại.');
                const data = await response.json();
                if (!data.csrf_token) throw new Error('Không lấy được mã bảo vệ phiên đăng nhập.');
                return data.csrf_token;
            }).catch(error => { csrfPromise = null; throw error; });
            const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
            headers.set('X-CSRF-Token', await csrfPromise);
            return originalFetch(input, { ...options, headers, credentials: 'same-origin' });
        }
        return originalFetch(input, options);
    };
})();

document.addEventListener('click', async event => {
    const logout = event.target.closest('[data-admin-logout]');
    if (logout) {
        try {
            const response = await fetch('/admin/logout', { method: 'POST' });
            if (!response.ok) throw new Error('Không thể đăng xuất. Hãy thử lại.');
            window.location.assign('/admin/login');
        } catch (error) {
            window.showToast(error.message, 'error');
        }
        return;
    }
    const button = event.target.closest('[data-novel-action]');
    if (!button) return;
    const data = button.dataset;
    const id = Number(data.novelId);
    if (!Number.isSafeInteger(id) || id < 1) return;
    if (data.novelAction === 'download') {
        window.openRangeDownloadModal(id, data.title, Number(data.translated), Number(data.total));
    } else if (data.novelAction === 'favorite') {
        window.toggleFavoriteNovel(id, data.title, data.cover, data.author, Number(data.total));
    } else if (data.novelAction === 'vote') {
        await window.handleVoteRequestNovel(id);
    }
});
