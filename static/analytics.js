(function () {
  'use strict';

  var script = document.currentScript;
  var measurementId = script ? (script.dataset.measurementId || '') : '';
  if (!/^G-[A-Z0-9]+$/i.test(measurementId)) return;

  var storageKey = 'sightline_analytics_consent_v1';
  var consent = readConsent();
  var loaded = false;

  function readConsent() {
    try {
      var value = localStorage.getItem(storageKey);
      return value === 'granted' || value === 'denied' ? value : 'unknown';
    } catch {
      return 'unknown';
    }
  }

  function storeConsent(value) {
    try { localStorage.setItem(storageKey, value); } catch { /* Storage may be unavailable. */ }
    consent = value;
  }

  function loadGoogleTag() {
    if (loaded || consent !== 'granted') return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {
      analytics_storage: 'denied',
      ad_storage: 'denied',
      ad_user_data: 'denied',
      ad_personalization: 'denied',
      functionality_storage: 'granted',
      security_storage: 'granted'
    });
    window.gtag('consent', 'update', { analytics_storage: 'granted' });
    window.gtag('js', new Date());
    window.gtag('config', measurementId, {
      send_page_view: true,
      cookie_flags: 'SameSite=Lax;Secure',
      allow_google_signals: false,
      allow_ad_personalization_signals: false
    });

    var loader = document.createElement('script');
    loader.async = true;
    loader.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(measurementId);
    document.head.appendChild(loader);

  }

  window.sightlineTrack = function (name, parameters) {
    if (!name || consent !== 'granted' || !loaded) return;
    var safeParameters = parameters && typeof parameters === 'object' ? parameters : {};
    window.gtag('event', name, safeParameters);
  };

  function removeBanner() {
    var banner = document.getElementById('sightline-consent');
    if (banner) banner.remove();
  }

  function choose(value) {
    storeConsent(value);
    removeBanner();
    if (value === 'granted') {
      loadGoogleTag();
    }
    window.dispatchEvent(new CustomEvent('sightline:consent', { detail: { analytics: value } }));
  }

  function showBanner() {
    if (document.getElementById('sightline-consent')) return;
    var banner = document.createElement('section');
    banner.id = 'sightline-consent';
    banner.className = 'sightline-consent';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Analytics preferences');
    banner.innerHTML =
      '<div class="sightline-consent__copy">' +
        '<strong>Help us improve Sightline</strong>' +
        '<p>Optional analytics show us which public information is useful. We do not load Google Analytics until you accept.</p>' +
        '<a href="/privacy">Privacy policy</a>' +
      '</div>' +
      '<div class="sightline-consent__actions">' +
        '<button type="button" data-consent-choice="denied">Decline</button>' +
        '<button type="button" class="is-primary" data-consent-choice="granted">Accept analytics</button>' +
      '</div>';
    document.body.appendChild(banner);
    banner.querySelectorAll('[data-consent-choice]').forEach(function (button) {
      button.addEventListener('click', function () { choose(button.dataset.consentChoice); });
    });
  }

  window.sightlineOpenPrivacyChoices = function () {
    storeConsent('unknown');
    showBanner();
  };

  document.addEventListener('click', function (event) {
    var privacyChoice = event.target.closest('[data-privacy-choices]');
    if (privacyChoice) {
      event.preventDefault();
      window.sightlineOpenPrivacyChoices();
      return;
    }
    var tracked = event.target.closest('[data-track-event]');
    if (!tracked) return;
    window.sightlineTrack(tracked.dataset.trackEvent, {
      cta_name: tracked.dataset.trackName || '',
      cta_location: tracked.dataset.trackLocation || '',
      link_url: tracked.getAttribute('href') || '',
      page_path: window.location.pathname
    });
  }, true);

  if (consent === 'granted') {
    loadGoogleTag();
  } else if (consent === 'unknown') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', showBanner, { once: true });
    } else {
      showBanner();
    }
  }
}());
