// ═══════════════════════════════════════════════════════════════
// database.js — TAB 1: Database Reports Browser — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// TAB 1 — DATABASE (DB Reports Browser)
// ═══════════════════════════════════════════════════════════════════════════

async function reloadReports() {
  const role = window.__userRole || 'free';
  const isPremium = role === 'premium' || role === 'admin';
  const banner = document.getElementById('db-premium-banner');
  const recentList = document.getElementById('db-recent-list');
  const fullAccess = document.getElementById('db-full-access');

  if (isPremium) {
    if (banner) banner.style.display = 'none';
    if (recentList) recentList.style.display = 'none';
    if (fullAccess) fullAccess.classList.remove('hidden');
    await Promise.all([loadStats(), loadFilterOptions()]);
    await applyFilters();
  } else {
    if (banner) banner.style.display = 'flex';
    if (recentList) recentList.style.display = 'block';
    if (fullAccess) fullAccess.classList.add('hidden');
    await loadStats();
    await loadRecentReports();
  }
}

async function loadStats() {
  try {
    const r = await api('/api/db/stats');
    const d = await r.json();
    document.getElementById('s-reports').textContent = (d.report_count || 0).toLocaleString();
    document.getElementById('s-chunks').textContent = (d.chunk_count || 0).toLocaleString();
  } catch { /* ignore */ }
}

async function loadRecentReports() {
  const container = document.getElementById('db-recent-items');
  if (!container) return;
  try {
    const r = await api('/api/db/reports?sort=date&order=desc&limit=10');
    const data = await r.json();
    const reports = data.reports || data;
    if (!reports.length) {
      container.innerHTML = '<div class="msg-muted" style="padding:16px">No recent reports found.</div>';
      return;
    }
    container.innerHTML = reports.slice(0, 10).map(rep => {
      const date = rep.date || '—';
      const country = rep.primary_country || '—';
      const title = rep.title || 'Untitled';
      const url = rep.url || '';
      const urlAttr = url ? `data-url="${escHtml(url)}"` : '';
      return `<div class="db-recent-item" data-report-id="${rep.report_id}" ${urlAttr} data-action="view-recent-report" style="cursor:pointer">
        <span class="db-recent-date">${escHtml(date)}</span>
        <span class="db-recent-country">${escHtml(country)}</span>
        <span class="db-recent-title">${escHtml(title)}</span>
        <svg class="db-recent-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
      </div>`;
    }).join('');
  } catch {
    container.innerHTML = '<div class="msg-muted" style="padding:16px">Could not load reports.</div>';
  }
}

async function loadFilterOptions() {
  try {
    const [cRes, sRes] = await Promise.all([api('/api/db/countries'), api('/api/db/sources')]);
    const countries = await cRes.json();
    const sources = await sRes.json();

    const cSel = document.getElementById('f-country');
    const prevC = cSel.value;
    cSel.innerHTML = '<option value="">All Countries</option>';
    countries.forEach(c => {
      const o = new Option(c, c);
      if (c === prevC) o.selected = true;
      cSel.appendChild(o);
    });

    const sSel = document.getElementById('f-source');
    const prevS = sSel.value;
    sSel.innerHTML = '<option value="">All Sources</option>';
    sources.forEach(s => {
      const o = new Option(s, s);
      if (s === prevS) o.selected = true;
      sSel.appendChild(o);
    });
  } catch { /* ignore */ }
}

async function applyFilters() {
  const search = document.getElementById('f-search').value.trim();
  const country = document.getElementById('f-country').value;
  const source = document.getElementById('f-source').value;
  const from = document.getElementById('f-from').value;
  const to = document.getElementById('f-to').value;

  const p = new URLSearchParams();
  if (search) p.set('search', search);
  if (source) p.set('source', source);
  if (from) p.set('date_from', from);
  if (to) p.set('date_to', to);

  try {
    const res = await api('/api/db/reports?' + p);
    let data = await res.json();
    if (country) {
      data = data.filter(r => (r.all_countries || []).includes(country));
    }
    dbState.allReports = data;
  } catch {
    dbState.allReports = [];
  }
  renderTable();
}

function dbFilter() {
  clearTimeout(dbState.filterTimer);
  dbState.filterTimer = setTimeout(applyFilters, 280);
}

function sortBy(key) {
  if (dbState.sortKey === key) dbState.sortAsc = !dbState.sortAsc;
  else { dbState.sortKey = key; dbState.sortAsc = true; }

  document.querySelectorAll('.rtable thead th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === key);
  });
  renderTable();
}

function renderTable() {
  const body = document.getElementById('rtbody');
  const data = [...dbState.allReports].sort((a, b) => {
    const va = String(a[dbState.sortKey] ?? '');
    const vb = String(b[dbState.sortKey] ?? '');
    if (va < vb) return dbState.sortAsc ? -1 : 1;
    if (va > vb) return dbState.sortAsc ? 1 : -1;
    return 0;
  });

  document.getElementById('f-count').textContent = data.length + ' reports';

  if (!data.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty"><div class="icon"></div>No results found</td></tr>';
    return;
  }

  body.innerHTML = data.map((r, index) => {
    const fmtBadge = r.format_type
      ? `<span class="badge b-blue">${esc(r.format_type.replace('Situation Report', 'Sit.Rep').replace('News and Press Release', 'News'))}</span>`
      : '';
    const pdfBadge = r.has_pdf
      ? '<span class="badge b-green">PDF</span>'
      : '<span class="badge b-gray">—</span>';

    return `<tr class="db-report-row animate-fade-in-up" data-report-id="${r.report_id}" style="animation-delay: ${index * 15}ms;">
      <td class="id-cell">${r.report_id}</td>
      <td class="no-nowrap">${r.date || ''}</td>
      <td>${esc(r.primary_country || '')}</td>
      <td><span class="badge b-yellow">${esc(r.source || '')}</span></td>
      <td class="title-cell" title="${esc(r.title || '')}">${esc(r.title || '')}</td>
      <td>${fmtBadge}</td>
      <td>${pdfBadge}</td>
      <td class="chunks-cell">${r.total_chunks || 0}</td>
    </tr>`;
  }).join('');
}

async function openDbReport(id) {
  dbState.currentReportId = id;
  try {
    const res = await api('/api/db/reports/' + id);
    const r = await res.json();
    dbState.currentReportTitle = r.title || '';

    document.getElementById('m-title').textContent = r.title || '—';
    document.getElementById('m-id').textContent = r.report_id;
    document.getElementById('m-date').textContent = r.date || '—';
    document.getElementById('m-countries').textContent = (r.all_countries || []).join(', ') || '—';
    document.getElementById('m-source').textContent = r.source || '—';
    document.getElementById('m-format').textContent = r.format_type || '—';
    document.getElementById('m-pdf').textContent = r.has_pdf ? `Available (${r.pdf_pages} pages)` : 'None';
    document.getElementById('m-chunks').textContent = r.has_content ? `Available (${r.total_chunks} chunks)` : 'None';

    let themes = r.themes_list || [];
    if (!themes.length) { try { themes = JSON.parse(r.themes || '[]'); } catch { } }
    document.getElementById('m-themes').textContent = themes.join(', ') || '—';
    document.getElementById('m-link').href = r.url || '#';

    const chunks = r.chunks_preview || [];
    document.getElementById('m-preview').textContent =
      chunks.length ? (chunks[0].content || '').slice(0, 900) : '(No content available)';

    document.getElementById('db-modal').classList.add('open');
  } catch (err) {
    alert('Could not load report: ' + err.message);
  }
}

function closeDbModal() {
  document.getElementById('db-modal').classList.remove('open');
}

function askAbout() {
  closeDbModal();
  switchTab('agent');
  chatInput.value = `Tell me about the report "${dbState.currentReportTitle}" (ID: ${dbState.currentReportId}). What are the key findings and summary?`;
  chatInput.focus();
  chatInput.dispatchEvent(new Event('input'));
}

