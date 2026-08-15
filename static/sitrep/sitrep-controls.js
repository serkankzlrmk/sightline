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

