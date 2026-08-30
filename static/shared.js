// ═══════════════════════════════════════════════════════════════════════════
// shared.js — Shared helpers for Sightline frontend
//
// Loaded BEFORE app.js and proposal.js via <script> tag. Provides the
// cross-cutting utilities both files need, so they don't have to reach into
// each other's globals or window.*.
//
// NOTE: plain script-tag JS (no modules) — these become browser globals,
// which is fine for this codebase (no build step, same as before).
// ═══════════════════════════════════════════════════════════════════════════

// ── API wrapper with Bearer token ────────────────────────────────────────────
async function api(url, opts = {}) {
  if (!opts.headers) opts.headers = {};
  // Merge existing headers if provided (keep Content-Type etc)
  const tok = typeof getIdToken === 'function' ? getIdToken() : '';
  if (tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  let res = await fetch(url, opts);

  // 401 = token expired → refresh and retry once
  if (res.status === 401 && typeof auth !== 'undefined' && auth.currentUser) {
    try {
      const freshTok = await auth.currentUser.getIdToken(true);
      localStorage.setItem('id_token', freshTok);
      opts.headers['Authorization'] = 'Bearer ' + freshTok;
      res = await fetch(url, opts);
    } catch {
      // Refresh failed — return original 401
    }
  }
  return res;
}

// ── Toast notifications ──────────────────────────────────────────────────────
function toast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  const icons = { success: '\u2713', error: '\u2717', warning: '\u26A0', info: '\u2139' };
  el.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span>${esc(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastOut .3s ease-in forwards';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ── HTML escaping ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
const escHtml = esc;

// ── XSS-safe HTML sanitization ───────────────────────────────────────────────
function sanitizeHtml(html) {
  // Use DOMPurify if available (preferred — battle-tested XSS prevention)
  if (typeof DOMPurify !== 'undefined') {
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: ['b', 'i', 'em', 'strong', 'a', 'p', 'br', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'img', 'hr', 'sup', 'sub', 'del', 'details', 'summary', 'span', 'div'],
      ALLOWED_ATTR: ['href', 'target', 'rel', 'src', 'alt', 'title', 'class', 'id', 'data-url', 'colspan', 'rowspan'],
      ALLOW_DATA_ATTR: false,
    });
  }
  // Fallback: manual sanitization (less robust, but better than nothing)
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  const dangerous = tmp.querySelectorAll('script, iframe, object, embed, form, svg, math, style, link, meta, base');
  dangerous.forEach(el => el.remove());
  const all = tmp.querySelectorAll('*');
  all.forEach(el => {
    const attrs = Array.from(el.attributes);
    attrs.forEach(attr => {
      if (/^on/i.test(attr.name) || attr.value.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attr.name);
      }
    });
    ['href', 'src', 'action', 'formaction', 'xlink:href'].forEach(attrName => {
      const val = el.getAttribute(attrName);
      if (val && val.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attrName);
      }
    });
  });
  return tmp.innerHTML;
}

// ── Expose for proposal.js (legacy window.* contract) ───────────────────────
window.api = api;
window.escHtml = escHtml;
window.toast = toast;
window.sanitizeHtml = sanitizeHtml;

// ── GA4 outbound / cross-surface link tracking ─────────────────────────────
// Fires when the SPA links out to public content (SEO pages, proposal).
// No-op unless gtag is present (analytics off in dev).
document.addEventListener('click', (e) => {
  const a = e.target && e.target.closest ? e.target.closest('a') : null;
  if (!a || !window.gtag) return;
  const href = a.getAttribute('href') || '';
  if (
    href.startsWith('http') ||
    href.startsWith('/bulletins') ||
    href.startsWith('/countries') ||
    href.startsWith('/sitrep/') ||
    href.startsWith('/map')
  ) {
    try {
      window.gtag('event', 'link_click', { link_url: href });
    } catch (_) { /* analytics must never break navigation */ }
  }
}, true);
