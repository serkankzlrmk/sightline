// ═══════════════════════════════════════════════════════════════
// dashboard.js — Home Dashboard (stats, command center) — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// HOME DASHBOARD
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

// ═══════════════════════════════════════════════════════════════════════════
// COMMAND CENTER (Home tab)
// ═══════════════════════════════════════════════════════════════════════════

async function loadCommandCenter() {
  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;

  // Auth CTA
  const authCta = document.getElementById('cc-auth-cta');
  if (authCta) authCta.style.display = isAuthed ? 'none' : 'block';

  // 1. Fetch and render existing SITREPs
  try {
    const res = await api('/api/public/sitrep/reports');
    const sitreps = await res.json();
    const container = document.getElementById('cc-recent-sitreps');
    if (container && Array.isArray(sitreps)) {
      if (sitreps.length > 0) {
        container.innerHTML = sitreps.slice(0, 5).map(item => {
          const country = item.filename.split('_')[0].replace(/\(/g, ' ').replace(/\)/g, '').trim();
          return `<div class="cc-recent-item" data-action="cc-open-sitrep" data-file="${esc(item.filename)}" style="font-size:13px; padding:6px 0; cursor:pointer; color:var(--primary); font-weight:500;">
            <span style="display:inline-flex; align-items:center; gap:6px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              ${escHtml(country)}
            </span>
          </div>`;
        }).join('');
      } else {
        container.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">No reports yet</div>';
      }
    }
  } catch {
    const container = document.getElementById('cc-recent-sitreps');
    if (container) container.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">Failed to load</div>';
  }

  // 2. Recent proposals (modül yeniden tasarlanıyor — placeholder)
  const proposalsContainer = document.getElementById('cc-recent-proposals');
  if (proposalsContainer) {
    proposalsContainer.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">🚧 Coming soon — being redesigned</div>';
  }

  // 3. Bulletins list
  try {
    const res = await api('/api/public/bulletins');
    const data = await res.json();
    const bulletins = data.bulletins || data || [];
    const container = document.getElementById('cc-recent-bulletins');
    if (container && Array.isArray(bulletins)) {
      if (bulletins.length > 0) {
        container.innerHTML = bulletins.slice(0, 5).map(b =>
          `<div class="cc-recent-item" data-action="cc-open-bulletin" data-file="${esc(b.filename)}" style="font-size:13px; padding:6px 0; cursor:pointer; color:var(--primary); font-weight:500;">
            <span style="display:inline-flex; align-items:center; gap:6px;">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><path d="M16 8h2m-6 4h6m-6 4h6M6 8h4v8H6z"/></svg>
              ${escHtml(humanizeWeekLabel(b.week_label))}
            </span>
          </div>`
        ).join('');
      } else {
        container.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">No bulletins yet</div>';
      }
    }
  } catch {
    const container = document.getElementById('cc-recent-bulletins');
    if (container) container.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">Failed to load</div>';
  }
}

function ccStartSitrep() {
  const role = window.__userRole || 'free';
  const tok = window.getIdToken ? window.getIdToken() : '';
  // SITREP reports are PUBLIC (anonymous can read them — the generation
  // form is hidden in switchTab). Only the generation flow is premium.
  switchTab('sitrep');
  if (!tok || role === 'free') return;
  const sel = document.getElementById('cc-sitrep-country');
  const country = sel ? sel.value : '';
  if (country) {
    setTimeout(() => {
      const inp = document.getElementById('inp-country');
      if (inp) inp.value = country;
    }, 200);
  }
}

function ccStartBulletin() {
  switchTab('bulletin');
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
  if (currentTab === 'crisis-map') initWorldMap();
}

