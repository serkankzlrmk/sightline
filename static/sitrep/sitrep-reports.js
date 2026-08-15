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

