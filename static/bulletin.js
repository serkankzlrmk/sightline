// ═══════════════════════════════════════════════════════════════
// bulletin.js — Weekly Bulletin UI — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// WEEKLY BULLETIN
// ═══════════════════════════════════════════════════════════════════════════

async function loadBulletinList() {
  const container = document.getElementById('bulletin-tabs');
  if (!container) return;
  container.innerHTML = '<div class="bulletin-tab-loading">Loading…</div>';
  try {
    const resp = await api('/api/sitrep/bulletins');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const bulletins = await resp.json();
    if (!bulletins.length) {
      container.innerHTML = `
        <div class="bulletin-tab-empty">
          No bulletins yet
          <button class="bulletin-gen-btn bulletin-gen-inline" data-action="generate-bulletin">Generate Weekly Bulletin</button>
        </div>`;
      return;
    }
    container.innerHTML = bulletins.map((b, i) => {
      const fallbackTag = b.data_date_range?.fallback
        ? ' <span class="severity-warn-icon" style="display:inline-flex;align-items:center;vertical-align:middle;margin-left:4px;color:var(--amber-dark)"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>'
        : '';
      return `<button class="bulletin-tab-pill${i === 0 ? ' active' : ''}" data-action="open-bulletin" data-filename="${esc(b.filename)}">${esc(humanizeWeekLabel(b.week_label))}${fallbackTag}</button>`;
    }).join('');
    // Auto-select first bulletin
    const firstBtn = container.querySelector('.bulletin-tab-pill.active');
    if (firstBtn) firstBtn.click();
  } catch (e) {
    console.error('[bulletin] loadBulletinList error:', e);
    container.innerHTML = '<div class="bulletin-tab-empty">Failed to load</div>';
  }
}

async function generateBulletin() {
  const btn = document.querySelector('.bulletin-gen-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
  try {
    const resp = await api('/api/sitrep/bulletin/generate', { method: 'POST' });
    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.error || `HTTP ${resp.status}`);
    }
    const result = await resp.json();
    if (result.job_id) {
      // Async generation — poll for status
      if (btn) { btn.textContent = 'Generating…'; }
      const filename = await pollBulletinJob(result.job_id);
      toast('Bulletin generated!', 'success');
      loadBulletinList();
      if (filename) openBulletin(filename);
    } else if (result.filename) {
      // Sync fallback (shouldn't happen but just in case)
      toast('Bulletin generated!', 'success');
      loadBulletinList();
      openBulletin(result.filename);
    }
  } catch (e) {
    console.error('[bulletin] generateBulletin error:', e);
    toast('Failed to generate bulletin: ' + (e.message || 'Unknown error'), 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Generate Weekly Bulletin'; }
  }
}

async function pollBulletinJob(jobId) {
  const maxAttempts = 120; // 120 × 2s = 4 min max
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const resp = await api(`/api/sitrep/bulletin/generate/status/${jobId}`);
      if (!resp.ok) {
        if (resp.status === 404) throw new Error('Job not found');
        continue; // Network error — keep polling
      }
      const status = await resp.json();
      if (status.status === 'done') {
        return status.result?.filename || null;
      }
      if (status.status === 'error') {
        throw new Error(status.error || 'Generation failed');
      }
      // Still running — update button text
      const btn = document.querySelector('.bulletin-gen-btn');
      if (btn) { btn.textContent = `Generating… (${i * 2 + 2}s)`; }
    } catch (e) {
      if (e.message?.includes('Generation failed') || e.message?.includes('Job not found')) throw e;
      // Network error — keep polling
    }
  }
  throw new Error('Bulletin generation timed out');
}

async function openBulletin(filename) {
  const content = document.getElementById('bulletin-content');
  if (!content) return;
  content.innerHTML = '<div class="bulletin-loading">Loading bulletin…</div>';
  try {
    const resp = await api(`/api/sitrep/bulletin/${filename}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const b = await resp.json();
    renderBulletin(b, content);
  } catch (e) {
    console.error('[bulletin] openBulletin error:', e);
    content.innerHTML = '<div class="bulletin-error">Failed to load bulletin</div>';
  }
}

function renderBulletin(b, container) {
  const severityOrder = { high: 0, medium: 1, low: 2 };
  const allCrises = (b.crises || []).sort((a, c) =>
    (severityOrder[a.severity] ?? 3) - (severityOrder[c.severity] ?? 3)
  );

  const severityBadge = (s) => {
    const labels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
    return `<span class="severity-badge severity-${s}">${labels[s] || s.toUpperCase()}</span>`;
  };

  const keyFigures = (b.key_figures || []).map(f => `
    <div class="bulletin-kf-card">
      <div class="bulletin-kf-value">${esc(f.value)}</div>
      <div class="bulletin-kf-label">${esc(f.label)}</div>
    </div>
  `).join('');

  const buildCrisisCards = (crises) => crises.map(c => {
    return `
    <div class="crisis-card crisis-${c.severity}" data-severity="${c.severity}">
      <div class="crisis-card-header">
        <div class="crisis-card-country">${esc(c.country)}</div>
        ${severityBadge(c.severity)}
      </div>
      ${c.headline ? `<div class="crisis-card-headline">${esc(c.headline)}</div>` : ''}
      ${c.summary ? `<div class="crisis-card-summary">${esc(c.summary)}</div>` : ''}
      ${c.has_sitrep ? `<button class="crisis-sitrep-btn" data-action="view-bulletin-sitrep" data-country="${esc(c.country)}">View SITREP →</button>` : ''}
    </div>
  `;
  }).join('');

  const counts = { high: 0, medium: 0, low: 0 };
  allCrises.forEach(c => { if (counts[c.severity] !== undefined) counts[c.severity]++; });

  // Show fallback notice if data date range differs from requested range
  const fallbackNotice = b.data_date_range?.fallback
    ? `<div class="bulletin-fallback-notice">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right:2px;flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <span>No data available for ${b.data_date_range.requested_from} to ${b.data_date_range.requested_to}. Showing data from ${b.data_date_range.actual_from} to ${b.data_date_range.actual_to} instead.</span>
      </div>`
    : '';

  container.innerHTML = `
    <div class="bulletin-header">
      <div class="bulletin-title-row">
        <h2 class="bulletin-title">${esc(humanizeWeekLabel(b.week_label))}</h2>
      </div>
      ${fallbackNotice}
      <div class="bulletin-kf-row">${keyFigures}</div>
    </div>

    <div class="bulletin-overview">
      <h3>Global Overview</h3>
      <div class="bulletin-overview-text">${typeof marked !== 'undefined' ? sanitizeHtml(marked.parse(b.global_overview || '')) : esc(b.global_overview || '')}</div>
    </div>

    <div class="bulletin-crises">
      <div class="bulletin-crises-head">
        <h3>Active Crises</h3>
        <div class="severity-filter" id="severity-filter">
          <button class="severity-pill active" data-sev="all">All ${allCrises.length}</button>
          <button class="severity-pill" data-sev="high">High ${counts.high}</button>
          <button class="severity-pill" data-sev="medium">Medium ${counts.medium}</button>
          <button class="severity-pill" data-sev="low">Low ${counts.low}</button>
        </div>
      </div>
      <div class="crisis-grid" id="crisis-grid">${buildCrisisCards(allCrises)}</div>
    </div>
  `;

  const filterBtns = container.querySelectorAll('#severity-filter .severity-pill');
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const sev = btn.dataset.sev;
      container.querySelectorAll('.crisis-card').forEach(card => {
        if (sev === 'all' || card.dataset.severity === sev) {
          card.style.display = '';
        } else {
          card.style.display = 'none';
        }
      });
    });
  });
}

function viewBulletinSitrep(country) {
  // Find the SITREP report for this country in the sidebar list
  const items = document.querySelectorAll('#sitrep-reports-list .report-item');
  for (const item of items) {
    if (item.textContent.toLowerCase().includes(country.toLowerCase())) {
      item.click();
      return;
    }
  }
  // If not found, switch to SITREP and show a message
  alert(`No SITREP report found for ${country}. You can generate one using the SITREP pipeline.`);
}
