(function () {
  'use strict';

  var config = document.currentScript;
  var client = config ? (config.dataset.client || '') : '';
  if (!/^ca-pub-\d+$/.test(client)) return;

  function hasSignedInUser() {
    try {
      return Boolean(window.__idToken || localStorage.getItem('id_token'));
    } catch {
      return false;
    }
  }

  function hideAdSlots() {
    document.querySelectorAll('.crisis-ad, .seo-ad').forEach(function (element) {
      element.hidden = true;
    });
  }

  function initializeAdSlots() {
    document.querySelectorAll('ins.adsbygoogle').forEach(function (slot) {
      if (slot.dataset.initialized === 'true') return;
      slot.dataset.initialized = 'true';
      try { (window.adsbygoogle = window.adsbygoogle || []).push({}); } catch { /* Ad blockers may intervene. */ }
    });
  }

  function start() {
    if (hasSignedInUser()) {
      hideAdSlots();
      return;
    }
    var loader = document.createElement('script');
    loader.async = true;
    loader.crossOrigin = 'anonymous';
    loader.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' + encodeURIComponent(client);
    loader.addEventListener('load', initializeAdSlots, { once: true });
    document.head.appendChild(loader);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
}());
