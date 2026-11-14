(function () {
  'use strict';

  function utm() {
    var params = new URLSearchParams(window.location.search);
    var out = {};
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content'].forEach(function (key) {
      if (params.get(key)) out[key] = params.get(key);
    });
    return out;
  }

  document.addEventListener('submit', function (event) {
    var form = event.target.closest('[data-lead-form]');
    if (!form) return;
    event.preventDefault();
    var status = form.querySelector('.lead-status');
    var button = form.querySelector('button[type="submit"]');
    var data = new FormData(form);
    var payload = {
      email: data.get('email') || '',
      name: data.get('name') || '',
      organization: data.get('organization') || '',
      source: form.dataset.source || 'site',
      consent: data.get('consent') === 'on',
      website: data.get('website') || '',
      page: window.location.pathname
    };
    Object.assign(payload, utm());
    if (status) { status.textContent = 'Saving…'; status.className = 'lead-status'; }
    if (button) button.disabled = true;
    fetch('/api/leads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function (resp) {
      return resp.json().then(function (body) { return { ok: resp.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok) throw new Error(result.body.error || 'Could not save');
      if (status) { status.textContent = 'You are on the list. Thank you.'; status.className = 'lead-status ok'; }
      form.reset();
      if (window.sightlineTrack) {
        window.sightlineTrack(form.dataset.leadEvent || 'newsletter_signup', {
          source: payload.source,
          page_path: window.location.pathname
        });
      }
    }).catch(function (err) {
      if (status) { status.textContent = err.message || 'Could not save. Please retry.'; status.className = 'lead-status bad'; }
    }).finally(function () {
      if (button) button.disabled = false;
    });
  });
}());
