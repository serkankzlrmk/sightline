// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for TRC Data Platform
//
// Tab 1: Database  → /api/db/*
// Tab 2: Agent     → /api/agent/chat
// Tab 3: SITREP    → /api/sitrep/*
// ═══════════════════════════════════════════════════════════════════════════

// ── Shared state ────────────────────────────────────────────────────────────
let currentTab = 'agent';

// DB tab state
let allReports     = [];
let sortKey        = 'date';
let sortAsc        = false;
let filterTimer    = null;
let currentReportTitle = '';
let currentReportId    = null;

// Agent tab state
let isStreaming    = false;
let currentAiEl   = null;
let currentAiText = '';

// SITREP tab state
let sitrepCurrentStep  = -1;

// Ingest tab state
let mqResults     = [];
let uploadHistory = [];
const _tags = { country: [], theme: [] };
let sitrepStepStates   = [];
let sitrepActiveJobId  = null;
let sitrepActiveFile   = null;

// ── DOM references (populated on DOMContentLoaded) ─────────────────────────
let chatInput, sendBtn, chatDiv, busyDot;

// ═══════════════════════════════════════════════════════════════════════════
// SHARED HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
// alias for SITREP code
const escHtml = esc;

// LaTeX notation → Unicode cleanup (runs before markdown parse)
const _latexMap = {
  '\\rightarrow':  '→', '\\leftarrow':   '←', '\\leftrightarrow': '↔',
  '\\Rightarrow':  '⇒', '\\Leftarrow':   '⇐', '\\Leftrightarrow': '⇔',
  '\\geq':         '≥', '\\leq':         '≤', '\\neq':  '≠',
  '\\approx':      '≈', '\\pm':          '±', '\\times': '×',
  '\\div':         '÷', '\\infty':       '∞', '\\sum':  '∑',
  '\\prod':        '∏', '\\sqrt':        '√', '\\alpha': 'α',
  '\\beta':        'β', '\\gamma':       'γ', '\\delta': 'δ',
  '\\lambda':      'λ', '\\mu':          'μ', '\\pi':    'π',
  '\\sigma':       'σ', '\\omega':       'ω', '\\theta': 'θ',
  '\\cdot':        '·', '\\dots':        '…', '\\ldots': '…',
  '\\degree':      '°', '\\checkmark':   '✓', '\\star':  '★',
};
function cleanLatex(text) {
  // Replace $\cmd$ and \cmd patterns
  return text.replace(/\$\\([a-zA-Z]+)\$/g, (_, cmd) =>
    _latexMap['\\' + cmd] || cmd
  ).replace(/\\([a-zA-Z]+)/g, (m, cmd) =>
    _latexMap['\\' + cmd] || m
  );
}

function md(text) {
  try   { return marked.parse(cleanLatex(text), { breaks: true, gfm: true }); }
  catch { return esc(text).replace(/\n/g, '<br>'); }
}

// ── Tab switching ────────────────────────────────────────────────────────────
function switchTab(name) {
  currentTab = name;
  ['db', 'agent', 'sitrep', 'ingest'].forEach(t => {
    document.getElementById('panel-' + t).classList.toggle('active', t === name);
    document.getElementById('tab-'   + t).classList.toggle('active', t === name);
  });
  // Show/hide agent reset button
  const resetBtn = document.getElementById('agent-reset-btn');
  if (resetBtn) resetBtn.style.display = (name === 'agent') ? '' : 'none';

  if (name === 'db') reloadReports();
  if (name === 'sitrep') loadSitrepReportsList();
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 2 — AGENT CHAT (multi-chat)
// ═══════════════════════════════════════════════════════════════════════════

const WELCOME_HTML = `
  <div class="msg assistant">
    <div class="msg-avatar">AI</div>
    <div class="msg-body">
      Hello! I'm connected to the TRC humanitarian data platform.<br><br>
      What I can do:
      <ul>
        <li>Search reports by country, theme, or source</li>
        <li>Download reports and save them to the local database</li>
        <li>Run semantic queries and summaries over downloaded reports</li>
      </ul><br>
      Example: <em>"Fetch and download Sudan health reports"</em><br>
      or: <em>"What's happening in Iran in the last month?"</em>
    </div>
  </div>`;

function addMsg(role, html) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  wrap.innerHTML = `
    <div class="msg-avatar">${role === 'user' ? 'You' : 'AI'}</div>
    <div class="msg-body">${html}</div>`;
  chatDiv.appendChild(wrap);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return wrap.querySelector('.msg-body');
}

function addToolInd(name) {
  const el = document.createElement('div');
  el.className = 'tool-ind';
  el.innerHTML = `<div class="spin"></div><span>🔧 <strong>${esc(name)}</strong> running...</span>`;
  chatDiv.appendChild(el);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return el;
}

function clearToolInds() {
  chatDiv.querySelectorAll('.tool-ind').forEach(e => e.remove());
}

async function sendMessage() {
  if (isStreaming) return;
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  chatInput.style.height = 'auto';
  addMsg('user', esc(text));

  isStreaming = true;
  sendBtn.disabled    = true;
  sendBtn.textContent = '...';
  busyDot.classList.add('visible');

  currentAiEl   = addMsg('assistant',
    '<div class="typing-dots"><span></span><span></span><span></span></div>');
  currentAiText = '';

  try {
    const resp = await fetch('/api/agent/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text }),
    });

    if (resp.status === 429) {
      currentAiEl.innerHTML = '<span style="color:#d97706">⚠️ Agent is busy, please wait.</span>';
      return;
    }

    const reader = resp.body.getReader();
    const dec    = new TextDecoder();
    let   buf    = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

        if (evt.type === 'token') {
          if (!currentAiText) currentAiEl.innerHTML = '';
          currentAiText += evt.text;
          currentAiEl.innerHTML = md(currentAiText);
          chatDiv.scrollTop = chatDiv.scrollHeight;
        } else if (evt.type === 'tool_start') {
          if (!currentAiText) currentAiEl.innerHTML = '';
          addToolInd(evt.name);
        } else if (evt.type === 'error') {
          currentAiEl.innerHTML = `<span style="color:#dc2626">❌ Error: ${esc(evt.text)}</span>`;
          clearToolInds();
        } else if (evt.type === 'done') {
          clearToolInds();
          if (!currentAiText) currentAiEl.innerHTML = '<span style="color:#94a3b8">—</span>';
        }
      }
    }
  } catch (err) {
    if (currentAiEl) {
      currentAiEl.innerHTML = `<span style="color:#dc2626">❌ Connection error: ${esc(err.message)}</span>`;
    }
    clearToolInds();
  } finally {
    isStreaming          = false;
    sendBtn.disabled     = false;
    sendBtn.textContent  = 'Send ↑';
    busyDot.classList.remove('visible');
    currentAiEl          = null;
    chatDiv.scrollTop    = chatDiv.scrollHeight;
    loadChatList();  // refresh sidebar (auto-title may have changed)
  }
}

async function resetChat() {
  if (!confirm('Clear chat history?')) return;
  await fetch('/api/agent/chat/reset', { method: 'POST' });
  chatDiv.innerHTML = WELCOME_HTML;
  currentAiText = '';
  loadChatList();
}

// ── Multi-chat management ────────────────────────────────────────────────

async function loadChatList() {
  try {
    const r = await fetch('/api/agent/chats');
    const d = await r.json();
    const list = document.getElementById('chat-list');
    if (!list) return;
    list.innerHTML = '';
    for (const c of d.chats) {
      const item = document.createElement('div');
      item.className = 'chat-item' + (c.id === d.active ? ' active' : '');
      item.innerHTML = `
        <span class="chat-item-title" title="${esc(c.title)}">${esc(c.title)}</span>
        <span class="chat-item-actions">
          <button class="chat-item-btn" onclick="event.stopPropagation(); renameChat('${c.id}')" title="Rename">✏️</button>
          <button class="chat-item-btn delete" onclick="event.stopPropagation(); deleteChat('${c.id}')" title="Delete">🗑️</button>
        </span>`;
      item.addEventListener('click', () => selectChat(c.id));
      list.appendChild(item);
    }
  } catch { /* ignore */ }
}

async function newChat() {
  if (isStreaming) return;
  try {
    await fetch('/api/agent/chats/new', { method: 'POST' });
    chatDiv.innerHTML = WELCOME_HTML;
    currentAiText = '';
    await loadChatList();
  } catch { /* ignore */ }
}

async function selectChat(chatId) {
  if (isStreaming) return;
  try {
    await fetch(`/api/agent/chats/${chatId}/select`, { method: 'POST' });
    // Load and render saved messages
    const r = await fetch(`/api/agent/chats/${chatId}/messages`);
    const d = await r.json();
    chatDiv.innerHTML = '';
    if (d.messages && d.messages.length > 0) {
      for (const m of d.messages) {
        if (m.role === 'user') {
          addMsg('user', esc(m.content));
        } else {
          addMsg('assistant', md(m.content));
        }
      }
    } else {
      chatDiv.innerHTML = WELCOME_HTML;
    }
    currentAiText = '';
    await loadChatList();
  } catch { /* ignore */ }
}

async function renameChat(chatId) {
  const title = prompt('Chat title:');
  if (!title) return;
  try {
    await fetch(`/api/agent/chats/${chatId}/rename`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    await loadChatList();
  } catch { /* ignore */ }
}

async function deleteChat(chatId) {
  if (!confirm('Delete this chat?')) return;
  try {
    await fetch(`/api/agent/chats/${chatId}`, { method: 'DELETE' });
    chatDiv.innerHTML = WELCOME_HTML;
    currentAiText = '';
    await loadChatList();
  } catch { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 1 — VERİTABANI (DB Reports Browser)
// ═══════════════════════════════════════════════════════════════════════════

async function reloadReports() {
  await Promise.all([loadStats(), loadFilterOptions()]);
  await applyFilters();
}

async function loadStats() {
  try {
    const r = await fetch('/api/db/stats');
    const d = await r.json();
    document.getElementById('s-reports').textContent = (d.report_count || 0).toLocaleString();
    document.getElementById('s-chunks').textContent  = (d.chunk_count  || 0).toLocaleString();
  } catch { /* ignore */ }
}

async function loadFilterOptions() {
  try {
    const [cRes, sRes] = await Promise.all([fetch('/api/db/countries'), fetch('/api/db/sources')]);
    const countries    = await cRes.json();
    const sources      = await sRes.json();

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
  const search   = document.getElementById('f-search').value.trim();
  const country  = document.getElementById('f-country').value;
  const source   = document.getElementById('f-source').value;
  const from     = document.getElementById('f-from').value;
  const to       = document.getElementById('f-to').value;

  const p = new URLSearchParams();
  if (search) p.set('search',    search);
  if (source) p.set('source',    source);
  if (from)   p.set('date_from', from);
  if (to)     p.set('date_to',   to);

  try {
    const res  = await fetch('/api/db/reports?' + p);
    let   data = await res.json();
    if (country) {
      data = data.filter(r => (r.all_countries || []).includes(country));
    }
    allReports = data;
  } catch {
    allReports = [];
  }
  renderTable();
}

function dbFilter() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(applyFilters, 280);
}

function sortBy(key) {
  if (sortKey === key) sortAsc = !sortAsc;
  else { sortKey = key; sortAsc = true; }

  document.querySelectorAll('.rtable thead th').forEach(th => {
    th.classList.toggle('sorted', th.getAttribute('onclick') === `sortBy('${key}')`);
  });
  renderTable();
}

function renderTable() {
  const body = document.getElementById('rtbody');
  const data = [...allReports].sort((a, b) => {
    const va = String(a[sortKey] ?? '');
    const vb = String(b[sortKey] ?? '');
    if (va < vb) return sortAsc ? -1 :  1;
    if (va > vb) return sortAsc ?  1 : -1;
    return 0;
  });

  document.getElementById('f-count').textContent = data.length + ' reports';

  if (!data.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty"><div class="icon">🔍</div>No results found</td></tr>';
    return;
  }

  body.innerHTML = data.map(r => {
    const fmtBadge = r.format_type
      ? `<span class="badge b-blue">${esc(r.format_type.replace('Situation Report','Sit.Rep').replace('News and Press Release','News'))}</span>`
      : '';
    const pdfBadge = r.has_pdf
      ? '<span class="badge b-green">PDF</span>'
      : '<span class="badge b-gray">—</span>';

    return `<tr onclick="openDbReport(${r.report_id})">
      <td class="id-cell">${r.report_id}</td>
      <td style="white-space:nowrap">${r.date || ''}</td>
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
  currentReportId = id;
  try {
    const res = await fetch('/api/db/reports/' + id);
    const r   = await res.json();
    currentReportTitle = r.title || '';

    document.getElementById('m-title').textContent     = r.title || '—';
    document.getElementById('m-id').textContent        = r.report_id;
    document.getElementById('m-date').textContent      = r.date || '—';
    document.getElementById('m-countries').textContent = (r.all_countries || []).join(', ') || '—';
    document.getElementById('m-source').textContent    = r.source || '—';
    document.getElementById('m-format').textContent    = r.format_type || '—';
    document.getElementById('m-pdf').textContent       = r.has_pdf ? `✅ Available (${r.pdf_pages} pages)` : '❌ None';
    document.getElementById('m-chunks').textContent    = r.has_content ? `✅ Available (${r.total_chunks} chunks)` : '❌ None';

    let themes = r.themes_list || [];
    if (!themes.length) { try { themes = JSON.parse(r.themes || '[]'); } catch {} }
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
  chatInput.value = `Tell me about the report "${currentReportTitle}" (ID: ${currentReportId}). What are the key findings and summary?`;
  chatInput.focus();
  chatInput.dispatchEvent(new Event('input'));
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 3 — SITREP PIPELINE
// ═══════════════════════════════════════════════════════════════════════════

const STEPS = [
  { id: 0, name: "Chroma Connection",   icon: "🔌" },
  { id: 1, name: "Chunk Loading",       icon: "📦" },
  { id: 2, name: "Clustering",          icon: "🧩" },
  { id: 3, name: "Question Generation", icon: "❓" },
  { id: 4, name: "Question Filtering",  icon: "🔍" },
  { id: 5, name: "RAG Answering",       icon: "🤖" },
  { id: 6, name: "Citation Validation", icon: "🔗" },
  { id: 7, name: "Cluster Summary",     icon: "📝" },
  { id: 8, name: "Executive Summary",   icon: "📋" },
  { id: 9, name: "Report Assembly",     icon: "📄" },
];

const STEP_RE  = /\[INFO\]\s+pipeline:\s+\[(\d)\]/;
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
  sitrepStepStates[idx] = state;
  const card = document.getElementById(`step-card-${idx}`);
  if (!card) return;
  card.className = `step-card ${state}`;
  const iconMap = { waiting: STEPS[idx].icon, active: '⏳', cached: '⚡', done: '✅', error: '❌' };
  card.querySelector('.step-icon').textContent = iconMap[state] || STEPS[idx].icon;
}

function advanceToStep(n) {
  if (n <= sitrepCurrentStep) return;
  if (sitrepCurrentStep >= 0) setSitrepStepState(sitrepCurrentStep, 'done');
  sitrepCurrentStep = n;
  setSitrepStepState(n, 'active');
}

function logClass(line) {
  if (/^\[GPU_WARN\]/i.test(line))                          return 'gpu-warn';
  if (STEP_RE.test(line))                                   return 'step';
  if (/completed successfully|pipeline.*done/i.test(line))  return 'done-line';
  if (CACHE_RE.test(line))                                  return 'cached';
  if (/\[warning\]/i.test(line))                            return 'warn';
  if (/\[error\]/i.test(line) || /traceback/i.test(line))   return 'error';
  if (/\[info\]/i.test(line))                               return 'info';
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
      sitrepCurrentStep = n;
    } else {
      advanceToStep(n);
    }
  }
  if (CACHE_RE.test(line) && !m && sitrepCurrentStep >= 0) {
    setSitrepStepState(sitrepCurrentStep, 'cached');
  }
}

function connectSSE(jobId) {
  sitrepActiveJobId = jobId;
  const es  = new EventSource(`/api/sitrep/stream/${jobId}`);
  const dot = document.getElementById('log-dot');

  es.onmessage = (e) => {
    const data = e.data;
    if (data === '__PING__') return;
    if (data.startsWith('__DONE__')) {
      const status = data.replace('__DONE__', '');
      es.close();
      if (dot) dot.className = status === 'done' ? 'log-dot done' : 'log-dot error';
      const spinner = document.getElementById('pipeline-spinner');
      if (spinner) { spinner.className = ''; spinner.textContent = status === 'done' ? '✅' : '❌'; }

      if (status === 'done') {
        for (let i = 0; i <= sitrepCurrentStep; i++)
          if (sitrepStepStates[i] !== 'cached') setSitrepStepState(i, 'done');
        appendLog('─── Pipeline completed successfully ───');
        setTimeout(() => loadSitrepReportsList(), 1500);
      } else {
        setSitrepStepState(sitrepCurrentStep, 'error');
        appendLog('─── Pipeline failed with error ───');
      }
      sitrepActiveJobId = null;
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
  const event   = document.getElementById('inp-event').value.trim();
  if (!country) { alert('Country name is required.'); return; }

  const themesRaw = document.getElementById('inp-themes').value.trim();
  const themes    = themesRaw ? themesRaw.split(',').map(t => t.trim()).filter(Boolean) : [];
  const skipCache = document.getElementById('chk-skip-cache').checked;

  document.getElementById('btn-run').disabled = true;

  // Reset progress
  sitrepCurrentStep = -1;
  sitrepStepStates  = new Array(STEPS.length).fill('waiting');
  buildStepsGrid();
  const cons = document.getElementById('log-console');
  if (cons) cons.innerHTML = '';
  const dot = document.getElementById('log-dot');
  if (dot) dot.className = 'log-dot running';
  const spinner = document.getElementById('pipeline-spinner');
  if (spinner) { spinner.className = 'spin'; spinner.textContent = '⏳'; }
  const titleEl = document.getElementById('pipeline-title-text');
  if (titleEl) titleEl.textContent = `${country} / ${event || country}  —  running…`;

  showSitrepView('pipeline');
  deactivateSitrepItems();

  try {
    const resp = await fetch('/api/sitrep/run', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ country, event, themes, skip_cache: skipCache }),
    });
    const { job_id, error } = await resp.json();
    if (error) { alert('Error: ' + error); document.getElementById('btn-run').disabled = false; return; }
    connectSSE(job_id);
  } catch (err) {
    alert('Server error: ' + err);
    document.getElementById('btn-run').disabled = false;
  }
}

async function loadSitrepReportsList() {
  const list = document.getElementById('sitrep-reports-list');
  if (!list) return;
  try {
    const resp  = await fetch('/api/sitrep/reports');
    const items = await resp.json();
    if (!items.length) {
      list.innerHTML = '<div class="sidebar-empty">No reports yet.</div>';
      return;
    }
    list.innerHTML = '';
    items.forEach(item => {
      const div = document.createElement('div');
      div.className = 'report-item';
      div.dataset.file = item.filename;

      const name    = item.filename.replace(/_report\.json$/, '').replace(/_/g, ' ');
      const parts   = name.split(' ');
      const country = parts[0];
      const evt     = parts.slice(1).join(' ');

      div.innerHTML = `
        <div class="report-item-name">${escHtml(country)}</div>
        <div class="report-item-meta">${escHtml(evt) || ''}${evt ? ' &nbsp;·&nbsp; ' : ''}${item.size_kb} KB</div>`;
      div.addEventListener('click', () => openSitrepReport(item.filename, div));
      list.appendChild(div);
    });
  } catch {
    list.innerHTML = '<div class="sidebar-empty">Could not connect to server.</div>';
  }
}

function deactivateSitrepItems() {
  document.querySelectorAll('.report-item.active').forEach(el => el.classList.remove('active'));
  sitrepActiveFile = null;
}

async function openSitrepReport(filename, itemEl) {
  deactivateSitrepItems();
  if (itemEl) itemEl.classList.add('active');
  sitrepActiveFile = filename;

  showSitrepView('report');
  document.getElementById('report-content').innerHTML =
    '<div style="color:var(--text-muted);padding:20px">Loading…</div>';

  try {
    const resp   = await fetch(`/api/sitrep/report?file=${encodeURIComponent(filename)}`);
    const report = await resp.json();
    if (report.error) throw new Error(report.error);
    renderSitrepReport(report, filename);
  } catch (err) {
    document.getElementById('report-content').innerHTML =
      `<div style="color:#ef4444;padding:20px">Could not load report: ${escHtml(err.message)}</div>`;
  }
}

function renderSitrepReport(report, filename) {
  const raw     = report.file_name || filename.replace(/_report\.json$/, '');
  const parts   = raw.replace(/_/g, ' ').split(/\s+/);
  const country = parts[0];
  const evt     = parts.slice(1).join(' ');

  let html = `
    <div class="report-header">
      <div>
        <div class="report-title">🌍 ${escHtml(country)}</div>
        <div class="report-subtitle">${escHtml(evt)}</div>
      </div>
      <div class="report-actions">
        <a class="btn-sm" href="/api/sitrep/report?file=${encodeURIComponent(filename)}"
           download="${escHtml(filename)}">⬇ JSON</a>
      </div>
    </div>`;

  if (report.summary) {
    const summaryCtx = report.summary_contexts || {};
    html += `
      <div class="sitrep-section-card">
        <div class="sitrep-section-header" onclick="toggleCard(this)">
          <span>📋</span> Executive Summary
          <span class="toggle-icon">▾</span>
        </div>
        <div class="sitrep-section-body">
          <div class="summary-text">${renderCitations(escHtml(report.summary), summaryCtx)}</div>
          ${buildSummarySourcesList(summaryCtx)}
        </div>
      </div>`;
  }

  const clusters = report.clusters || [];
  clusters.forEach((cluster, ci) => {
    const headline = cluster.cluster_headline || `Cluster ${cluster.cluster_id}`;
    const qas      = cluster.questions_and_answers || [];
    const { qaRemaps, sources } = buildClusterContextIndex(cluster);

    let qaHtml = '';
    qas.forEach((qa, qi) => {
      const answer    = qa.updated_retrieved_answer || qa.retrieved_answer || '';
      const remap     = qaRemaps[qi];
      const isNoAns   = /no clear answer|do not contain information/i.test(answer);
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
        <div class="sitrep-section-header" onclick="toggleCard(this)">
          <span class="cluster-badge">Cluster ${cluster.cluster_id}</span>
          &nbsp;${escHtml(headline)}
          <span class="toggle-icon">▾</span>
        </div>
        <div class="sitrep-section-body ${ci > 0 ? 'hidden' : ''}">
          ${qaHtml || '<div style="color:var(--text-muted);font-size:13px">No Q&A for this cluster.</div>'}
          ${buildSourcesListFromArray(sources)}
        </div>
      </div>`;
  });

  if (!clusters.length) {
    html += '<div style="color:var(--text-muted);font-size:14px;padding:20px">No clusters found.</div>';
  }

  document.getElementById('report-content').innerHTML = html;
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

function renderCitationsRemapped(escapedText, remap) {
  return escapedText.replace(/\[(\d+)\]/g, (match, origNum) => {
    const entry = remap && remap[origNum];
    if (!entry) return `<span class="citation" style="background:#94a3b8">[?]</span>`;
    const { newNum, ctx } = entry;
    const ctxText  = encodeURIComponent(ctx.context || '');
    const ctxTitle = encodeURIComponent(ctx.title || '');
    const ctxUrl   = encodeURIComponent(ctx.url || '');
    return `<span class="citation" onclick="showCitation(${newNum},'${ctxText}','${ctxTitle}','${ctxUrl}')">[${newNum}]</span>`;
  });
}

function renderCitations(escapedText, contexts) {
  return escapedText.replace(/\[(\d+)\]/g, (match, num) => {
    const ctx = contexts && (contexts[num] || contexts[String(num)]);
    if (!ctx) return `<span class="citation" style="background:#94a3b8">[${num}]</span>`;
    const ctxText  = encodeURIComponent(ctx.context || '');
    const ctxTitle = encodeURIComponent(ctx.title || '');
    const ctxUrl   = encodeURIComponent(ctx.url || '');
    return `<span class="citation" onclick="showCitation(${num},'${ctxText}','${ctxTitle}','${ctxUrl}')">[${num}]</span>`;
  });
}

function showCitation(num, ctxEnc, titleEnc, urlEnc) {
  const ctx   = decodeURIComponent(ctxEnc);
  const title = decodeURIComponent(titleEnc);
  const url   = decodeURIComponent(urlEnc);

  document.getElementById('sitrep-modal-heading').textContent = `Source [${num}]`;
  document.getElementById('sitrep-modal-context').textContent = ctx || '(no content)';
  document.getElementById('sitrep-modal-title').textContent   = title || '(no title)';

  const linkEl = document.getElementById('sitrep-modal-source-link');
  if (url) { linkEl.href = url; linkEl.removeAttribute('data-no-url'); }
  else     { linkEl.href = '#'; linkEl.setAttribute('data-no-url', '1'); }

  document.getElementById('sitrep-modal-overlay').classList.remove('hidden');
}

function closeSitrepModal() {
  document.getElementById('sitrep-modal-overlay').classList.add('hidden');
}

function buildSummarySourcesList(summaryCtx) {
  const entries = Object.entries(summaryCtx)
    .filter(([, ctx]) => ctx && (ctx.url || ctx.title))
    .sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
  if (!entries.length) return '';
  let items = '';
  entries.forEach(([num, ctx]) => {
    let domain = '';
    try { domain = new URL(ctx.url || '').hostname.replace(/^www\./, ''); } catch {}
    const href  = ctx.url ? escHtml(ctx.url) : '#';
    const noUrl = ctx.url ? '' : 'style="opacity:0.6;pointer-events:none"';
    items += `
      <a class="source-item" href="${href}" target="_blank" rel="noopener noreferrer" ${noUrl}>
        <span class="source-item-num">${escHtml(num)}</span>
        <span class="source-item-body">
          <div class="source-item-title">${escHtml(ctx.title || ctx.url || '—')}</div>
          ${domain ? `<div class="source-item-domain">${escHtml(domain)}</div>` : ''}
        </span>
        <span class="source-item-icon">↗</span>
      </a>`;
  });
  return `<div class="sources-section"><div class="sources-title">🔗 Sources (${entries.length})</div>${items}</div>`;
}

function buildSourcesListFromArray(sources) {
  const valid = sources.filter(s => s.url || s.title);
  if (!valid.length) return '';
  let items = '';
  valid.forEach(({ num, title, url }) => {
    let domain = '';
    try { domain = new URL(url || '').hostname.replace(/^www\./, ''); } catch {}
    items += `
      <a class="source-item" href="${escHtml(url || '#')}" target="_blank" rel="noopener noreferrer">
        <span class="source-item-num">${num}</span>
        <span class="source-item-body">
          <div class="source-item-title">${escHtml(title || url || '—')}</div>
          ${domain ? `<div class="source-item-domain">${escHtml(domain)}</div>` : ''}
        </span>
        <span class="source-item-icon">↗</span>
      </a>`;
  });
  return `<div class="sources-section"><div class="sources-title">🔗 Sources (${valid.length})</div>${items}</div>`;
}

function toggleCard(header) {
  const body = header.nextElementSibling;
  const icon = header.querySelector('.toggle-icon');
  const isHidden = body.classList.toggle('hidden');
  header.classList.toggle('collapsed', isHidden);
}

function showSitrepView(name) {
  ['welcome', 'pipeline', 'report'].forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.toggle('hidden', v !== name);
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

// ═════════════════════════════════════════════════════════════════════════
// TAB 4 — INGEST
// ═════════════════════════════════════════════════════════════════════════

// —— helpers ——————————————————————————————————

function mqStatus(msg, type = 'info') {
  const el = document.getElementById('mq-status');
  el.style.display = 'block';
  el.className = `ingest-status ${type}`;
  el.textContent = msg;
}
function mqClearStatus() {
  const el = document.getElementById('mq-status');
  el.style.display = 'none';
  el.textContent = '';
}

function upStatus(msg, type = 'info') {
  const el = document.getElementById('up-status');
  el.style.display = 'block';
  el.className = `ingest-status ${type}`;
  el.textContent = msg;
}
function upClearStatus() {
  const el = document.getElementById('up-status');
  el.style.display = 'none';
  el.textContent = '';
}

// —— Manual Query ————————————————————————————————

function mqSearch() {
  const payload = {
    country:     document.getElementById('mq-country').value.trim(),
    query:       document.getElementById('mq-query').value.trim(),
    source_org:  document.getElementById('mq-source').value,
    source_fullname: document.getElementById('mq-source-full').value.trim(),
    organization_type: document.getElementById('mq-org-type').value,
    theme:       document.getElementById('mq-theme').value,
    disaster_type: document.getElementById('mq-disaster-type').value,
    disaster:    document.getElementById('mq-disaster').value.trim(),
    format_type: document.getElementById('mq-format').value,
    language:    document.getElementById('mq-language').value,
    date_from:   document.getElementById('mq-from').value,
    date_to:     document.getElementById('mq-to').value,
    limit:       parseInt(document.getElementById('mq-limit').value) || 50
  };
  // At least one filter must be set
  const hasFilter = payload.country || payload.query || payload.source_org || payload.theme
    || payload.source_fullname || payload.organization_type || payload.disaster_type
    || payload.disaster || payload.format_type || payload.language
    || payload.date_from || payload.date_to;
  if (!hasFilter) {
    mqStatus('Please enter at least one filter.', 'warning');
    return;
  }
  const tbody = document.getElementById('mq-tbody');
  tbody.innerHTML = '<tr><td colspan="8" class="empty"><div class="spinner"></div>Searching…</td></tr>';
  document.getElementById('mq-count').textContent = '';
  const dlSelBtn = document.getElementById('mq-dl-sel-btn');
  const dlNewBtn = document.getElementById('mq-dl-new-btn');
  dlSelBtn.disabled = true;
  dlNewBtn.disabled = true;
  mqClearStatus();

  fetch('/api/ingest/search', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload)
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) { mqStatus(data.error, 'error'); return; }
    mqResults = data.reports || [];
    mqRenderTable();
    document.getElementById('mq-count').textContent = `${mqResults.length} result(s)`;
    const newCount = mqResults.filter(r => !r.already_ingested).length;
    dlSelBtn.disabled = false;
    dlNewBtn.disabled = newCount === 0;
    if (mqResults.length === 0) {
      mqStatus('No reports found with the given filters.', 'warning');
    }
  })
  .catch(err => mqStatus('Error: ' + err.message, 'error'));
}

function mqRenderTable() {
  const tbody = document.getElementById('mq-tbody');
  if (!mqResults.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty"><div class="icon">🔍</div>No results found.</td></tr>';
    return;
  }
  tbody.innerHTML = mqResults.map((r, i) => {
    const badge = r.already_ingested
      ? '<span class="badge-ingested">✓ Ingested</span>'
      : '<span class="badge-new">New</span>';
    return `<tr>
      <td><input type="checkbox" class="mq-chk" data-idx="${i}" ${r.already_ingested ? '' : 'checked'} onchange="mqCheckChange()"></td>
      <td>${r.id}</td>
      <td>${(r.date || '').slice(0, 10)}</td>
      <td>${Array.isArray(r.countries) ? r.countries.join(', ') : (r.countries || '')}</td>
      <td>${Array.isArray(r.source) ? r.source.join(', ') : (r.source || '')}</td>
      <td class="td-title">${escHtml(r.title || '')}</td>
      <td>${Array.isArray(r.format) ? r.format.join(', ') : (r.format || '')}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('');
}

function mqCheckChange() {
  const anyChecked = [...document.querySelectorAll('.mq-chk')].some(c => c.checked);
  document.getElementById('mq-dl-sel-btn').disabled = !anyChecked;
}

function mqToggleAll(checked) {
  document.querySelectorAll('.mq-chk').forEach(c => c.checked = checked);
  mqCheckChange();
}

function mqDownloadSelected() {
  const ids = [...document.querySelectorAll('.mq-chk')]
    .filter(c => c.checked)
    .map(c => mqResults[parseInt(c.dataset.idx)].id);
  if (!ids.length) { mqStatus('No reports checked.', 'warning'); return; }
  mqDoDownload(ids);
}

function mqDownloadNew() {
  const ids = mqResults.filter(r => !r.already_ingested).map(r => r.id);
  if (!ids.length) { mqStatus('All results already ingested.', 'warning'); return; }
  mqDoDownload(ids);
}

function mqDoDownload(ids) {
  mqStatus(`⏳ Downloading and ingesting ${ids.length} report(s)…`, 'info');
  document.getElementById('mq-dl-sel-btn').disabled = true;
  document.getElementById('mq-dl-new-btn').disabled = true;
  document.getElementById('mq-search-btn').disabled = true;

  fetch('/api/ingest/download', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ report_ids: ids })
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) { mqStatus(data.error, 'error'); return; }
    const { ingested, failed, skipped } = data;
    mqStatus(
      `✓ Done: ${ingested} ingested, ${skipped} skipped (already existed), ${failed} failed.`,
      failed > 0 ? 'warning' : 'success'
    );
    document.getElementById('mq-search-btn').disabled = false;
    document.getElementById('mq-dl-sel-btn').disabled = false;
    document.getElementById('mq-dl-new-btn').disabled = false;
    // Refresh table to mark newly ingested rows
    ids.forEach(id => {
      const r = mqResults.find(x => x.id === id);
      if (r) r.already_ingested = true;
    });
    mqRenderTable();
  })
  .catch(err => {
    mqStatus('Error: ' + err.message, 'error');
    document.getElementById('mq-search-btn').disabled = false;
    document.getElementById('mq-dl-sel-btn').disabled = false;
    document.getElementById('mq-dl-new-btn').disabled = false;
  });
}

// —— Tags ———————————————————————————————————————

function tagAdd(field) {
  const inp = document.getElementById(`up-${field}-input`);
  const val = inp.value.trim();
  if (!val) return;
  if (!_tags[field].includes(val)) {
    _tags[field].push(val);
    tagRender(field);
  }
  inp.value = '';
  inp.focus();
}

function tagRemove(field, idx) {
  _tags[field].splice(idx, 1);
  tagRender(field);
}

function tagRender(field) {
  const box = document.getElementById(`up-${field}-tags`);
  box.innerHTML = _tags[field].map((v, i) =>
    `<span class="tag-chip">${escHtml(v)}<button type="button" onclick="tagRemove('${field}',${i})">×</button></span>`
  ).join('');
}

function tagReset() {
  _tags.country = [];
  _tags.theme   = [];
  tagRender('country');
  tagRender('theme');
}

// —— Upload PDF ————————————————————————————————

function clearUploadForm() {
  document.getElementById('upload-form').reset();
  tagReset();
  upClearStatus();
}

function uploadReport(e) {
  e.preventDefault();
  if (!_tags.country.length) {
    upStatus('Please add at least one country tag.', 'warning');
    return false;
  }
  const fd = new FormData();
  fd.append('title',    document.getElementById('up-title').value.trim());
  fd.append('source',   document.getElementById('up-source').value.trim());
  fd.append('format',   document.getElementById('up-format').value.trim());
  fd.append('language', document.getElementById('up-language').value);
  fd.append('date',     document.getElementById('up-date').value);
  fd.append('country',  JSON.stringify(_tags.country));
  fd.append('theme',    JSON.stringify(_tags.theme));
  const pdfFile = document.getElementById('up-pdf').files[0];
  if (!pdfFile) { upStatus('Please select a PDF file.', 'warning'); return false; }
  fd.append('pdf', pdfFile);

  const btn = document.getElementById('up-submit-btn');
  btn.disabled = true;
  upStatus('⏳ Uploading and ingesting…', 'info');

  fetch('/api/ingest/upload', { method: 'POST', body: fd })
  .then(r => r.json())
  .then(data => {
    btn.disabled = false;
    if (data.error) { upStatus(data.error, 'error'); return; }
    upStatus(
      `✓ Ingested as ${data.tr_id} — ${data.pdf_pages} page(s), ${data.chunks_added} chunks added.`,
      'success'
    );
    upAddHistory({
      tr_id:   data.tr_id,
      title:   document.getElementById('up-title').value.trim(),
      source:  document.getElementById('up-source').value.trim(),
      country: _tags.country.join(', '),
      date:    document.getElementById('up-date').value,
      chunks:  data.chunks_added
    });
    clearUploadForm();
  })
  .catch(err => {
    btn.disabled = false;
    upStatus('Error: ' + err.message, 'error');
  });
  return false;
}

function upAddHistory(item) {
  uploadHistory.unshift(item);
  const container = document.getElementById('up-history');
  container.style.display = 'block';
  const tbody = document.getElementById('up-history-tbody');
  tbody.innerHTML = uploadHistory.map(h => `<tr>
    <td><strong>${escHtml(h.tr_id)}</strong></td>
    <td>${escHtml(h.title)}</td>
    <td>${escHtml(h.source)}</td>
    <td>${escHtml(h.country)}</td>
    <td>${h.date}</td>
    <td>${h.chunks}</td>
  </tr>`).join('');
}

// ═════════════════════════════════════════════════════════════════════════
// DOM INIT
// ═════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  // Agent DOM refs
  chatInput = document.getElementById('chat-input');
  sendBtn   = document.getElementById('send-btn');
  chatDiv   = document.getElementById('chat-messages');
  busyDot   = document.getElementById('busy-dot');

  // Agent keyboard
  chatInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 130) + 'px';
  });
  chatInput.focus();

  // SITREP event listeners
  const btnToggle = document.getElementById('btn-toggle-form');
  if (btnToggle) btnToggle.addEventListener('click', () => {
    document.getElementById('run-form').classList.toggle('hidden');
  });

  const btnRun = document.getElementById('btn-run');
  if (btnRun) btnRun.addEventListener('click', runPipeline);

  ['inp-country', 'inp-event', 'inp-themes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') runPipeline(); });
  });

  // SITREP citation modal close
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

  // Init SITREP steps grid
  buildStepsGrid();
  sitrepStepStates = new Array(STEPS.length).fill('waiting');
  showSitrepView('welcome');

  // Init tab state — hide reset button on non-agent tabs
  switchTab('agent');
  loadChatList();

  // Ingest tag input: Enter key support
  ['country', 'theme'].forEach(field => {
    const inp = document.getElementById(`up-${field}-input`);
    if (!inp) return;
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); tagAdd(field); }
    });
  });

  // Ingest: keyboard shortcut on search filters
  ['mq-country','mq-query'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') mqSearch(); });
  });
});
