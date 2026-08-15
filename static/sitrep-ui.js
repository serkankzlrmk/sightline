// ═══════════════════════════════════════════════════════════════
// sitrep-ui.js — TAB 3: SITREP Pipeline UI — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// TAB 3 — SITREP PIPELINE
// ═══════════════════════════════════════════════════════════════════════════

const STEPS = [
  { id: 0, name: "Chroma Connection", icon: "1" },
  { id: 1, name: "Chunk Loading", icon: "2" },
  { id: 2, name: "Clustering", icon: "3" },
  { id: 3, name: "Question Generation", icon: "4" },
  { id: 4, name: "Question Filtering", icon: "5" },
  { id: 5, name: "RAG Answering", icon: "6" },
  { id: 6, name: "Citation Validation", icon: "7" },
  { id: 7, name: "Cluster Summary", icon: "8" },
  { id: 8, name: "Exec + Narrative", icon: "9" },
  { id: 9, name: "Report Assembly", icon: "10" },
];

const STEP_RE = /\[INFO\]\s+pipeline:\s+\[(\d)\]/;
const CACHE_RE = /\[CHECKPOINT\]/;

function buildStepsGrid() {
  const grid = document.getElementById('steps-grid');
  if (!grid) return;
  grid.innerHTML = '';
  STEPS.forEach((s) => {
    const div = document.createElement('div');
    div.className = 'step-card waiting';
    div.id = `step-card-${s.id}`;
    div.innerHTML = `
      <div class="step-num">STEP ${s.id}</div>
      <div class="step-name">${s.name}</div>
      <div class="step-icon">${s.icon}</div>`;
    grid.appendChild(div);
  });
}

function setSitrepStepState(idx, state) {
  if (idx < 0 || idx >= STEPS.length) return;
  sitrepState.stepStates[idx] = state;
  const card = document.getElementById(`step-card-${idx}`);
  if (!card) return;
  card.className = `step-card ${state}`;
  const iconMap = { waiting: STEPS[idx].icon, active: '○', cached: '⚡', done: '✓', error: '✗' };
  card.querySelector('.step-icon').textContent = iconMap[state] || STEPS[idx].icon;
}

function advanceToStep(n) {
  if (n <= sitrepState.currentStep) return;
  if (sitrepState.currentStep >= 0) setSitrepStepState(sitrepState.currentStep, 'done');
  sitrepState.currentStep = n;
  setSitrepStepState(n, 'active');
}

function logClass(line) {
  if (/^\[GPU_WARN\]/i.test(line)) return 'gpu-warn';
  if (STEP_RE.test(line)) return 'step';
  if (/completed successfully|pipeline.*done/i.test(line)) return 'done-line';
  if (CACHE_RE.test(line)) return 'cached';
  if (/\[warning\]/i.test(line)) return 'warn';
  if (/\[error\]/i.test(line) || /traceback/i.test(line)) return 'error';
  if (/\[info\]/i.test(line)) return 'info';
  return 'debug';
}

function appendLog(line) {
  const cons = document.getElementById('log-console');
  if (!cons) return;
  const div = document.createElement('div');
  div.className = `log-line ${logClass(line)}`;
  div.textContent = line;
  cons.appendChild(div);
  cons.scrollTop = cons.scrollHeight;

  const m = line.match(STEP_RE);
  if (m) {
    const n = parseInt(m[1]);
    if (CACHE_RE.test(line)) {
      setSitrepStepState(n, 'cached');
      sitrepState.currentStep = n;
    } else {
      advanceToStep(n);
    }
  }
  if (CACHE_RE.test(line) && !m && sitrepState.currentStep >= 0) {
    setSitrepStepState(sitrepState.currentStep, 'cached');
  }
}

function connectSSE(jobId, nonce) {
  sitrepState.activeJobId = jobId;
  const es = new EventSource(`/api/sitrep/stream/${jobId}?nonce=${encodeURIComponent(nonce || '')}`);
  const dot = document.getElementById('log-dot');

  es.onmessage = (e) => {
    const data = e.data;
    if (data === '__PING__') return;
    if (data.startsWith('__DONE__')) {
      const status = data.replace('__DONE__', '');
      es.close();
      if (dot) dot.className = status === 'done' ? 'log-dot done' : 'log-dot error';
      const spinner = document.getElementById('pipeline-spinner');
      if (spinner) { spinner.className = ''; spinner.textContent = status === 'done' ? '✓' : '✗'; }

      if (status === 'done') {
        for (let i = 0; i <= sitrepState.currentStep; i++)
          if (sitrepState.stepStates[i] !== 'cached') setSitrepStepState(i, 'done');
        appendLog('─── Pipeline completed successfully ───');
        setTimeout(() => loadSitrepReportsList(), 1500);
      } else {
        setSitrepStepState(sitrepState.currentStep, 'error');
        appendLog('─── Pipeline failed with error ───');
        appendLog('Tip: Check the log above for error details. You can re-run with "Skip cache" to restart from scratch.');
      }
      sitrepState.activeJobId = null;
      document.getElementById('btn-run').disabled = false;
      return;
    }
    appendLog(data);
  };

  es.onerror = () => {
    es.close();
    appendLog('[Connection lost]');
  };
}

async function runPipeline() {
  const country = document.getElementById('inp-country').value.trim();
  const event = document.getElementById('inp-event').value.trim();
  if (!country) { alert('Country name is required.'); return; }

  // Check chunk preview warning
  const cpEl = document.getElementById('chunk-preview');
  if (cpEl && cpEl.classList.contains('err')) {
    if (!confirm('No matching data found for the selected filters. Run anyway?')) return;
  }

  const dateFrom = document.getElementById('inp-date-from').value || '';
  const dateTo = document.getElementById('inp-date-to').value || '';
  const skipCache = document.getElementById('chk-skip-cache').checked;
  const themesRaw = document.getElementById('inp-themes')?.value || '';
  const themes = themesRaw.split(',').map(t => t.trim()).filter(Boolean);

  document.getElementById('btn-run').disabled = true;

  // Reset progress
  sitrepState.currentStep = -1;
  sitrepState.stepStates = new Array(STEPS.length).fill('waiting');
  buildStepsGrid();
  const cons = document.getElementById('log-console');
  if (cons) cons.innerHTML = '';
  const dot = document.getElementById('log-dot');
  if (dot) dot.className = 'log-dot running';
  const spinner = document.getElementById('pipeline-spinner');
  if (spinner) { spinner.className = 'spin'; spinner.textContent = ''; }
  const titleEl = document.getElementById('pipeline-title-text');
  if (titleEl) titleEl.textContent = `${country} / ${event || country}  —  running…`;

  showSitrepView('pipeline');
  deactivateSitrepItems();

  try {
    const resp = await api('/api/sitrep/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country, event, themes, skip_cache: skipCache, date_from: dateFrom, date_to: dateTo }),
    });
    const { job_id, stream_nonce, error } = await resp.json();
    if (error) { alert('Error: ' + error); document.getElementById('btn-run').disabled = false; return; }
    connectSSE(job_id, stream_nonce);
  } catch (err) {
    alert('Server error: ' + err);
    document.getElementById('btn-run').disabled = false;
  }
}

async function loadSitrepReportsList() {
  const list = document.getElementById('sitrep-reports-list');
  if (!list) return;
  try {
    const resp = await api('/api/sitrep/reports');
    const items = await resp.json();
    if (!items.length) {
      list.innerHTML = '<div class="empty-state">No reports yet.</div>';
      return;
    }
    list.innerHTML = '';
    const canDelete = (window.__userRole || 'free') === 'admin';
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = 'report-item';
      div.dataset.file = item.filename;
      div.dataset.action = 'open-sitrep-report';
      const country = item.filename.split('_')[0].replace(/\(/g, ' ').replace(/\)/g, '').trim();
      div.innerHTML = `<span>${escHtml(country)}</span>` +
        (canDelete ? `<button class="report-item-delete" data-action="delete-sitrep-report" data-file="${escHtml(item.filename)}" title="Delete report (admin)">✕</button>` : '');
      list.appendChild(div);
    });
  } catch {
    list.innerHTML = '<div class="empty-state">Could not connect to server.</div>';
  }
}

function deactivateSitrepItems() {
  document.querySelectorAll('.report-item.active').forEach(el => el.classList.remove('active'));
  sitrepState.activeFile = null;
}

async function openSitrepReport(filename, itemEl) {
  deactivateSitrepItems();
  if (itemEl) itemEl.classList.add('active');
  sitrepState.activeFile = filename;

  showSitrepView('report');
  document.getElementById('report-content').innerHTML =
    '<div class="loading-placeholder">Loading…</div>';

  try {
    const resp = await api(`/api/sitrep/report?file=${encodeURIComponent(filename)}`);
    const report = await resp.json();
    if (report.error) throw new Error(report.error);
    renderSitrepReport(report, filename);
  } catch (err) {
    document.getElementById('report-content').innerHTML =
      `<div class="error-placeholder">Could not load report: ${escHtml(err.message)}</div>`;
  }
}

async function deleteSitrepReport(filename, itemEl) {
  if (!confirm(`Delete SITREP report "${filename}"? This cannot be undone.`)) return;
  try {
    const resp = await api(`/api/sitrep/report?file=${encodeURIComponent(filename)}`, { method: 'DELETE' });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    if (itemEl) itemEl.remove();
    if (sitrepState.activeFile === filename) {
      sitrepState.activeFile = null;
      showSitrepView('welcome');
    }
    loadSitrepReportsList();
  } catch (err) {
    alert('Could not delete report: ' + err.message);
  }
}

function renderSitrepReport(report, filename) {
  _currentReportData = report;
  _currentReportFile = filename;

  const raw = report.file_name || filename.replace(/_report\.json$/, '');
  const parts = raw.replace(/_/g, ' ').split(/\s+/);
  const country = parts[0];
  const evt = parts.slice(1).join(' ');

  const hasNarrative = !!(report.narrative_html && report.narrative_html.trim());
  const rThemes = report.themes || [];
  const rDateFrom = report.date_from || '';
  const rDateTo = report.date_to || '';
  const clusters = report.clusters || [];
  const narrSources = hasNarrative ? (report.narrative_sources || {}) : {};
  const sourceCount = Object.entries(narrSources).filter(([k, v]) => !isNaN(Number(k)) && v && typeof v === 'object' && (v.url || v.title)).length;

  // ── Hero banner ──
  let html = `
    <div class="report-hero">
      <div class="report-hero-content">
        <div class="report-hero-badge"><svg class="icon-svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="vertical-align:-1px; margin-right:4px;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><span>SPECIAL DISPATCH</span></div>
        <h1 class="report-hero-title">${escHtml(country)}</h1>
        <div class="report-hero-subtitle">${escHtml(evt)}</div>
        <div class="report-hero-meta">
          ${(rDateFrom || rDateTo) ? `<span class="report-hero-date"><svg class="icon-svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px; margin-right:4px;"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>${escHtml(rDateFrom || '…')} — ${escHtml(rDateTo || '…')}</span>` : ''}
          ${rThemes.length ? rThemes.map(t => `<span class="report-hero-theme">${escHtml(t)}</span>`).join('') : ''}
        </div>
      </div>
      <div class="report-hero-actions">
        <button class="btn-sm btn-discuss-agent btn-with-icon" data-action="discuss-sitrep">
          <svg class="icon-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span>Discuss with Sightline</span>
        </button>
        <button class="btn-sm btn-discuss-agent btn-with-icon" data-action="proposal-from-sitrep" data-country="${esc(country)}" data-event="${esc(evt)}" data-themes="${esc(rThemes.join(','))}" data-date-from="${esc(rDateFrom)}" data-date-to="${esc(rDateTo)}">
          <svg class="icon-svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          <span>Design Proposal</span>
        </button>
      </div>
    </div>`;

  // ── Key figures row ──
  html += `<div class="report-kf-row">`;
  html += `<div class="report-kf-card"><div class="report-kf-value">${clusters.length}</div><div class="report-kf-label">Clusters</div></div>`;
  html += `<div class="report-kf-card"><div class="report-kf-value">${sourceCount || Object.keys(narrSources).filter(k => !isNaN(Number(k))).length}</div><div class="report-kf-label">Sources</div></div>`;
  html += `<div class="report-kf-card"><div class="report-kf-value">${rThemes.length}</div><div class="report-kf-label">Themes</div></div>`;
  if (rDateFrom && rDateTo) {
    const days = Math.max(1, Math.round((new Date(rDateTo) - new Date(rDateFrom)) / 86400000));
    html += `<div class="report-kf-card"><div class="report-kf-value">${days}</div><div class="report-kf-label">Days Covered</div></div>`;
  }
  // HDX key figures
  const hdxData = report.hdx_data || {};
  const hdxSummary = hdxData.summary || {};
  if (hdxSummary.refugees_total && hdxSummary.refugees_total > 0) {
    html += `<div class="report-kf-card hdx-kf"><div class="report-kf-value">${(hdxSummary.refugees_total).toLocaleString()}</div><div class="report-kf-label">Refugees (HDX)</div></div>`;
  }
  if (hdxSummary.idps_total && hdxSummary.idps_total > 0) {
    html += `<div class="report-kf-card hdx-kf"><div class="report-kf-value">${(hdxSummary.idps_total).toLocaleString()}</div><div class="report-kf-label">IDPs (HDX)</div></div>`;
  }
  const hdxReq = hdxSummary.funding_required_usd || 0;
  const hdxFund = hdxSummary.funding_funded_usd || 0;
  if (hdxReq > 0) {
    const pct = ((hdxFund / hdxReq) * 100).toFixed(0);
    html += `<div class="report-kf-card hdx-kf"><div class="report-kf-value">${pct}%</div><div class="report-kf-label">Funded (HDX)</div></div>`;
  }
  html += `</div>`;

  // View toggle (only if narrative exists)
  if (hasNarrative) {
    html += `
      <div class="report-view-toggle">
        <button class="report-view-btn active" data-mode="narrative" data-action="switch-report-view">Editorial Narrative</button>
        <button class="report-view-btn" data-mode="qa" data-action="switch-report-view">Field Q&A Briefing</button>
      </div>`;
  }

  // ── Narrative view ──
  if (hasNarrative) {
    const rawNarrative = (report.narrative_html || '').replace(/<\/h[1-6]>/gi, '$&\n\n');
    // narrative_html is already HTML from the LLM — skip md() to preserve citations
    let narrativeHtml = renderNarrativeCitations(sanitizeHtml(rawNarrative), narrSources);
    // Add id attributes to headings for TOC anchor links
    narrativeHtml = narrativeHtml.replace(/<h([1-3])([^>]*)>([\s\S]*?)<\/h[1-3]>/gi, (match, level, attrs, inner) => {
      const text = inner.replace(/<[^>]+>/g, '').trim();
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').substring(0, 60);
      return `<h${level} id="${esc(id)}"${attrs}>${inner}</h${level}>`;
    });
    const tocHtml = buildNarrativeToc(narrativeHtml);
    html += `<div id="report-narrative-view" class="report-view-section">`;
    html += `<div class="narrative-layout">`;
    if (tocHtml) html += `<nav class="narrative-toc"><div class="narrative-toc-title">Dispatch Index</div>${tocHtml}</nav>`;
    html += `<div class="narrative-content"><div class="narrative-body">${narrativeHtml}</div>`;
    html += buildNarrativeSourcesList(narrSources);
    html += `</div></div></div>`;
  }

  // ── Q&A view ──
  html += `<div id="report-qa-view" class="report-view-section ${hasNarrative ? 'hidden' : ''}">`;

  if (report.summary) {
    const summaryCtx = report.summary_contexts || {};
    html += `
      <div class="sitrep-section-card">
        <div class="sitrep-section-header" data-action="toggle-card">
          <span>Executive Summary</span>
          <span class="toggle-icon">▾</span>
        </div>
        <div class="sitrep-section-body">
          <div class="summary-text">${renderCitations(escHtml(report.summary), summaryCtx)}</div>
          ${buildSummarySourcesList(summaryCtx)}
        </div>
      </div>`;
  }

  const clusterList = report.clusters || [];
  clusterList.forEach((cluster, ci) => {
    const headline = cluster.cluster_headline || `Cluster ${cluster.cluster_id}`;
    const qas = cluster.questions_and_answers || [];
    const { qaRemaps, sources } = buildClusterContextIndex(cluster);

    let qaHtml = '';
    qas.forEach((qa, qi) => {
      const answer = qa.updated_retrieved_answer || qa.retrieved_answer || '';
      const remap = qaRemaps[qi];
      const isNoAns = /no clear answer|do not contain information/i.test(answer);
      qaHtml += `
        <div class="qa-item">
          <div class="qa-question">Q${qi + 1}. ${escHtml(qa.question)}</div>
          <div class="qa-answer ${isNoAns ? 'no-answer' : ''}">
            ${isNoAns ? escHtml(answer) : renderCitationsRemapped(escHtml(answer), remap)}
          </div>
        </div>`;
    });

    html += `
      <div class="sitrep-section-card">
        <div class="sitrep-section-header" data-action="toggle-card">
          <span class="cluster-badge">Cluster ${cluster.cluster_id}</span>
          &nbsp;${escHtml(headline)}
          <span class="toggle-icon">▾</span>
        </div>
        <div class="sitrep-section-body ${ci > 0 ? 'hidden' : ''}">
          ${qaHtml || '<div class="msg-muted no-qa-msg">No Q&A for this cluster.</div>'}
          ${buildSourcesListFromArray(sources)}
        </div>
      </div>`;
  });

  if (!clusterList.length) {
    html += '<div class="msg-muted no-clusters-msg">No clusters found.</div>';
  }

  html += `</div>`; // close report-qa-view

  document.getElementById('report-content').innerHTML = html;
}

// ── Narrative citation helpers ───────────────────────────────────────────────

function renderNarrativeCitations(htmlText, narrativeSources) {
  return htmlText.replace(/\[(\d+)\]/g, (match, num) => {
    const src = narrativeSources && (narrativeSources[num] || narrativeSources[String(num)]);
    return _renderCitationSpan(num, src);
  });
}

function buildNarrativeToc(html) {
  const headingRegex = /<h([1-3])[^>]*id=["']([^"']*)["'][^>]*>([\s\S]*?)<\/h[1-3]>/gi;
  const headings = [];
  let match;
  while ((match = headingRegex.exec(html)) !== null) {
    const raw = match[3].replace(/<[^>]+>/g, '').trim();
    const text = raw.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"');
    headings.push({ level: parseInt(match[1]), id: match[2], text });
  }
  if (headings.length < 2) return '';
  return headings.map(h => {
    const txt = h.text.substring(0, 60);
    const ellipsis = h.text.length > 60 ? '…' : '';
    return `<a href="#${esc(h.id)}" class="level-h${h.level}" onclick="event.preventDefault();document.getElementById('${esc(h.id)}')?.scrollIntoView({behavior:'smooth',block:'start'})">${esc(txt)}${ellipsis}</a>`;
  }).join('\n');
}

function buildNarrativeSourcesList(narrativeSources) {
  const sources = Object.entries(narrativeSources)
    .filter(([_num, src]) => src && typeof src === 'object' && (src.url || src.title))
    .filter(([num]) => !isNaN(Number(num)))
    .map(([num, src]) => ({ ...src, num }))
    .sort((a, b) => parseInt(a.num) - parseInt(b.num));
  return buildSourcesList(sources, { cardStyle: true });
}

// ── Citation helpers ─────────────────────────────────────────────────────────

function buildClusterContextIndex(cluster) {
  const canonToNum = new Map();
  const canonToCtx = new Map();
  let counter = 1;
  const qas = cluster.questions_and_answers || [];
  qas.forEach(qa => {
    Object.values(qa.used_contexts || {}).forEach(ctx => {
      const canon = ctx.url || ctx.title || JSON.stringify(ctx.context || '');
      if (!canonToNum.has(canon)) {
        canonToNum.set(canon, counter++);
        canonToCtx.set(canon, ctx);
      }
    });
  });
  const qaRemaps = qas.map(qa => {
    const remap = {};
    Object.entries(qa.used_contexts || {}).forEach(([origNum, ctx]) => {
      const canon = ctx.url || ctx.title || JSON.stringify(ctx.context || '');
      remap[origNum] = { newNum: canonToNum.get(canon), ctx };
    });
    return remap;
  });
  const sources = [];
  canonToNum.forEach((num, canon) => sources.push({ num, ...canonToCtx.get(canon) }));
  sources.sort((a, b) => a.num - b.num);
  return { qaRemaps, sources };
}

function _renderCitationSpan(num, ctx) {
  if (!ctx) return `<span class="citation citation-fallback">[${num}]</span>`;
  const ctxText = encodeURIComponent(ctx.context || '');
  const ctxTitle = encodeURIComponent(ctx.title || '');
  const ctxUrl = encodeURIComponent(ctx.url || '');
  return `<span class="citation" data-action="show-citation" data-num="${num}" data-date="${ctxText}" data-title="${ctxTitle}" data-url="${ctxUrl}">[${num}]</span>`;
}

function renderCitationsRemapped(escapedText, remap) {
  return escapedText.replace(/\[(\d+)\]/g, (match, origNum) => {
    const entry = remap && remap[origNum];
    if (!entry) return `<span class="citation citation-fallback">[?]</span>`;
    return _renderCitationSpan(entry.newNum, entry.ctx);
  });
}

function renderCitations(escapedText, contexts) {
  return escapedText.replace(/\[(\d+)\]/g, (match, num) => {
    const ctx = contexts && (contexts[num] || contexts[String(num)]);
    return _renderCitationSpan(num, ctx);
  });
}

function showCitation(num, ctxEnc, titleEnc, urlEnc) {
  const ctx = decodeURIComponent(ctxEnc);
  const title = decodeURIComponent(titleEnc);
  const url = decodeURIComponent(urlEnc);

  document.getElementById('sitrep-modal-heading').textContent = `Source [${num}]`;
  document.getElementById('sitrep-modal-context').textContent = ctx || '(no content)';
  document.getElementById('sitrep-modal-title').textContent = title || '(no title)';

  const linkEl = document.getElementById('sitrep-modal-source-link');
  if (url) { linkEl.href = url; linkEl.removeAttribute('data-no-url'); }
  else { linkEl.href = '#'; linkEl.setAttribute('data-no-url', '1'); }

  document.getElementById('sitrep-modal-overlay').classList.remove('hidden');
}

function showCitationFromEl(el) {
  showCitation(
    el.dataset.num,
    el.dataset.date || '',
    el.dataset.title || '',
    el.dataset.url || ''
  );
}

function closeSitrepModal() {
  document.getElementById('sitrep-modal-overlay').classList.add('hidden');
}

function buildSourcesList(sources, { cardStyle = false } = {}) {
  const valid = sources.filter(s => s.url || s.title);
  if (!valid.length) return '';
  let items = '';
  valid.forEach(src => {
    let domain = '';
    try { domain = new URL(src.url || '').hostname.replace(/^www\./, ''); } catch { }
    const href = src.url ? escHtml(src.url) : '#';
    const noUrl = src.url ? '' : (cardStyle ? 'class="source-no-url"' : 'class="source-no-url"');
    const icon = cardStyle ? getSourceIcon(domain, src.url) : null;
    const num = src.num || src.key;
    items += cardStyle
      ? `<a class="source-card" href="${href}" target="_blank" rel="noopener noreferrer" ${noUrl}>
          <div class="source-card-icon">${icon}</div>
          <div class="source-card-body">
            <div class="source-card-title">${escHtml(src.title || '—')}</div>
            <div class="source-card-meta">
              ${domain ? `<span class="source-card-domain">${escHtml(domain)}</span>` : ''}
              ${src.date ? `<span class="source-card-date">${escHtml(src.date)}</span>` : ''}
            </div>
          </div>
          <span class="source-card-num">[${escHtml(String(num))}]</span>
        </a>`
      : `<a class="source-item" href="${href}" target="_blank" rel="noopener noreferrer" ${noUrl}>
          <span class="source-item-num">${escHtml(String(num))}</span>
          <span class="source-item-body">
            <div class="source-item-title">${escHtml(src.title || src.url || '—')}</div>
            ${domain ? `<div class="source-item-domain">${escHtml(domain)}</div>` : ''}
          </span>
          <span class="source-item-icon">↗</span>
        </a>`;
  });
  const label = cardStyle ? '📎 Sources' : 'Sources';
  const inner = cardStyle ? `<div class="sources-grid">${items}</div>` : items;
  return `<div class="sources-section"><div class="sources-title">${label} (${valid.length})</div>${inner}</div>`;
}

function getSourceIcon(domain, url) {
  if (domain.includes('reliefweb')) return '🌐';
  if (domain.includes('un')) return '🇺🇳';
  if (domain.includes('ocha')) return '📍';
  if (url) return '🔗';
  return '📄';
}

function buildSummarySourcesList(summaryCtx) {
  const sources = Object.entries(summaryCtx)
    .filter(([, ctx]) => ctx && (ctx.url || ctx.title))
    .map(([num, ctx]) => ({ ...ctx, num }))
    .sort((a, b) => parseInt(a.num) - parseInt(b.num));
  return buildSourcesList(sources);
}

function buildSourcesListFromArray(sources) {
  return buildSourcesList(sources);
}

function toggleCard(header) {
  const body = header.nextElementSibling;
  const isHidden = body.classList.toggle('hidden');
  header.classList.toggle('collapsed', isHidden);
}

function showSitrepView(name) {
  ['welcome', 'pipeline', 'report', 'bulletin'].forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.toggle('hidden', v !== name);
  });
}

// ── Theme pills loader ──────────────────────────────────────────────────────
// ── Country dropdown loader ─────────────────────────────────────────────────
async function loadCountryDropdown() {
  const sel = document.getElementById('inp-country');
  if (!sel) return;
  try {
    const resp = await api('/api/sitrep/countries');
    const countries = await resp.json();
    if (!countries.length || countries.error) return;
    // API now returns [{name, count}] — show chunk count and warn if < 20
    sel.innerHTML = '<option value="">Select country…</option>';
    countries.forEach(c => {
      const opt = document.createElement('option');
      const name = typeof c === 'string' ? c : c.name;
      const count = typeof c === 'object' ? (c.count || 0) : 0;
      opt.value = name;
      if (count > 0 && count < 20) {
        opt.textContent = `${name} (${count} chunks — limited data)`;
        opt.style.color = '#d97706';
      } else if (count > 0) {
        opt.textContent = `${name} (${count.toLocaleString()})`;
      } else {
        opt.textContent = name;
      }
      sel.appendChild(opt);
    });
  } catch {
    // Silently fail — dropdown stays empty
  }
}

// ── Country date-range hint ─────────────────────────────────────────────────
async function fetchCountryDateRange(country) {
  const hint = document.getElementById('date-range-hint');
  if (!hint) return;
  if (!country) { hint.textContent = ''; return; }
  try {
    const resp = await api(`/api/sitrep/date-range/${encodeURIComponent(country)}`);
    const data = await resp.json();
    if (data.error || !data.count) {
      hint.textContent = `No data found for "${country}"`;
      return;
    }
    hint.textContent = `${data.count} chunks · ${data.min} → ${data.max}`;
    // Set min/max constraints on date inputs so user can only pick within available range
    const dfEl = document.getElementById('inp-date-from');
    const dtEl = document.getElementById('inp-date-to');
    if (dfEl) { dfEl.min = data.min; dfEl.max = data.max; }
    if (dtEl) { dtEl.min = data.min; dtEl.max = data.max; }
  } catch {
    hint.textContent = '';
  }
  // Also refresh chunk preview after date range loads
  refreshChunkPreview();
}

// ── Chunk preview (pre-run filter check) ─────────────────────────────────────
let _cpTimer = null;
function scheduleChunkPreview() {
  clearTimeout(_cpTimer);
  _cpTimer = setTimeout(refreshChunkPreview, 400);
}

async function refreshChunkPreview() {
  const el = document.getElementById('chunk-preview');
  if (!el) return;
  const country = (document.getElementById('inp-country')?.value || '').trim();
  if (!country) { el.classList.add('hidden'); return; }

  const dateFrom = document.getElementById('inp-date-from')?.value || '';
  const dateTo = document.getElementById('inp-date-to')?.value || '';
  const themesRaw = document.getElementById('inp-themes')?.value || '';
  const themes = themesRaw.split(',').map(t => t.trim()).filter(Boolean);

  try {
    const resp = await api('/api/sitrep/chunk-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country, date_from: dateFrom, date_to: dateTo, themes }),
    });
    const data = await resp.json();
    if (data.error) { el.classList.add('hidden'); return; }

    el.classList.remove('hidden', 'ok', 'warn', 'err');
    if (data.count === 0) {
      el.classList.add('err');
      const filterParts = [];
      if (dateFrom) filterParts.push(`from: ${dateFrom}`);
      if (dateTo) filterParts.push(`to: ${dateTo}`);
      el.innerHTML = `<div class="cp-count"><svg class="inline-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right:5px;vertical-align:-1.5px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>No matching data found</div>` +
        (filterParts.length ? `<div class="cp-themes">Filters: ${escHtml(filterParts.join(' · '))}. Try adjusting your selection.</div>` : '');
    } else if (data.count < 20) {
      el.classList.add('warn');
      el.innerHTML = `<div class="cp-count"><svg class="inline-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right:5px;vertical-align:-1.5px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Only ${data.count} chunks match — results may be limited</div>` +
        (data.themes_found.length ? `<div class="cp-themes">Topics: ${data.themes_found.map(escHtml).join(', ')}</div>` : '');
    } else {
      el.classList.add('ok');
      el.innerHTML = `<div class="cp-count"><svg class="inline-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right:5px;vertical-align:-1.5px"><polyline points="20 6 9 17 4 12"/></svg>${data.count} chunks available</div>` +
        (data.themes_found.length ? `<div class="cp-themes">Top topics: ${data.themes_found.map(escHtml).join(', ')}</div>` : '');
    }
  } catch {
    el.classList.add('hidden');
  }
}

// ── Narrative / Q&A report toggle ────────────────────────────────────────────
let _currentReportData = null;
let _currentReportFile = null;

function switchReportView(mode) {
  document.querySelectorAll('.report-view-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`.report-view-btn[data-mode="${mode}"]`)?.classList.add('active');

  const qaView = document.getElementById('report-qa-view');
  const narrView = document.getElementById('report-narrative-view');
  if (!qaView || !narrView) return;

  if (mode === 'narrative') {
    qaView.classList.add('hidden');
    narrView.classList.remove('hidden');
  } else {
    qaView.classList.remove('hidden');
    narrView.classList.add('hidden');
  }
}

// ── SITREP → AgenTRC discuss ────────────────────────────────────────────────
async function discussSitrepWithAgent() {
  if (!sitrepState.activeFile) return;

  // Fetch the full report JSON
  let report;
  try {
    const resp = await api(`/api/sitrep/report?file=${encodeURIComponent(sitrepState.activeFile)}`);
    report = await resp.json();
    if (report.error) throw new Error(report.error);
  } catch (err) {
    alert('Could not load SITREP report: ' + err.message);
    return;
  }

  // Build a comprehensive context string
  const raw = report.file_name || sitrepState.activeFile.replace(/_report\.json$/, '');
  const parts = raw.replace(/_/g, ' ').split(/\s+/);
  const country = parts[0];
  const evt = parts.slice(1).join(' ');

  let ctx = `**SITREP Report Context: ${country} — ${evt}**\n\n`;
  ctx += `I have analyzed a SITREP report for **${country}** regarding **${evt}**. Here is the full analysis:\n\n`;

  // Narrative report (professional prose)
  if (report.narrative_html) {
    ctx += `## Narrative Report\n`;
    const tmp = document.createElement('div');
    tmp.textContent = report.narrative_html;
    ctx += tmp.textContent.trim() + '\n\n';
    // Narrative sources
    const ns = report.narrative_sources || {};
    const nLinks = Object.values(ns).filter(s => s.url).map(s => `- [${s.title || 'Source'}](${s.url})`);
    if (nLinks.length) ctx += `**Narrative Sources:**\n${nLinks.join('\n')}\n\n`;
  }

  // Summary
  if (report.summary) {
    ctx += `## Executive Summary\n${report.summary}\n\n`;
    const sCtx = report.summary_contexts || {};
    const sLinks = Object.values(sCtx).filter(s => s.url).map(s => `- [${s.title || 'Source'}](${s.url})`);
    if (sLinks.length) ctx += `**Summary Sources:**\n${sLinks.join('\n')}\n\n`;
  }

  // Clusters with Q&A and sources
  const clusters = report.clusters || [];
  clusters.forEach(cluster => {
    const headline = cluster.cluster_headline || `Cluster ${cluster.cluster_id}`;
    ctx += `## ${headline}\n`;
    const qas = cluster.questions_and_answers || [];
    qas.forEach((qa, i) => {
      const answer = qa.updated_retrieved_answer || qa.retrieved_answer || 'No answer available';
      ctx += `**Q${i + 1}: ${qa.question}**\n${answer}\n\n`;
    });
    // Gather all sources for this cluster
    const seenUrls = new Set();
    qas.forEach(qa => {
      Object.values(qa.used_contexts || {}).forEach(s => {
        if (s.url && !seenUrls.has(s.url)) {
          seenUrls.add(s.url);
          ctx += `- [${s.title || 'Source'}](${s.url})\n`;
        }
      });
    });
    ctx += '\n';
  });

  ctx += `---\nYou can now ask me any detailed questions about this SITREP report, its sources, findings, or request deeper analysis on specific topics.`;

  // Create a new chat with this context pre-loaded
  try {
    const r = await api('/api/agent/chats/new-with-context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: `SITREP: ${country} — ${evt}`,
        context: ctx,
      }),
    });
    const d = await r.json();
    if (!d.id) throw new Error('Failed to create chat');

    // Switch to Agent tab
    switchTab('agent');

    // Load messages for this new chat (will show the context message)
    const mr = await api(`/api/agent/chats/${d.id}/messages`);
    const msgs = await mr.json();
    chatDiv.innerHTML = '';
    if (msgs.messages && msgs.messages.length > 0) {
      for (const m of msgs.messages) {
        if (m.role === 'user') addMsg('user', esc(m.content));
        else addMsg('assistant', sanitizeHtml(md(m.content)));
      }
    }
    chatState.currentAiText = '';
    await loadChatList();

    // Focus input
    const inp = document.getElementById('chat-input');
    if (inp) inp.focus();
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

