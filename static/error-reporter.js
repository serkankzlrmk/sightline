// ═══════════════════════════════════════════════════════════════
// error-reporter.js — client-side error capture (best-effort)
//
// Reports uncaught JS errors and unhandled promise rejections to
// POST /api/client-errors. The endpoint is rate-limited server-side; this
// module additionally caps reports per page load to avoid storms.
// ═══════════════════════════════════════════════════════════════

(function () {
  let sent = 0;
  const MAX_PER_PAGE = 20;

  function release() {
    const meta = document.querySelector('meta[name="sightline-release"]');
    return (meta && meta.content) || window.SIGHTLINE_RELEASE || 'dev';
  }

  function reportClientError(payload) {
    try {
      if (sent >= MAX_PER_PAGE) return;
      sent += 1;
      const body = JSON.stringify(Object.assign({}, payload || {}, {
        release: release(),
        request_id: window.__lastRequestId || '',
        route: (payload && payload.route) || (window.location.pathname + window.location.hash),
      }));
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon('/api/client-errors', blob)) return;
      }
      fetch('/api/client-errors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
      }).catch(function () { /* reporting must never throw */ });
    } catch {
      /* ignore */
    }
  }

  function shouldIgnore(message) {
    return /ResizeObserver|Script error\.|extension context|moz-extension|chrome-extension|AbortError/i.test(String(message || ''));
  }

  window.reportClientError = reportClientError;
  window.SIGHTLINE_RELEASE = release();

  window.addEventListener('error', function (event) {
    if (!event || !event.message || shouldIgnore(event.message)) return;
    reportClientError({
      kind: 'frontend',
      message: event.message,
      source: event.filename || '',
      lineno: event.lineno || 0,
      colno: event.colno || 0,
      stack: (event.error && event.error.stack) || '',
    });
  });

  window.addEventListener('unhandledrejection', function (event) {
    const reason = event && event.reason;
    const message = (reason && (reason.message || String(reason))) || 'Unhandled promise rejection';
    if (shouldIgnore(message)) return;
    reportClientError({
      kind: 'frontend',
      message,
      stack: (reason && reason.stack) || '',
    });
  });
})();
