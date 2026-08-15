// ═══════════════════════════════════════════════════════════════
// map.js — Crisis Map (Leaflet, country cards, GDACS banners) — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

function isWorldMapVisible(container = document.getElementById('world-map')) {
  const panel = document.getElementById('panel-crisis-map');
  if (!container || !panel || !panel.classList.contains('active')) return false;
  const rect = container.getBoundingClientRect();
  return rect.width >= 100 && rect.height >= 100;
}

function scheduleWorldMapResize() {
  if (!leafletMap || !isWorldMapVisible()) return;
  if (leafletResizeFrame) cancelAnimationFrame(leafletResizeFrame);
  leafletResizeFrame = requestAnimationFrame(() => {
    leafletResizeFrame = 0;
    if (leafletMap && isWorldMapVisible()) {
      leafletMap.invalidateSize({ animate: false, pan: false });
    }
  });
}

function observeWorldMapSize(container) {
  if (leafletResizeObserver || typeof ResizeObserver === 'undefined') return;
  leafletResizeObserver = new ResizeObserver(() => scheduleWorldMapResize());
  leafletResizeObserver.observe(container);
}

function initWorldMap() {
  const container = document.getElementById('world-map');
  if (!container) return;

  // Leaflet calculates its internal grid from the container's first size.
  // Never initialize it inside a hidden (0 x 0) tab.
  if (!isWorldMapVisible(container)) return;

  if (typeof L === 'undefined') {
    container.innerHTML = '<div class="center-loading dash-weekly-loading">Loading map…</div>';
    let retries = 0;
    const tryInit = () => {
      if (typeof L !== 'undefined') {
        initWorldMap();
      } else if (retries < 10) {
        retries++;
        setTimeout(tryInit, 500);
      } else {
        container.innerHTML = '<div class="center-loading dash-weekly-loading">Map unavailable. Please refresh.</div>';
      }
    };
    setTimeout(tryInit, 500);
    return;
  }

  if (leafletMap) {
    updateMapMarkers();
    scheduleWorldMapResize();
    return;
  }

  try {
    leafletMap = L.map(container, {
      center: [20, 15],
      zoom: 3,
      minZoom: 3,
      maxZoom: 8,
      zoomControl: true,
      attributionControl: false,
      worldCopyJump: true,
      scrollWheelZoom: true,
      doubleClickZoom: true,
      dragging: true,
      touchZoom: true,
    });

    // Tile layer with automatic fallback: CARTO primary, OSM as backup.
    // If a CDN is blocked/slow (different regions/ISPs), the map still loads.
    const TILE_PROVIDERS = [
      {
        url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        options: {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
          subdomains: 'abcd',
          maxZoom: 19,
        },
      },
      {
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        options: {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19,
        },
      },
    ];

    function addTileLayerWithFallback(map, index) {
      if (index >= TILE_PROVIDERS.length) return;
      const provider = TILE_PROVIDERS[index];
      const layer = L.tileLayer(provider.url, provider.options).addTo(map);
      let failed = 0;
      layer.on('tileerror', () => {
        failed += 1;
        // After a few failed tiles, switch to the next provider
        if (failed >= 3 && index < TILE_PROVIDERS.length - 1) {
          map.removeLayer(layer);
          addTileLayerWithFallback(map, index + 1);
        }
      });
    }
    addTileLayerWithFallback(leafletMap, 0);

    // No scroll interception — let Leaflet handle zoom natively
    observeWorldMapSize(container);
    scheduleWorldMapResize();
  } catch (err) {
    console.error('[map] Leaflet init error:', err);
    container.innerHTML = '<div class="center-loading dash-weekly-loading">Map unavailable.</div>';
    return;
  }

  updateMapMarkers();
}

let leafletMarkerGroup = null;   // L.FeatureGroup for all markers (efficient batch ops)

function updateMapMarkers() {
  if (!leafletMap || typeof L === 'undefined') return;

  // Remove previous marker group in one shot
  if (leafletMarkerGroup) {
    leafletMap.removeLayer(leafletMarkerGroup);
  }
  leafletMarkerGroup = L.featureGroup();
  leafletMarkers = [];

  const crises = Object.values(crisisMapData);
  if (!crises.length) return;

  // GDACS-driven marker color: Red alert → red, Orange → orange,
  // no active alert → green (calm state). Severity does NOT drive the
  // marker color — only live GDACS alerts do.
  function crisisColor(c) {
    const alerts = (c && c.gdacs_alerts) || [];
    const top = alerts.find(a => a.alert_level === 'Red') || alerts.find(a => a.alert_level === 'Orange') || alerts[0];
    if (top) {
      if (top.alert_level === 'Red') return '#ef4444';
      if (top.alert_level === 'Orange') return '#f59e0b';
      return '#22c55e'; // Green alert level — still an event, calm-ish
    }
    return '#22c55e'; // No active alert → calm green
  }

  crises.forEach(c => {
    const lat = c.coords?.lat;
    const lng = c.coords?.lng;
    if (!lat || !lng) return;

    const color = crisisColor(c);
    const sevClass = (c.severity === 'high') ? 'severity-high' : (c.severity === 'medium') ? 'severity-medium' : 'severity-low';

    const icon = L.divIcon({
      className: 'crisis-marker',
      html: `<div class="crisis-marker-dot ${sevClass}" style="background:${color};box-shadow:0 0 6px ${color}aa;"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });

    const marker = L.marker([lat, lng], { icon })
      .on('click', () => openCountryCard(c));

    leafletMarkerGroup.addLayer(marker);
    leafletMarkers.push(marker);
  });

  // Add entire group to map at once
  leafletMarkerGroup.addTo(leafletMap);

  // Only fit bounds on first load, not on zoom/pan
  if (!window._mapBoundsSet) {
    leafletMap.fitBounds(leafletMarkerGroup.getBounds().pad(0.3));
    window._mapBoundsSet = true;
  }
}

function openCountryCard(crisis) {
  const panel = document.getElementById('dash-crisis-panel');
  const countryEl = document.getElementById('dash-crisis-panel-country');
  const bodyEl = document.getElementById('dash-crisis-panel-body');
  if (!panel || !countryEl || !bodyEl) return;

  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;
  const country = crisis.country || '';
  const sevColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
  const sevLabels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
  const color = sevColors[crisis.severity] || '#007AFF';

  // Look up full data from mapCountries
  const fullData = mapCountries[country] || {};

  countryEl.textContent = country;

  // Show loading state
  bodyEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">Loading country intelligence...</div>';
  panel.classList.add('open');
  // Note: don't add panel-open class to map — it causes resize/marker lag
  // The crisis panel overlays the map absolutely, no layout shift needed

  // If we have narrative data from /api/map/countries (now always generated
  // deterministically server-side), render the full card immediately.
  if (fullData.narrative || fullData.headline) {
    renderCountryCard(bodyEl, fullData, color, sevLabels, isAuthed);
  } else if (isAuthed) {
    // Authed: fetch full country summary
    api('/api/country/' + encodeURIComponent(country) + '/summary')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) {
          renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
          return;
        }
        renderCountryCard(bodyEl, data, color, sevLabels, isAuthed);
      })
      .catch(() => {
        renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
      });
  } else {
    // Preview mode: show what we have from map data + register prompt
    renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
  }
}

function renderCountryCard(bodyEl, data, color, sevLabels, isAuthed) {
  let html = '';
  const severity = data.severity || 'low';

  // ── GDACS Active Disaster Banner (priority over severity badge) ──
  // If there's a live disaster alert, surface it prominently with
  // alert-level color coding (Red/Orange/Green). If NOT, show a calm
  // green "no active alert" state instead of a loud severity label.
  const gdacs = data.gdacs_alerts || [];
  const topAlert = gdacs.find(a => a.alert_level === 'Red') || gdacs.find(a => a.alert_level === 'Orange') || gdacs[0] || null;
  if (topAlert) {
    const alertColor = topAlert.alert_level === 'Red' ? '#ef4444' : topAlert.alert_level === 'Orange' ? '#f59e0b' : '#22c55e';
    html += `<div class="crisis-gdacs-banner" style="display:flex;align-items:center;gap:10px;background:${alertColor}14;border:1px solid ${alertColor}55;border-left:4px solid ${alertColor};border-radius:8px;padding:10px 12px;margin-bottom:10px;">`;
    html += `<div style="flex-shrink:0;width:34px;height:34px;border-radius:8px;background:${alertColor};color:#fff;display:flex;align-items:center;justify-content:center;font-size:17px;">⚠️</div>`;
    html += `<div style="flex:1;min-width:0;">`;
    html += `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;"><span style="color:${alertColor};font-weight:800;font-size:12px;letter-spacing:.8px;">${esc(topAlert.alert_level || 'ACTIVE')} ALERT</span><span style="font-size:11px;color:var(--text-muted);">${esc(topAlert.event_type || 'Disaster')}</span></div>`;
    html += `<div style="font-size:13px;font-weight:600;color:var(--text);margin-top:2px;">${esc(topAlert.title || '')}</div>`;
    if (topAlert.from_date) html += `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">${esc(String(topAlert.from_date).substring(0, 10))}${topAlert.to_date ? ' → ' + esc(String(topAlert.to_date).substring(0, 10)) : ''}</div>`;
    html += `</div></div>`;
  } else {
    // No active disaster — calm green state (no loud severity color)
    html += `<div class="crisis-gdacs-banner" style="display:flex;align-items:center;gap:10px;background:#22c55e14;border:1px solid #22c55e44;border-left:4px solid #22c55e;border-radius:8px;padding:10px 12px;margin-bottom:10px;">`;
    html += `<div style="flex-shrink:0;width:34px;height:34px;border-radius:8px;background:#22c55e;color:#fff;display:flex;align-items:center;justify-content:center;font-size:17px;">✓</div>`;
    html += `<div style="flex:1;min-width:0;">`;
    html += `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;"><span style="color:#22c55e;font-weight:800;font-size:12px;letter-spacing:.8px;">NO ACTIVE ALERT</span><span style="font-size:11px;color:var(--text-muted);">GDACS monitored</span></div>`;
    html += `<div style="font-size:12px;color:var(--text-muted);margin-top:2px;">No live disaster alert for this country.</div>`;
    html += `</div></div>`;
  }

  // Severity badge (compact — informational, not the primary signal)
  html += `<span class="crisis-severity-badge" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[severity] || ''}</span>`;

  // Last updated date
  const lastUpdated = data.last_updated || (data.date_range && data.date_range.max_date) || '';
  if (lastUpdated) {
    const dateStr = lastUpdated.length > 10 ? lastUpdated.substring(0, 10) : lastUpdated;
    html += `<div class="crisis-meta" style="margin-bottom:8px;"><span class="crisis-meta-item" style="color:var(--text-muted);font-size:11px;">Updated ${esc(dateStr)}</span>`;
    if (data.report_count) html += `<span class="crisis-meta-item" style="font-size:11px;"><strong>${data.report_count}</strong> reports</span>`;

    // Per-source freshness (HDX / GDACS)
    const freshParts = [];
    if (data.hdx_fetched_at) {
      const daysAgo = Math.floor((Date.now() / 1000 - data.hdx_fetched_at) / 86400);
      freshParts.push(`HDX ${daysAgo <= 0 ? 'today' : daysAgo + 'd ago'}`);
    }
    if (data.gdacs_fetched_at) {
      const daysAgo = Math.floor((Date.now() / 1000 - data.gdacs_fetched_at) / 86400);
      freshParts.push(`GDACS ${daysAgo <= 0 ? 'today' : daysAgo + 'd ago'}`);
    }
    if (freshParts.length) {
      html += `<span class="crisis-meta-item" style="color:var(--text-muted);font-size:11px;">${freshParts.map(esc).join(' · ')}</span>`;
    }
    html += `</div>`;
  }

  if (data.headline) {
    html += `<div class="crisis-headline">${esc(data.headline)}</div>`;
  }

  // (narrative line removed — same info already shown as chips/sections)

  // Reporting Organizations — straight from DB, no LLM
  if (data.top_sources && data.top_sources.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Reporting Organizations</div>`;
    html += `<div class="country-card-sources">`;
    data.top_sources.slice(0, 5).forEach(s => {
      const name = (typeof s === 'string') ? s : (s.name || '');
      const count = (typeof s === 'string') ? '' : (s.count != null ? ` · ${s.count}` : '');
      if (name) html += `<span class="crisis-theme-tag">${esc(name)}${esc(String(count))}</span>`;
    });
    html += `</div></div>`;
  }

  if (data.hdx_key_figures && data.hdx_key_figures.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Key Figures</div>`;
    html += `<div class="country-card-figures">`;
    data.hdx_key_figures.forEach(f => {
      html += `<div class="country-card-figure"><span class="country-card-figure-value">${esc(String(f.value || ''))}</span><span class="country-card-figure-label">${esc(f.label || '')}</span></div>`;
    });
    html += `</div>`;
    // Active organizations (from HDX operational presence) — shown as chips
    const activeOrgFig = data.hdx_key_figures.find(f => f.orgs && f.orgs.length);
    if (activeOrgFig && activeOrgFig.orgs && activeOrgFig.orgs.length) {
      html += `<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:8px;">`;
      activeOrgFig.orgs.slice(0, 6).forEach(o => {
        html += `<span class="crisis-theme-tag" style="font-size:10px;">${esc(o)}</span>`;
      });
      html += `</div>`;
    }
    html += `</div>`;
  }

  if (data.gdacs_alerts && data.gdacs_alerts.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Active Alerts</div>`;
    data.gdacs_alerts.forEach(a => {
      const alertColor = a.alert_level === 'Red' ? '#ef4444' : a.alert_level === 'Orange' ? '#f59e0b' : '#22c55e';
      html += `<div class="country-card-alert"><span class="country-card-alert-badge" style="background:${alertColor}1a;color:${alertColor};">${esc(a.alert_level || '')}</span> ${esc(a.event_type || '')} — ${esc(a.title || '')}</div>`;
    });
    html += `</div>`;
  }

  if (data.top_themes && data.top_themes.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Themes</div>`;
    html += `<div class="crisis-themes">${data.top_themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
    html += `</div>`;
  }

  if (data.recent_reports && data.recent_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Recent Reports</div>`;
    html += `<div class="country-card-reports">`;
    data.recent_reports.slice(0, 5).forEach(r => {
      html += `<div class="country-card-report"><a href="${esc(r.url || '#')}" target="_blank" rel="noopener">${esc(r.title || '')}</a><span class="country-card-report-meta">${esc(r.date || '')} · ${esc(r.source || '')}</span></div>`;
    });
    html += `</div></div>`;
  }

  if (data.worldbank_indicators && Object.keys(data.worldbank_indicators).length > 0) {
    const wbLabels = {
      gdp_per_capita: 'GDP per capita (USD)',
      population: 'Population',
      life_expectancy: 'Life expectancy (years)',
      poverty_rate: 'Poverty rate (%)',
      electricity_access: 'Electricity access (%)',
    };
    html += `<div class="country-card-section"><div class="country-card-section-title">Country Profile</div>`;
    html += `<div class="country-card-figures">`;
    for (const [key, val] of Object.entries(data.worldbank_indicators)) {
      if (val && val.value) {
        const label = wbLabels[key] || key.replace(/_/g, ' ');
        html += `<div class="country-card-figure"><span class="country-card-figure-value">${esc(String(val.value))}</span><span class="country-card-figure-label">${esc(label)} · ${esc(val.year || '')}</span></div>`;
      }
    }
    html += `</div></div>`;
  }

  if (data.sitrep_reports && data.sitrep_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">SITREP Reports</div>`;
    data.sitrep_reports.forEach(f => {
      html += `<div class="country-card-report"><a href="#" onclick="switchTab('sitrep');setTimeout(()=>{document.querySelectorAll('#sitrep-reports-list .report-item').forEach(i=>{if(i.textContent.includes('${esc(data.country)}'))i.click()})},300);return false;">${esc(f)}</a></div>`;
    });
    html += `</div>`;
  }

  // Preview lock — anonymous users see the card but get a register prompt
  if (!isAuthed) {
    html += `<div class="preview-lock-msg"><div class="preview-lock-text">Register to view full report sources and SITREP analysis.</div><button class="preview-lock-btn">Register</button></div>`;
  } else if (data.has_sitrep) {
    html += `<button class="crisis-sitrep-btn" data-action="dash-view-crisis" data-country="${esc(data.country)}">View SITREP →</button>`;
  }

  bodyEl.innerHTML = html;
}

function renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels) {
  let html = '';
  html += `<span class="crisis-severity-badge" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[crisis.severity] || ''}</span>`;
  if (crisis.headline) html += `<div class="crisis-headline">${esc(crisis.headline)}</div>`;
  if (crisis.summary || crisis.narrative) html += `<div class="crisis-summary">${esc(crisis.summary || crisis.narrative)}</div>`;
  html += `<div class="crisis-meta">`;
  if (crisis.report_count) html += `<span class="crisis-meta-item"><strong>${crisis.report_count}</strong> reports</span>`;
  // Show last updated date
  const lastUpdated = crisis.last_updated || (crisis.date_range && crisis.date_range.max_date) || '';
  if (lastUpdated) {
    const dateStr = lastUpdated.length > 10 ? lastUpdated.substring(0, 10) : lastUpdated;
    html += `<span class="crisis-meta-item" style="color:var(--text-muted);">Updated ${esc(dateStr)}</span>`;
  }
  html += `</div>`;
  if (crisis.themes && crisis.themes.length) {
    html += `<div class="crisis-themes">${crisis.themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
  } else if (crisis.top_themes && crisis.top_themes.length) {
    html += `<div class="crisis-themes">${crisis.top_themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
  }
  // Reporting Organizations (from map data, DB-driven)
  if (crisis.top_sources && crisis.top_sources.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Reporting Organizations</div>`;
    html += `<div class="country-card-sources">`;
    crisis.top_sources.slice(0, 5).forEach(s => {
      const name = (typeof s === 'string') ? s : (s.name || '');
      const count = (typeof s === 'string') ? '' : (s.count != null ? ` · ${s.count}` : '');
      if (name) html += `<span class="crisis-theme-tag">${esc(name)}${esc(String(count))}</span>`;
    });
    html += `</div></div>`;
  }
  // Show recent reports (from map data)
  if (crisis.recent_reports && crisis.recent_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Latest Reports</div>`;
    html += `<div class="country-card-reports">`;
    crisis.recent_reports.slice(0, 3).forEach(r => {
      html += `<div class="country-card-report"><a href="${esc(r.url || '#')}" target="_blank" rel="noopener">${esc(r.title || '')}</a><span class="country-card-report-meta">${esc(r.date || '')} · ${esc(r.source || '')}</span></div>`;
    });
    html += `</div></div>`;
  }
  if (!isAuthed) {
    html += `<div class="preview-lock-msg"><div class="preview-lock-text">Register to view report sources and full SITREP analysis.</div><button class="preview-lock-btn">Register</button></div>`;
  } else if (crisis.has_sitrep) {
    html += `<button class="crisis-sitrep-btn" data-action="dash-view-crisis" data-country="${esc(crisis.country)}">View SITREP →</button>`;
  }
  bodyEl.innerHTML = html;
}

function closeCrisisPanel() {
  const panel = document.getElementById('dash-crisis-panel');
  if (panel) panel.classList.remove('open');
  // No panel-open class to remove — map stays full-screen
}

// (removed: viewCrisisSitrep was dead code — 'dash-view-crisis' action
// handles country navigation inline in the event delegation switch)




document.addEventListener('DOMContentLoaded', () => {
  // Menu navigation hint tooltip logic (appears on load, fades out after 5s or on click)
  const menuHint = document.getElementById('menu-hint-tooltip');
  if (menuHint) {
    setTimeout(() => {
      menuHint.classList.add('visible');
    }, 600);

    const hideHint = () => {
      menuHint.classList.remove('visible');
    };

    setTimeout(hideHint, 5000);
    const hamBtn = document.getElementById('hamburger-btn');
    if (hamBtn) hamBtn.addEventListener('click', hideHint, { once: true });
    document.addEventListener('click', hideHint, { once: true });
  }

  // Legal modal
  const termsLink = document.getElementById('terms-link');
  const privacyLink = document.getElementById('privacy-link');
  const legalModal = document.getElementById('legal-modal');
  const legalTitle = document.getElementById('legal-modal-title');
  const legalBody = document.getElementById('legal-modal-body');
  const legalClose = document.getElementById('legal-modal-close');

  const legalContent = {
    terms: `<h4>1. Acceptance</h4>
<p>By accessing and using Sightline, you agree to be bound by these Terms of Use. If you do not agree, please do not use the service.</p>
<h4>2. Purpose</h4>
<p>Sightline is a humanitarian data analytics platform that aggregates publicly available information from ReliefWeb and HDX to support humanitarian analysis, research, and decision-making.</p>
<h4>3. Data Sources</h4>
<p>All data displayed on Sightline originates from publicly accessible humanitarian sources, primarily the ReliefWeb API and the HDX HAPI API. We do not claim ownership of source data. All rights to original data remain with their respective publishers.</p>
<h4>4. AI-Generated Content</h4>
<p>Sightline uses AI to analyze data and generate situation reports, summaries, and responses. AI-generated content may contain inaccuracies. Users should verify critical information against original sources. Every AI response includes citations to source documents.</p>
<h4>5. User Conduct</h4>
<ul>
<li>Use the service only for lawful humanitarian analysis purposes</li>
<li>Do not attempt to overwhelm or disrupt the service</li>
<li>Do not misrepresent AI-generated content as official humanitarian guidance</li>
<li>Respect intellectual property rights of data publishers</li>
</ul>
<h4>6. Disclaimer</h4>
<p>Sightline is provided "as is" without warranties of any kind. We make no guarantees about accuracy, completeness, or timeliness of data or AI-generated content. The service is not a substitute for professional humanitarian assessment.</p>
<h4>7. Changes</h4>
<p>We may update these terms at any time. Continued use after changes constitutes acceptance.</p>`,
    privacy: `<h4>Data We Collect</h4>
<ul>
<li><strong>Authentication data:</strong> Google account email and display name when you sign in</li>
<li><strong>Usage data:</strong> Chat messages, SITREP reports, and bulletin requests you create</li>
<li><strong>Analytics:</strong> We do not use third-party analytics or tracking services</li>
</ul>
<h4>Data We Do NOT Collect</h4>
<ul>
<li>We do not sell, share, or distribute your personal data to third parties</li>
<li>We do not use your data for advertising</li>
<li>We do not track your browsing across other websites</li>
<li>We do not collect device fingerprints or location data</li>
</ul>
<h4>Data Storage</h4>
<p>Your chat history and reports are stored securely on our servers and are accessible only to you through your authenticated session. You can delete your data at any time by contacting us.</p>
<h4>Security</h4>
<p>We use industry-standard encryption (HTTPS/TLS) for all data in transit. Authentication is handled through Firebase Auth with Google Sign-In. Access tokens are validated on every request.</p>
<h4>Your Rights</h4>
<ul>
<li>Access your data at any time through the platform</li>
<li>Request deletion of your account and all associated data</li>
<li>Withdraw consent by discontinuing use of the service</li>
</ul>
<h4>Contact</h4>
<p>For privacy inquiries or data deletion requests, please contact us through the platform.</p>`
  };

  function showLegal(type) {
    if (!legalModal || !legalTitle || !legalBody) return;
    legalTitle.textContent = type === 'terms' ? 'Terms of Use' : 'Privacy Policy';
    legalBody.innerHTML = legalContent[type] || '';
    legalModal.classList.add('open');
  }

  if (termsLink) termsLink.addEventListener('click', (e) => { e.preventDefault(); showLegal('terms'); });
  if (privacyLink) privacyLink.addEventListener('click', (e) => { e.preventDefault(); showLegal('privacy'); });
  if (legalClose) legalClose.addEventListener('click', () => { legalModal.classList.remove('open'); });
  if (legalModal) legalModal.addEventListener('click', (e) => { if (e.target === legalModal) legalModal.classList.remove('open'); });

  // Crisis panel close button
  const crisisPanelClose = document.getElementById('dash-crisis-panel-close');
  if (crisisPanelClose) crisisPanelClose.addEventListener('click', closeCrisisPanel);

  // Country search on map
  const searchInput = document.getElementById('map-search-input');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        const query = e.target.value.toLowerCase().trim();
        if (!query || !leafletMap) return;
        for (const [country, data] of Object.entries(crisisMapData)) {
          if (country.toLowerCase().includes(query)) {
            const coords = data.coords || { lat: 0, lng: 0 };
            if (coords.lat && coords.lng) {
              leafletMap.setView([coords.lat, coords.lng], 5);
              openCountryCard(data);
              break;
            }
          }
        }
      }, 300);
    });
  }

  // Mobile bottom tab bar
  document.querySelectorAll('.mobile-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Mobile user button (logout)
  const mobileUserBtn = document.getElementById('mobile-user-btn');
  if (mobileUserBtn) {
    mobileUserBtn.addEventListener('click', () => {
      if (typeof signOut === 'function') {
        if (confirm('Sign out of Sightline?')) signOut();
      }
    });
  }

  // Agent DOM refs
  chatInput = document.getElementById('chat-input');
  sendBtn = document.getElementById('send-btn');
  chatDiv = document.getElementById('chat-messages');
  busyDot = document.getElementById('busy-dot');

  // Model selector
  const modelToggle = document.getElementById('model-selector-toggle');
  const modelMenu = document.getElementById('model-menu');
  if (modelToggle && modelMenu) {
    modelToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      modelMenu.classList.toggle('open');
    });
    document.addEventListener('click', () => modelMenu.classList.remove('open'));
    modelMenu.addEventListener('click', (e) => e.stopPropagation());
    modelMenu.querySelectorAll('.model-option').forEach(opt => {
      opt.addEventListener('click', () => {
        const key = opt.dataset.model;
        if (!key) return;
        const cfg = CHAT_MODELS[key];
        if (cfg.premium && window.__userRole !== 'premium' && window.__userRole !== 'admin') {
          toast(`${cfg.name} requires a Premium account`, 'warning');
          return;
        }
        chatState.selectedModel = key;
        const label = document.getElementById('model-selector-label');
        if (label) label.textContent = cfg.name;
        modelMenu.querySelectorAll('.model-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        modelMenu.classList.remove('open');
      });
    });
    // Lock premium models for non-premium users (Ultra + Deep Think)
    if (window.__userRole !== 'premium' && window.__userRole !== 'admin') {
      modelMenu.querySelectorAll('.model-option-premium').forEach(opt => opt.classList.add('locked'));
    }
  }

  // Welcome mode — center content until user sends first message
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.add('welcome-mode');

  // ── Static element bindings ────────────────────────────────────────────

  // Sidebar nav
  const sidebar = document.getElementById('sidebar-nav');
  if (sidebar) sidebar.classList.add('collapsed');
  document.body.classList.add('sidebar-collapsed');
  // On initial load, home is default, so sidebar starts hidden
  document.body.classList.add('sidebar-hidden');
  const hamburgerBtn = document.getElementById('hamburger-btn');
  if (hamburgerBtn) hamburgerBtn.addEventListener('click', () => {
    const sb = document.getElementById('sidebar-nav');
    const mn = document.querySelector('.main');
    if (sb) { sb.classList.remove('hidden', 'collapsed'); }
    document.body.classList.remove('sidebar-collapsed');
    document.body.classList.remove('sidebar-hidden');
    if (mn) mn.style.marginLeft = '';
    sidebarJustOpened = true;
    setTimeout(() => { sidebarJustOpened = false; }, 100);
  });

  // Click outside sidebar → hide it completely (premium UX)
  let sidebarJustOpened = false;
  const mainEl = document.querySelector('.main');
  if (mainEl) {
    mainEl.addEventListener('click', () => {
      if (sidebarJustOpened) { sidebarJustOpened = false; return; }
      const sb = document.getElementById('sidebar-nav');
      if (sb && !sb.classList.contains('hidden')) {
        sb.classList.add('hidden');
        document.body.classList.add('sidebar-hidden');
        if (mainEl) mainEl.style.marginLeft = '0';
        setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 150);
      }
    });
  }

  // Prevent sidebar clicks from collapsing
  const sidebarEl = document.getElementById('sidebar-nav');
  if (sidebarEl) {
    sidebarEl.addEventListener('click', (e) => e.stopPropagation());
  }

  // Tab buttons — double-click any tab to toggle sidebar
  let lastTabClickTime = 0;
  let lastTabClickTarget = null;
  document.querySelectorAll('.sidebar-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const now = Date.now();
      if (lastTabClickTarget === btn && now - lastTabClickTime < 400) {
        e.stopImmediatePropagation();
        toggleSidebarNav();
        lastTabClickTime = 0;
        lastTabClickTarget = null;
        return;
      }
      lastTabClickTime = now;
      lastTabClickTarget = btn;
      switchTab(btn.dataset.tab);
    });
  });

  // Logout button
  const logoutBtn = document.getElementById('user-logout');
  if (logoutBtn) logoutBtn.addEventListener('click', () => { if (typeof signOut === 'function') signOut(); });

  // DB tab
  const btnUploadPdf = document.getElementById('btn-upload-pdf');
  if (btnUploadPdf) btnUploadPdf.addEventListener('click', showUploadModal);
  const btnRefreshReports = document.getElementById('btn-refresh-reports');
  if (btnRefreshReports) btnRefreshReports.addEventListener('click', reloadReports);
  const fSearch = document.getElementById('f-search');
  if (fSearch) fSearch.addEventListener('input', dbFilter);
  const fCountry = document.getElementById('f-country');
  if (fCountry) fCountry.addEventListener('change', applyFilters);
  const fSource = document.getElementById('f-source');
  if (fSource) fSource.addEventListener('change', applyFilters);
  const fFrom = document.getElementById('f-from');
  if (fFrom) fFrom.addEventListener('change', applyFilters);
  const fTo = document.getElementById('f-to');
  if (fTo) fTo.addEventListener('change', applyFilters);

  // Table header sort
  document.querySelectorAll('.rtable thead th[data-sort]').forEach(th => {
    th.addEventListener('click', () => sortBy(th.dataset.sort));
  });

  // Chat sidebar
  const chatOverlay = document.getElementById('chat-sidebar-overlay');
  if (chatOverlay) chatOverlay.addEventListener('click', toggleChatSidebar);
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggleChatSidebar);
  // User photo click opens chat sidebar
  const userPhoto = document.getElementById('user-photo');
  if (userPhoto) userPhoto.addEventListener('click', toggleChatSidebar);
  const mobileUserPhoto = document.getElementById('mobile-user-photo');
  if (mobileUserPhoto) mobileUserPhoto.addEventListener('click', toggleChatSidebar);
  const chatNewBtn = document.getElementById('chat-new-btn');
  if (chatNewBtn) chatNewBtn.addEventListener('click', newChat);
  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  // Attach image for Vision model
  const attachBtn = document.getElementById('attach-btn');
  const attachInput = document.getElementById('attach-input');
  if (attachBtn && attachInput) {
    attachBtn.addEventListener('click', () => {
      if (chatState.selectedModel !== 'vision') {
        toast('Select the Vision model to attach an image (Premium)', 'warning');
        return;
      }
      attachInput.click();
    });
    attachInput.addEventListener('change', () => {
      const file = attachInput.files && attachInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        chatState.attachment = { name: file.name, mime: file.type || 'application/octet-stream', dataUrl: reader.result };
        toast(`📎 ${file.name} attached`, 'success', 3000);
      };
      reader.readAsDataURL(file);
      attachInput.value = '';
    });
  }

  // Mode selector
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const mode = btn.dataset.mode;
      chatState.mode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      if (mode === 'proposal' || mode === 'me_reviewer') {
        if (!chatState.proposalsLoaded) {
          await loadChatProposals();
        }
        showProposalPicker(mode);
      } else {
        hideProposalPicker();
        updateChatPlaceholder('Message Sightline...');
      }
    });
  });

  // DB modal
  const dbModal = document.getElementById('db-modal');
  if (dbModal) dbModal.addEventListener('click', e => { if (e.target === dbModal) closeDbModal(); });
  const dbModalCloseBtn = document.getElementById('db-modal-close-btn');
  if (dbModalCloseBtn) dbModalCloseBtn.addEventListener('click', closeDbModal);
  const btnAskAbout = document.getElementById('btn-ask-about');
  if (btnAskAbout) btnAskAbout.addEventListener('click', askAbout);

  // Upload modal
  const uploadModal = document.getElementById('upload-modal');
  if (uploadModal) uploadModal.addEventListener('click', e => { if (e.target === uploadModal) hideUploadModal(); });
  const uploadModalCloseBtn = document.getElementById('upload-modal-close-btn');
  if (uploadModalCloseBtn) uploadModalCloseBtn.addEventListener('click', hideUploadModal);
  const uploadForm = document.getElementById('upload-form');
  if (uploadForm) uploadForm.addEventListener('submit', e => { e.preventDefault(); submitUpload(e); });
  const btnClearUpload = document.getElementById('btn-clear-upload');
  if (btnClearUpload) btnClearUpload.addEventListener('click', clearUploadForm);

  // Agent keyboard
  chatInput.addEventListener('keydown', e => {
    // Block input when rate limit is exhausted
    const rl = window.__rateLimit;
    const role = window.__userRole || 'free';
    if (rl && rl.remaining <= 0 && role !== 'admin') {
      e.preventDefault();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  chatInput.addEventListener('input', () => {
    // Block input when rate limit is exhausted
    const rl = window.__rateLimit;
    const role = window.__userRole || 'free';
    if (rl && rl.remaining <= 0 && role !== 'admin') {
      chatInput.value = '';
      return;
    }
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 130) + 'px';
  });
  chatInput.focus();

  // SITREP event listeners
  const btnRun = document.getElementById('btn-run');
  if (btnRun) btnRun.addEventListener('click', runPipeline);

  ['inp-event', 'inp-themes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') runPipeline(); });
  });

  const countryEl = document.getElementById('inp-country');
  if (countryEl) {
    countryEl.addEventListener('change', () => fetchCountryDateRange(countryEl.value));
  }

  ['inp-date-from', 'inp-date-to', 'inp-themes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', scheduleChunkPreview);
    if (el && el.tagName === 'INPUT' && el.type !== 'date') el.addEventListener('input', scheduleChunkPreview);
  });

  const sitrepModalClose = document.getElementById('sitrep-modal-close-btn');
  if (sitrepModalClose) sitrepModalClose.addEventListener('click', closeSitrepModal);
  const sitrepModalOverlay = document.getElementById('sitrep-modal-overlay');
  if (sitrepModalOverlay) sitrepModalOverlay.addEventListener('click', e => {
    if (e.target === sitrepModalOverlay) closeSitrepModal();
  });

  // Global keyboard
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      closeDbModal();
      closeSitrepModal();
    }
  });

  // ── Event delegation for dynamic elements ──────────────────────────────
  document.addEventListener('click', e => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;

    switch (action) {
      case 'quick-prompt':
        sendQuickPrompt(target.dataset.text);
        break;
      case 'select-proposal':
        selectProposal(target.dataset.id);
        break;
      case 'delete-proposal':
        e.stopPropagation();
        deleteProposalItem(target.dataset.id);
        break;
      case 'open-rag-drawer':
        openRagDrawer(parseInt(target.dataset.index));
        break;
      case 'edit-toc-node':
        editTocNode(parseInt(target.dataset.index));
        break;
      case 'open-smart-scorecard':
        openSmartScorecard(target.dataset.level, target);
        break;
      case 'open-chat-history':
        toggleChatSidebar();
        break;
      case 'rename-chat':
        e.stopPropagation();
        renameChat(target.dataset.chatId, target);
        break;
      case 'delete-chat':
        e.stopPropagation();
        confirmDeleteChat(target.dataset.chatId, target);
        break;
      case 'confirm-delete-chat':
        e.stopPropagation();
        executeDeleteChat(target.dataset.chatId, target);
        break;
      case 'cancel-delete-chat':
        e.stopPropagation();
        target.closest('.delete-confirm')?.remove();
        break;
      case 'create-new-proposal':
        switchTab('proposal');
        break;
      case 'generate-toc':
        generateSection('toc');
        break;
      case 'generate-logframe':
        generateSection('logframe');
        break;
      case 'generate-narrative':
        generateSection('final_review');
        break;
      case 'generate-section':
        generateSection(target.dataset.step);
        break;
      case 'save-section':
        saveSectionManual(target.dataset.step);
        break;
      case 'approve-section':
        approveSection(target.dataset.step);
        break;
      case 'skip-section':
        skipSection(target.dataset.step);
        break;
      case 'wizard-select-step':
        wizardSelectStep(target.dataset.step);
        break;
      case 'proposal-view-mode':
        window.toggleProposalViewMode(target.dataset.step, target.dataset.mode);
        break;
      case 'open-diff-modal':
        openDiffModal();
        break;
      case 'discuss-sitrep':
        discussSitrepWithAgent();
        break;
      case 'proposal-from-sitrep':
        createProposalFromSitrep(target.dataset);
        break;
      case 'go-chat':
        switchTab('agent');
        break;
      case 'go-sitrep':
        switchTab('sitrep');
        break;
      case 'go-db':
        switchTab('db');
        break;
      case 'cc-start-sitrep':
        ccStartSitrep();
        break;
      case 'cc-start-proposal':
        ccStartProposal();
        break;
      case 'cc-start-bulletin':
        ccStartBulletin();
        break;
      case 'cc-open-crisis-map':
        switchTab('crisis-map');
        break;
      case 'cc-open-db':
        switchTab('db');
        break;
      case 'cc-open-agent':
        switchTab('agent');
        break;
      case 'cc-open-proposal':
        selectProposal(target.dataset.id);
        switchTab('proposal');
        break;
      case 'cc-open-sitrep': {
        const file = target.dataset.file;
        switchTab('sitrep');
        setTimeout(() => {
          const itemEl = document.querySelector(`#sitrep-reports-list .report-item[data-file="${file}"]`);
          if (itemEl) {
            itemEl.click();
          } else {
            openSitrepReport(file);
          }
        }, 150);
        break;
      }
      case 'cc-open-bulletin': {
        const bFile = target.dataset.file;
        switchTab('bulletin');
        setTimeout(() => {
          const itemEl = document.querySelector(`#bulletin-tabs .bulletin-tab-pill[data-filename="${bFile}"]`);
          if (itemEl) {
            itemEl.click();
          } else {
            openBulletin(bFile);
          }
        }, 150);
        break;
      }
      case 'toggle-cc-acc': {
        const targetId = target.dataset.target;
        const targetCard = document.getElementById(targetId);
        if (targetCard) {
          const isOpen = targetCard.classList.contains('open');
          document.querySelectorAll('.cc-acc-card').forEach(card => card.classList.remove('open'));
          if (!isOpen) {
            targetCard.classList.add('open');
          }
        }
        break;
      }
      case 'go-sitrep-country':
        switchTab('sitrep');
        setTimeout(() => {
          const sel = document.getElementById('inp-country');
          if (sel) { sel.value = target.dataset.country || ''; }
        }, 100);
        break;
      case 'go-bulletin':
        switchTab('bulletin');
        break;
      case 'dash-view-crisis': {
        const crisisCountry = target.dataset.country;
        if (crisisCountry) {
          closeCrisisPanel();
          switchTab('sitrep');
          setTimeout(() => {
            const sel = document.getElementById('inp-country');
            if (sel) sel.value = crisisCountry;
          }, 100);
        }
        break;
      }
      case 'switch-report-view':
        switchReportView(target.dataset.mode);
        break;
      case 'view-recent-report': {
        const rid = parseInt(target.dataset.reportId, 10);
        if (rid) openDbReport(rid);
        break;
      }
      case 'toggle-card':
        toggleCard(target);
        break;
      case 'show-citation':
        showCitationFromEl(target);
        break;
      case 'tag-add':
        tagAdd(target.dataset.field);
        break;
      case 'tag-remove':
        tagRemove(target.dataset.field, parseInt(target.dataset.idx, 10));
        break;
      case 'set-role':
        setUserRole(target.dataset.uid, target.dataset.role);
        break;
      case 'generate-bulletin':
        generateBulletin();
        break;
      case 'open-bulletin':
        // Highlight active tab-pill
        document.querySelectorAll('.bulletin-tab-pill').forEach(p => p.classList.remove('active'));
        target.classList.add('active');
        openBulletin(target.dataset.filename);
        break;
      case 'view-bulletin-sitrep':
        closeCrisisPanel();
        viewBulletinSitrep(target.dataset.country);
        break;
      case 'open-sitrep-report':
        openSitrepReport(target.dataset.file, target);
        break;
      case 'delete-sitrep-report':
        event.stopPropagation();
        deleteSitrepReport(target.dataset.file, target.closest('.report-item'));
        break;
      case 'toggle-model-menu':
        // Handled by direct event listener above
        break;
    }
  });

  // Admin sub-tab switching (Users / Analytics)
  document.querySelectorAll('.admin-subtab').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.adminTab;
      document.querySelectorAll('.admin-subtab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const usersSec = document.getElementById('admin-users');
      const analyticsSec = document.getElementById('admin-analytics');
      if (tab === 'analytics') {
        if (usersSec) usersSec.style.display = 'none';
        if (analyticsSec) analyticsSec.style.display = '';
        loadAnalytics();
      } else {
        if (analyticsSec) analyticsSec.style.display = 'none';
        if (usersSec) usersSec.style.display = '';
      }
    });
  });

  // DB report row click delegation
  document.getElementById('rtbody')?.addEventListener('click', e => {
    const row = e.target.closest('.db-report-row');
    if (row && row.dataset.reportId) openDbReport(parseInt(row.dataset.reportId, 10));
  });

  // Chat list click delegation (for rename/delete buttons that stop propagation)
  document.getElementById('chat-list')?.addEventListener('click', e => {
    const actionEl = e.target.closest('[data-action]');
    if (actionEl) return; // handled by global delegation
  });

  // Init SITREP steps grid
  buildStepsGrid();
  sitrepState.stepStates = new Array(STEPS.length).fill('waiting');
  showSitrepView('welcome');

  // SITREP tag input: Enter key support
  ['country', 'theme'].forEach(field => {
    const inp = document.getElementById(`up-${field}-input`);
    if (!inp) return;
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); tagAdd(field); }
    });
  });

  // Wait for auth before making auth-required API calls
  let _appInited = false;
  let _previewInited = false;

  function initPreviewData() {
    // Login required but app visible behind overlay
    if (_previewInited) return;
    _previewInited = true;
    console.warn('[app] initPreviewData — showing app with login overlay');
    // Load Command Center (visible behind login panel)
    switchTab('home');
    loadCommandCenter();
  }

  function initAppData() {
    if (_appInited) return;
    _appInited = true;
    const tok = window.getIdToken ? window.getIdToken() : '';
    if (!tok) return;
    switchTab('home');
    loadChatList();
    updateVisibilityFromAuth();
  }

  function updateVisibilityFromAuth() {
    if (typeof window.updateVisibility === 'function') {
      window.updateVisibility();
    } else {
      const role = window.__userRole || 'free';
      const isPremium = role === 'premium' || role === 'admin';
      const sitrepFormBar = document.getElementById('sitrep-form-bar');
      if (sitrepFormBar) sitrepFormBar.style.display = isPremium ? '' : 'none';
    }
    updateUploadBtnVisibility();
  }

  // Preview mode: load public data immediately (no auth needed)
  if (window.__authReady) {
    initAppData();
  } else {
    // Listen for preview-ready (anonymous visitor — show limited content)
    window.addEventListener('preview-ready', () => {
      console.warn('[app] preview-ready event — forcing login');
      initPreviewData();
    }, { once: true });
    // Listen for auth-ready (user signed in — load full app)
    window.addEventListener('auth-ready', () => {
      console.warn('[app] auth-ready event — loading full app after sign-in');
      _previewInited = true; // prevent double-load
      // Reset dashboard loaded flag so it reloads with authed endpoints
      dashboardLoaded = false;
      initAppData();
      // Reload dashboard now that we have a token — force reload
      setTimeout(() => {
        dashboardLoaded = false;
        loadDashboard();
        // Also load chat list and other authed data
        loadChatList();
      }, 100);
    }, { once: true });
    setTimeout(() => {
      if (!_appInited && window.getIdToken && window.getIdToken()) {
        console.warn('[app] auth-ready event missed, initializing with cached token');
        initAppData();
      }
    }, 3000);
  }
});
