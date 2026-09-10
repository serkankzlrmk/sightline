// ═══════════════════════════════════════════════════════════════
// dashboard.js — Crisis map data and shared display labels
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// CRISIS MAP STATE
// ═══════════════════════════════════════════════════════════════════════════

let dashboardLoaded = false;
let dashboardLoading = false;

// ═══════════════════════════════════════════════════════════════════════════
// CRISIS MAP DATA (loaded from /api/map/countries — single endpoint)
// ═══════════════════════════════════════════════════════════════════════════

let mapCountries = {};   // { country_name: { ...all data } }
let mapDataLoaded = false;
let crisisMapData = {};
let leafletMap = null;
let leafletMarkers = [];
let leafletResizeObserver = null;
let leafletResizeFrame = 0;

function humanizeWeekLabel(label) {
  if (!label) return label;
  const isoMatch = label.match(/^(\d{4})-(\d{2})-(\d{2})\s+to\s+(\d{4})-(\d{2})-(\d{2})/);
  if (!isoMatch) return label;
  const [_, ys, ms, ds, ye, me, de] = isoMatch.map(Number);
  const sd = new Date(ys, ms - 1, ds);
  const ed = new Date(ye, me - 1, de);
  const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const ordinals = ['First', 'Second', 'Third', 'Fourth', 'Fifth'];
  if (sd.getMonth() === ed.getMonth() && sd.getFullYear() === ed.getFullYear()) {
    const weekOfMonth = Math.floor((ds - 1) / 7);
    return `${ordinals[Math.min(weekOfMonth, 4)]} week of ${monthNames[sd.getMonth()]} ${sd.getFullYear()}`;
  }
  return `${sd.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${ed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

async function loadDashboard() {
  if (dashboardLoaded) {
    if (currentTab === 'crisis-map') initWorldMap();
    return;
  }
  if (dashboardLoading) return;
  dashboardLoading = true;

  // Freemium preview: check if user is authenticated
  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;

  // ── Load map data: single endpoint for all 60 countries ──
  try {
    const r = await api('/api/map/countries');
    if (r.ok) {
      const countries = await r.json();
      if (Array.isArray(countries)) {
        countries.forEach(c => {
          if (c.country) {
            mapCountries[c.country] = c;
            // Also populate legacy crisisMapData for marker rendering
            crisisMapData[c.country] = {
              country: c.country,
              headline: c.headline || '',
              summary: c.narrative || '',
              severity: c.severity || 'low',
              report_count: c.report_count || 0,
              coords: c.coords || { lat: 0, lng: 0 },
              has_sitrep: c.has_sitrep || false,
              iso3: c.iso3 || '',
              last_updated: c.last_updated || '',
              recent_reports: c.recent_reports || [],
              top_themes: c.top_themes || [],
              top_sources: c.top_sources || [],
              hdx_key_figures: c.hdx_key_figures || [],
              gdacs_alerts: c.gdacs_alerts || [],
              hdx_fetched_at: c.hdx_fetched_at || 0,
              gdacs_fetched_at: c.gdacs_fetched_at || 0,
              worldbank_fetched_at: c.worldbank_fetched_at || 0,
              has_summary: c.has_summary || false,
              date_range: c.date_range || {},
            };
          }
        });
        mapDataLoaded = true;
      }
    }
  } catch (e) { console.warn('[dashboard] map/countries load failed:', e); }

  // Render new markers immediately when the visible map receives its data.
  if (currentTab === 'crisis-map') initWorldMap();

  // ── Load basic stats ──
  try {
    const statsUrl = isAuthed ? '/api/db/stats' : '/api/public/stats';
    const r = await api(statsUrl);
    const d = await r.json();
    const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    el('dash-reports', d.report_count != null ? d.report_count.toLocaleString() : '—');
    el('dash-chunks', d.chunk_count != null ? d.chunk_count.toLocaleString() : '—');
    el('cc-stat-chunks', d.chunk_count != null ? d.chunk_count.toLocaleString() : '24,955');
    if (Array.isArray(mapCountries) && mapCountries.length > 0) {
      el('cc-stat-countries', mapCountries.length.toString());
    }
  } catch { /* ignore */ }

  // A failed map request must remain retryable on the next Map visit.
  dashboardLoaded = mapDataLoaded;
  dashboardLoading = false;
  if (currentTab === 'crisis-map') {
    initWorldMap();
    const pendingCountry = window.__pendingMapCountry || '';
    if (pendingCountry && typeof window.focusMapCountry === 'function' && window.focusMapCountry(pendingCountry)) {
      window.__pendingMapCountry = '';
    }
  }
}
