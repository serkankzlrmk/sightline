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

function focusMapCountry(country) {
  if (!country || !leafletMap) return false;
  const normalized = country.trim().toLowerCase();
  const match = Object.values(crisisMapData).find(item =>
    String(item?.country || '').trim().toLowerCase() === normalized
  );
  if (!match) return false;
  const lat = Number(match.coords?.lat);
  const lng = Number(match.coords?.lng);
  if (!lat || !lng) return false;
  leafletMap.setView([lat, lng], 5);
  openCountryCard(match);
  return true;
}

window.focusMapCountry = focusMapCountry;

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
