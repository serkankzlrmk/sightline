// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for ReliefAgent Data Platform
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

// Upload modal state
const _tags = { country: [], theme: [] };
let sitrepStepStates   = [];
let sitrepActiveJobId  = null;
let sitrepActiveFile   = null;

// ── DOM references (populated on DOMContentLoaded) ─────────────────────────
let chatInput, sendBtn, chatDiv, busyDot;

// ── API wrapper with Bearer token ────────────────────────────────────────────
function api(url, opts = {}) {
  if (!opts.headers) opts.headers = {};
  // Merge existing headers if provided (keep Content-Type etc)
  const tok = typeof getIdToken === 'function' ? getIdToken() : '';
  if (tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  return fetch(url, opts);
}

// ═══════════════════════════════════════════════════════════════════════════
// SHARED HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function toast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  const icons = { success: '\u2713', error: '\u2717', warning: '\u26A0', info: '\u2139' };
  el.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span>${esc(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastOut .3s ease-in forwards';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function sanitizeHtml(html) {
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  // Remove dangerous elements
  const dangerous = tmp.querySelectorAll('script, iframe, object, embed, form, svg, math, style, link, meta, base');
  dangerous.forEach(el => el.remove());
  // Remove dangerous attributes (on* event handlers, javascript: URLs)
  const all = tmp.querySelectorAll('*');
  all.forEach(el => {
    const attrs = Array.from(el.attributes);
    attrs.forEach(attr => {
      if (/^on/i.test(attr.name) || attr.value.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attr.name);
      }
    });
  });
  return tmp.innerHTML;
}
// alias for SITREP code
const escHtml = esc;

// LaTeX notation → Unicode cleanup (runs before markdown parse)
const _latexMap = {
  '\\rightarrow':  '→', '\\leftarrow':   '←', '\\leftrightarrow': '↔',
  '\\Rightarrow':  '⇒', '\\Leftarrow':   '⇐', '\\Leftrightarrow': '⇔',
  '\\uparrow':     '↑', '\\downarrow':   '↓', '\\updownarrow': '↕',
  '\\Uparrow':     '⇑', '\\Downarrow':   '⇓',
  '\\geq':         '≥', '\\leq':         '≤', '\\neq':  '≠',
  '\\approx':      '≈', '\\pm':          '±', '\\times': '×',
  '\\div':         '÷', '\\infty':       '∞', '\\sum':  '∑',
  '\\prod':        '∏', '\\sqrt':        '√', '\\alpha': 'α',
  '\\beta':        'β', '\\gamma':       'γ', '\\delta': 'δ',
  '\\lambda':      'λ', '\\mu':          'μ', '\\pi':    'π',
  '\\sigma':       'σ', '\\omega':       'ω', '\\theta': 'θ',
  '\\cdot':        '·', '\\dots':        '…', '\\ldots': '…',
  '\\degree':      '°', '\\checkmark':   '✓', '\\star':  '★',
  '\\triangle':    '△', '\\bullet':      '•', '\\circ':  '○',
  '\\sim':         '∼', '\\cong':        '≅', '\\propto': '∝',
  '\\in':          '∈', '\\notin':       '∉', '\\subset': '⊂',
  '\\supset':      '⊃', '\\cup':         '∪', '\\cap':   '∩',
  '\\forall':      '∀', '\\exists':      '∃', '\\nabla':  '∇',
  '\\partial':     '∂', '\\emptyset':    '∅',
};
function cleanLatex(text) {
  // First: expand $...$ blocks (may contain multiple commands + text)
  text = text.replace(/\$([^$]+)\$/g, (_, inner) =>
    inner.replace(/\\([a-zA-Z]+)/g, (m, cmd) =>
      _latexMap['\\' + cmd] || cmd
    )
  );
  // Then: standalone \cmd not inside $...$
  text = text.replace(/\\([a-zA-Z]+)/g, (m, cmd) =>
    _latexMap['\\' + cmd] || m
  );
  return text;
}

// Configure marked to open links in new tab
const _markedRenderer = new marked.Renderer();
_markedRenderer.link = function(href, title, text) {
  // marked v5+ passes an object; v4 passes positional args
  if (typeof href === 'object') { title = href.title; text = href.text; href = href.href; }
  const t = title ? ` title="${esc(title)}"` : '';
  return `<a href="${esc(href)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`;
};

function md(text) {
  try   { return marked.parse(cleanLatex(text), { breaks: true, gfm: true, renderer: _markedRenderer }); }
  catch { return esc(text).replace(/\n/g, '<br>'); }
}

// ── Tab switching ────────────────────────────────────────────────────────────
function switchTab(name) {
  currentTab = name;
  const allTabs = ['db', 'agent', 'sitrep', 'admin'];
  allTabs.forEach(t => {
    const panel = document.getElementById('panel-' + t);
    const tab = document.getElementById('tab-' + t);
    if (panel) panel.classList.toggle('active', t === name);
    if (tab) tab.classList.toggle('active', t === name);
  });
  // Show/hide agent reset button
  const resetBtn = document.getElementById('agent-reset-btn');
  if (resetBtn) resetBtn.style.display = (name === 'agent') ? '' : 'none';

  if (name === 'db') reloadReports();
  if (name === 'sitrep') { loadSitrepReportsList(); loadThemePills(); }
  if (name === 'admin') loadAdminUsers();
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 2 — AGENT CHAT (multi-chat)
// ═══════════════════════════════════════════════════════════════════════════

const QUICK_PROMPTS = [
  { label: "Sudan Situation", text: "What is the current humanitarian situation in Sudan?" },
  { label: "Recent Reports", text: "Fetch and download the most recent health reports about Ukraine" },
  { label: "Food Security", text: "Summarize the latest food security reports for East Africa" },
  { label: "Displacement", text: "What are the main displacement trends in the Middle East region?" },
  { label: "Earthquake Response", text: "Show me situation reports about earthquake response efforts" },
];

const WELCOME_HTML = `<div class="chat-center">
  <div class="msg assistant">
    <div class="msg-label">AgenTRC</div>
    <div class="msg-body">
      Hello! I'm connected to the ReliefAgent Data Platform.<br><br>
      What I can do:
      <ul>
        <li>Search reports by country, theme, or source</li>
        <li>Download reports and save them to the local database</li>
        <li>Run semantic queries and summaries over downloaded reports</li>
      </ul>
    </div>
  </div>
  <div class="quick-prompts">
    <div class="quick-prompts-title">Try asking:</div>
    ${QUICK_PROMPTS.map(p => `<button class="quick-prompt-btn" onclick="sendQuickPrompt('${p.text.replace(/'/g, "\\'")}')">${p.label}</button>`).join('')}
  </div>
</div>`;

function addMsg(role, html) {
  // Ensure chat-center container exists inside chat-messages
  let center = chatDiv.querySelector('.chat-center');
  if (!center) {
    center = document.createElement('div');
    center.className = 'chat-center';
    chatDiv.appendChild(center);
  }
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  if (role === 'user') {
    wrap.innerHTML = `<div class="msg-body">${html}</div>`;
  } else {
    wrap.innerHTML = `
      <div class="msg-label">AgenTRC</div>
      <div class="msg-body">${html}</div>`;
  }
  center.appendChild(wrap);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return wrap.querySelector('.msg-body');
}

function addToolInd(name) {
  let center = chatDiv.querySelector('.chat-center');
  if (!center) {
    center = document.createElement('div');
    center.className = 'chat-center';
    chatDiv.appendChild(center);
  }
  const el = document.createElement('div');
  el.className = 'tool-ind';
  el.innerHTML = `<div class="spin"></div><span><strong>${esc(name)}</strong> running...</span>`;
  center.appendChild(el);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return el;
}

function clearToolInds() {
  chatDiv.querySelectorAll('.tool-ind').forEach(e => e.remove());
}

// ── Sidebar toggle ───────────────────
function toggleChatSidebar() {
  const sb = document.getElementById('chat-sidebar');
  const ov = document.getElementById('chat-sidebar-overlay');
  const open = sb.classList.toggle('open');
  ov.classList.toggle('open', open);
}

function sendQuickPrompt(text) {
  chatInput.value = text;
  sendMessage();
}

async function sendMessage() {
  if (isStreaming) return;
  // Block sending when rate limit is exhausted
  const rl = window.__rateLimit;
  const role = window.__userRole || "free";
  if (rl && rl.remaining <= 0 && role !== "admin") {
    toast('Daily message limit reached. Upgrade to Premium for more access — contact serkankizilirmaak@gmail.com', 'warning', 5000);
    return;
  }
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  chatInput.style.height = 'auto';
  addMsg('user', esc(text));

  isStreaming = true;
  sendBtn.disabled    = true;
  sendBtn.innerHTML   = '<div class="spin" style="width:16px;height:16px;border-width:2px"></div>';
  busyDot.classList.add('visible');

  currentAiEl   = addMsg('assistant',
    '<div class="typing-dots"><span></span><span></span><span></span></div>');
  currentAiText = '';

  try {
    const resp = await api('/api/agent/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text }),
    });

    if (resp.status === 429) {
      try {
        const errData = await resp.json();
        if (errData.remaining === 0) {
          currentAiEl.innerHTML = `<div class="rate-limit-msg"><div class="rate-limit-msg-title">Daily message limit reached (${errData.used}/${errData.limit})</div><div class="rate-limit-msg-body">Upgrade to Premium for unlimited access.</div><div class="rate-limit-msg-contact">Contact: <a href="mailto:serkankizilirmaak@gmail.com">serkankizilirmaak@gmail.com</a></div></div>`;
          toast(`Daily limit reached: ${errData.used}/${errData.limit} messages used`, 'error');
          updateChatRateUI(errData);
        } else {
          currentAiEl.innerHTML = '<span style="color:#d97706">Agent is busy, please wait.</span>';
          toast('Agent is busy, please try again in a moment', 'warning');
        }
      } catch {
        currentAiEl.innerHTML = '<span style="color:#d97706">Agent is busy, please wait.</span>';
      }
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
          currentAiEl.innerHTML = `<span style="color:#dc2626">Error: ${esc(evt.text)}</span>`;
          clearToolInds();
        } else if (evt.type === 'done') {
          clearToolInds();
          if (!currentAiText) currentAiEl.innerHTML = '<span style="color:#94a3b8">—</span>';
          if (typeof checkAdminStatus === 'function') checkAdminStatus();
        }
      }
    }
  } catch (err) {
    if (currentAiEl) {
      currentAiEl.innerHTML = `<span style="color:#dc2626">Connection error: ${esc(err.message)}</span>`;
    }
    clearToolInds();
  } finally {
    isStreaming          = false;
    sendBtn.disabled     = false;
    sendBtn.innerHTML    = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 2L11 13"/><path d="M22 2L15 22 11 13 2 9l20-7z"/></svg>';
    busyDot.classList.remove('visible');
    currentAiEl          = null;
    chatDiv.scrollTop    = chatDiv.scrollHeight;
    // Only update sidebar — do NOT re-render messages (causes layout shift)
    loadChatSidebar();
    // Refresh chat list after delay to pick up auto-generated title (full reload)
    setTimeout(() => loadChatList(), 3000);
    refreshChatRateHint();
  }
}

function updateChatRateUI(rateData) {
  if (!rateData) return;
  window.__rateLimit = rateData;
  if (typeof updateRateLimitUI === 'function') updateRateLimitUI();
  refreshChatRateHint();
}

function refreshChatRateHint() {
  const rl = window.__rateLimit;
  const hint = document.getElementById('chat-rate-hint');
  const role = window.__userRole || "free";
  if (!hint) return;
  if (role === "admin" || !rl) { hint.innerHTML = ''; chatInput.disabled = false; chatInput.placeholder = 'Message ReliefAgent...'; return; }
  const { remaining, limit, used } = rl;
  if (remaining <= 0) {
    hint.innerHTML = `Daily limit reached (${used}/${limit}) — <span class="rate-upgrade">Upgrade to Premium for more access. Contact <a href="mailto:serkankizilirmaak@gmail.com">serkankizilirmaak@gmail.com</a></span>`;
    hint.className = 'chat-rate-hint exhausted';
    chatInput.disabled = true;
    chatInput.placeholder = 'Daily limit reached';
  } else if (remaining <= 3) {
    hint.innerHTML = `${remaining}/${limit} messages remaining today`;
    hint.className = 'chat-rate-hint low';
    chatInput.disabled = false;
    chatInput.placeholder = 'Message ReliefAgent...';
  } else {
    hint.innerHTML = `${remaining}/${limit} messages remaining today`;
    hint.className = 'chat-rate-hint';
    chatInput.disabled = false;
    chatInput.placeholder = 'Message ReliefAgent...';
  }
}

async function resetChat() {
  if (!confirm('Clear chat history?')) return;
  await api('/api/agent/chat/reset', { method: 'POST' });
  chatDiv.innerHTML = WELCOME_HTML;
  currentAiText = '';
  loadChatList();
}

// ── Multi-chat management ────────────────────────────────────────────────

async function loadChatSidebar() {
  // Only update the sidebar chat list — do NOT re-render messages
  try {
    const r = await api('/api/agent/chats');
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
          <button class="chat-item-btn" onclick="event.stopPropagation(); renameChat('${c.id}', this)" title="Rename">R</button>
          <button class="chat-item-btn delete" onclick="event.stopPropagation(); confirmDeleteChat('${c.id}', this)" title="Delete">X</button>
        </span>`;
      item.addEventListener('click', () => selectChat(c.id));
      list.appendChild(item);
    }
  } catch { /* ignore */ }
}

async function loadChatList() {
  // Ensure admin status is checked before loading
  if (typeof checkAdminStatus === 'function' && typeof getIdToken === 'function' && getIdToken()) {
    await checkAdminStatus();
  }
  if (typeof updateVisibility === 'function') updateVisibility();
  try {
    const r = await api('/api/agent/chats');
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
          <button class="chat-item-btn" onclick="event.stopPropagation(); renameChat('${c.id}', this)" title="Rename">R</button>
          <button class="chat-item-btn delete" onclick="event.stopPropagation(); confirmDeleteChat('${c.id}', this)" title="Delete">X</button>
        </span>`;
      item.addEventListener('click', () => selectChat(c.id));
      list.appendChild(item);
    }
    // If there's an active chat, load its messages
    if (d.active) {
      try {
        const mr = await api(`/api/agent/chats/${d.active}/messages`);
        const msgData = await mr.json();
        if (msgData.messages && msgData.messages.length > 0) {
          chatDiv.innerHTML = '';
          const center = document.createElement('div');
          center.className = 'chat-center';
          chatDiv.appendChild(center);
          for (const m of msgData.messages) {
            if (m.role === 'user') {
              addMsg('user', esc(m.content));
            } else {
              addMsg('assistant', md(m.content));
            }
          }
          currentAiText = '';
        } else {
          chatDiv.innerHTML = WELCOME_HTML;
          currentAiText = '';
        }
      } catch { chatDiv.innerHTML = WELCOME_HTML; currentAiText = ''; }
    } else {
      chatDiv.innerHTML = WELCOME_HTML;
      currentAiText = '';
    }
  } catch { /* ignore */ }
}

async function newChat() {
  if (isStreaming) return;
  try {
    await api('/api/agent/chats/new', { method: 'POST' });
    chatDiv.innerHTML = WELCOME_HTML;
    currentAiText = '';
    await loadChatList();
  } catch { /* ignore */ }
}

async function selectChat(chatId) {
  if (isStreaming) return;
  try {
    await api(`/api/agent/chats/${chatId}/select`, { method: 'POST' });
    // Load and render saved messages
    const r = await api(`/api/agent/chats/${chatId}/messages`);
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
    // Close sidebar after selecting
    const sb = document.getElementById('chat-sidebar');
    const ov = document.getElementById('chat-sidebar-overlay');
    if (sb) sb.classList.remove('open');
    if (ov) ov.classList.remove('open');
  } catch { /* ignore */ }
}

function renameChat(chatId, btn) {
  const item = btn.closest('.chat-item');
  if (!item || item.querySelector('.rename-confirm')) return;
  const current = item.querySelector('.chat-item-title')?.textContent || '';
  const overlay = document.createElement('div');
  overlay.className = 'rename-confirm';
  overlay.innerHTML = `
    <input class="rc-input" type="text" value="${esc(current)}" maxlength="120" />
    <button class="rc-ok">OK</button>
    <button class="rc-cancel">X</button>`;
  overlay.addEventListener('click', e => e.stopPropagation());
  item.appendChild(overlay);
  const inp = overlay.querySelector('.rc-input');
  inp.focus();
  inp.select();
  const doRename = async () => {
    const title = inp.value.trim();
    if (!title || title === current) { overlay.remove(); return; }
    try {
      await api(`/api/agent/chats/${chatId}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      });
      await loadChatList();
    } catch { overlay.remove(); }
  };
  overlay.querySelector('.rc-ok').addEventListener('click', doRename);
  overlay.querySelector('.rc-cancel').addEventListener('click', () => overlay.remove());
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') doRename();
    if (e.key === 'Escape') overlay.remove();
  });
}

function confirmDeleteChat(chatId, btn) {
  const item = btn.closest('.chat-item');
  if (!item || item.querySelector('.delete-confirm')) return;
  const overlay = document.createElement('div');
  overlay.className = 'delete-confirm';
  overlay.innerHTML = `
    <span class="dc-label">Delete this chat?</span>
    <button class="dc-yes" onclick="event.stopPropagation(); executeDeleteChat('${chatId}', this)">Delete</button>
    <button class="dc-no" onclick="event.stopPropagation(); this.closest('.delete-confirm').remove()">Cancel</button>`;
  overlay.addEventListener('click', e => e.stopPropagation());
  item.appendChild(overlay);
}

async function executeDeleteChat(chatId, btn) {
  const item = btn.closest('.chat-item');
  if (item) {
    item.style.transition = 'all .3s ease';
    item.style.transform = 'translateX(-100%)';
    item.style.opacity = '0';
  }
  try {
    const r = await api(`/api/agent/chats/${chatId}`, { method: 'DELETE' });
    const d = await r.json();
    if (d.ok && d.active) {
      const mr = await api(`/api/agent/chats/${d.active}/messages`);
      const msgs = await mr.json();
      chatDiv.innerHTML = '';
      if (msgs.messages && msgs.messages.length > 0) {
        for (const m of msgs.messages) {
          if (m.role === 'user') addMsg('user', esc(m.content));
          else addMsg('assistant', md(m.content));
        }
      } else {
        chatDiv.innerHTML = WELCOME_HTML;
      }
      currentAiText = '';
    }
    setTimeout(() => loadChatList(), 300);
  } catch {
    if (item) { item.style.transform = ''; item.style.opacity = ''; }
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 1 — DATABASE (DB Reports Browser)
// ═══════════════════════════════════════════════════════════════════════════

async function reloadReports() {
  await Promise.all([loadStats(), loadFilterOptions()]);
  await applyFilters();
}

async function loadStats() {
  try {
    const r = await api('/api/db/stats');
    const d = await r.json();
    document.getElementById('s-reports').textContent = (d.report_count || 0).toLocaleString();
    document.getElementById('s-chunks').textContent  = (d.chunk_count  || 0).toLocaleString();
  } catch { /* ignore */ }
}

async function loadFilterOptions() {
  try {
    const [cRes, sRes] = await Promise.all([api('/api/db/countries'), api('/api/db/sources')]);
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
    const res  = await api('/api/db/reports?' + p);
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
    body.innerHTML = '<tr><td colspan="8" class="empty"><div class="icon"></div>No results found</td></tr>';
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
    const res = await api('/api/db/reports/' + id);
    const r   = await res.json();
    currentReportTitle = r.title || '';

    document.getElementById('m-title').textContent     = r.title || '—';
    document.getElementById('m-id').textContent        = r.report_id;
    document.getElementById('m-date').textContent      = r.date || '—';
    document.getElementById('m-countries').textContent = (r.all_countries || []).join(', ') || '—';
    document.getElementById('m-source').textContent    = r.source || '—';
    document.getElementById('m-format').textContent    = r.format_type || '—';
    document.getElementById('m-pdf').textContent       = r.has_pdf ? `Available (${r.pdf_pages} pages)` : 'None';
    document.getElementById('m-chunks').textContent    = r.has_content ? `Available (${r.total_chunks} chunks)` : 'None';

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
  { id: 0,  name: "Chroma Connection",   icon: "1" },
  { id: 1,  name: "Chunk Loading",       icon: "2" },
  { id: 2,  name: "Clustering",          icon: "3" },
  { id: 3,  name: "Question Generation", icon: "4" },
  { id: 4,  name: "Question Filtering",  icon: "5" },
  { id: 5,  name: "RAG Answering",       icon: "6" },
  { id: 6,  name: "Citation Validation", icon: "7" },
  { id: 7,  name: "Cluster Summary",     icon: "8" },
  { id: 8,  name: "Exec + Narrative",    icon: "9" },
  { id: 9,  name: "Report Assembly",     icon: "10" },
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
  const iconMap = { waiting: STEPS[idx].icon, active: '○', cached: '⚡', done: '✓', error: '✗' };
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
  const tok = typeof getIdToken === 'function' ? getIdToken() : '';
  const es  = new EventSource(`/api/sitrep/stream/${jobId}${tok ? '?token=' + encodeURIComponent(tok) : ''}`);
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

  // Check chunk preview warning
  const cpEl = document.getElementById('chunk-preview');
  if (cpEl && cpEl.classList.contains('err')) {
    if (!confirm('No matching data found for the selected filters. Run anyway?')) return;
  }

  // Collect selected theme pills
  const themes = [];
  document.querySelectorAll('#theme-pills .theme-pill.selected').forEach(el => {
    themes.push(el.dataset.theme);
  });

  const dateFrom  = document.getElementById('inp-date-from').value || '';
  const dateTo    = document.getElementById('inp-date-to').value || '';
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
  if (spinner) { spinner.className = 'spin'; spinner.textContent = ''; }
  const titleEl = document.getElementById('pipeline-title-text');
  if (titleEl) titleEl.textContent = `${country} / ${event || country}  —  running…`;

  showSitrepView('pipeline');
  deactivateSitrepItems();

  try {
    const resp = await api('/api/sitrep/run', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ country, event, themes, skip_cache: skipCache, date_from: dateFrom, date_to: dateTo }),
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
    const resp  = await api('/api/sitrep/reports');
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
    const resp   = await api(`/api/sitrep/report?file=${encodeURIComponent(filename)}`);
    const report = await resp.json();
    if (report.error) throw new Error(report.error);
    renderSitrepReport(report, filename);
  } catch (err) {
    document.getElementById('report-content').innerHTML =
      `<div style="color:#ef4444;padding:20px">Could not load report: ${escHtml(err.message)}</div>`;
  }
}

function renderSitrepReport(report, filename) {
  _currentReportData = report;
  _currentReportFile = filename;

  const raw     = report.file_name || filename.replace(/_report\.json$/, '');
  const parts   = raw.replace(/_/g, ' ').split(/\s+/);
  const country = parts[0];
  const evt     = parts.slice(1).join(' ');

  const hasNarrative = !!(report.narrative_html && report.narrative_html.trim());

  let html = `
    <div class="report-header">
      <div>
        <div class="report-title">${escHtml(country)}</div>
        <div class="report-subtitle">${escHtml(evt)}</div>
      </div>
      <div class="report-actions">
        <button class="btn-sm btn-discuss-agent" onclick="discussSitrepWithAgent()">Discuss with AgenTRC</button>
      </div>
    </div>`;

  // Filters meta (themes, date range)
  const rThemes = report.themes || [];
  const rDateFrom = report.date_from || '';
  const rDateTo   = report.date_to   || '';
  if (rThemes.length || rDateFrom || rDateTo) {
    let metaParts = [];
    if (rThemes.length) metaParts.push(`<span class="report-meta-label">Themes:</span> ${rThemes.map(t => `<span class="report-meta-pill">${escHtml(t)}</span>`).join(' ')}`);
    if (rDateFrom || rDateTo) metaParts.push(`<span class="report-meta-label">Date Range:</span> ${escHtml(rDateFrom || '…')} → ${escHtml(rDateTo || '…')}`);
    html += `<div class="report-meta-bar">${metaParts.join('<span class="report-meta-sep">|</span>')}</div>`;
  }

  // View toggle (only if narrative exists)
  if (hasNarrative) {
    html += `
      <div class="report-view-toggle">
        <button class="report-view-btn active" data-mode="narrative" onclick="switchReportView('narrative')">Narrative Report</button>
        <button class="report-view-btn" data-mode="qa" onclick="switchReportView('qa')">Q&A View</button>
      </div>`;
  }

  // ── Narrative view ──
  if (hasNarrative) {
    const narrSources = report.narrative_sources || {};
    html += `<div id="report-narrative-view" class="report-view-section">`;
    html += `<div class="narrative-body">${renderNarrativeCitations(md(sanitizeHtml(report.narrative_html)), narrSources)}</div>`;
    html += buildNarrativeSourcesList(narrSources);
    html += `</div>`;
  }

  // ── Q&A view ──
  html += `<div id="report-qa-view" class="report-view-section ${hasNarrative ? 'hidden' : ''}">`;

  if (report.summary) {
    const summaryCtx = report.summary_contexts || {};
    html += `
      <div class="sitrep-section-card">
        <div class="sitrep-section-header" onclick="toggleCard(this)">
          <span>Executive Summary</span>
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

  html += `</div>`; // close report-qa-view

  document.getElementById('report-content').innerHTML = html;
}

// ── Narrative citation helpers ───────────────────────────────────────────────

function renderNarrativeCitations(htmlText, narrativeSources) {
  // Replace [N] in already-rendered HTML with clickable citation spans
  return htmlText.replace(/\[(\d+)\]/g, (match, num) => {
    const src = narrativeSources && (narrativeSources[num] || narrativeSources[String(num)]);
    if (!src) return `<span class="citation" style="background:#94a3b8">[${num}]</span>`;
    const ctxTitle = encodeURIComponent(src.title || '');
    const ctxUrl   = encodeURIComponent(src.url || '');
    const ctxDate  = encodeURIComponent(src.date || '');
    return `<span class="citation" onclick="showCitation(${num},'${ctxDate}','${ctxTitle}','${ctxUrl}')">[${num}]</span>`;
  });
}

function buildNarrativeSourcesList(narrativeSources) {
  const entries = Object.entries(narrativeSources)
    .filter(([, src]) => src && (src.url || src.title))
    .sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
  if (!entries.length) return '';
  let items = '';
  entries.forEach(([num, src]) => {
    let domain = '';
    try { domain = new URL(src.url || '').hostname.replace(/^www\./, ''); } catch {}
    const href  = src.url ? escHtml(src.url) : '#';
    const noUrl = src.url ? '' : 'style="opacity:0.6;pointer-events:none"';
    items += `
      <a class="source-item" href="${href}" target="_blank" rel="noopener noreferrer" ${noUrl}>
        <span class="source-item-num">${escHtml(num)}</span>
        <span class="source-item-body">
          <div class="source-item-title">${escHtml(src.title || '—')}</div>
          ${src.date ? `<div class="source-item-domain">${escHtml(src.date)}</div>` : ''}
          ${domain ? `<div class="source-item-domain">${escHtml(domain)}</div>` : ''}
        </span>
        <span class="source-item-icon">↗</span>
      </a>`;
  });
  return `<div class="sources-section"><div class="sources-title">Sources (${entries.length})</div>${items}</div>`;
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
  return `<div class="sources-section"><div class="sources-title">Sources (${entries.length})</div>${items}</div>`;
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
  return `<div class="sources-section"><div class="sources-title">Sources (${valid.length})</div>${items}</div>`;
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

// ── Theme pills loader ──────────────────────────────────────────────────────
async function loadThemePills() {
  const container = document.getElementById('theme-pills');
  if (!container) return;
  try {
    const resp = await api('/api/sitrep/themes');
    const themes = await resp.json();
    if (!themes.length || themes.error) {
      container.innerHTML = '<span class="theme-pills-empty">No themes in DB</span>';
      return;
    }
    container.innerHTML = '';
    themes.forEach(t => {
      const pill = document.createElement('span');
      pill.className = 'theme-pill';
      pill.dataset.theme = t;
      pill.textContent = t;
      pill.addEventListener('click', () => { pill.classList.toggle('selected'); scheduleChunkPreview(); });
      container.appendChild(pill);
    });
  } catch {
    container.innerHTML = '<span class="theme-pills-empty">Could not load themes</span>';
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

  const themes = [];
  document.querySelectorAll('#theme-pills .theme-pill.selected').forEach(p => {
    themes.push(p.dataset.theme);
  });
  const dateFrom = document.getElementById('inp-date-from')?.value || '';
  const dateTo   = document.getElementById('inp-date-to')?.value || '';

  try {
    const resp = await api('/api/sitrep/chunk-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country, themes, date_from: dateFrom, date_to: dateTo }),
    });
    const data = await resp.json();
    if (data.error) { el.classList.add('hidden'); return; }

    el.classList.remove('hidden', 'ok', 'warn', 'err');
    if (data.count === 0) {
      el.classList.add('err');
      const filterParts = [];
      if (themes.length) filterParts.push(`themes: ${themes.join(', ')}`);
      if (dateFrom) filterParts.push(`from: ${dateFrom}`);
      if (dateTo)   filterParts.push(`to: ${dateTo}`);
      el.innerHTML = `<div class="cp-count">⚠ No matching data found</div>` +
        (filterParts.length ? `<div class="cp-themes">Filters: ${escHtml(filterParts.join(' · '))}. Try adjusting your selection.</div>` : '');
    } else if (data.count < 20) {
      el.classList.add('warn');
      el.innerHTML = `<div class="cp-count">⚠ Only ${data.count} chunks match — results may be limited</div>` +
        (data.themes_found.length ? `<div class="cp-themes">Topics: ${data.themes_found.map(escHtml).join(', ')}</div>` : '');
    } else {
      el.classList.add('ok');
      el.innerHTML = `<div class="cp-count">✓ ${data.count} chunks available</div>` +
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

  const qaView   = document.getElementById('report-qa-view');
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
  if (!sitrepActiveFile) return;

  // Fetch the full report JSON
  let report;
  try {
    const resp = await api(`/api/sitrep/report?file=${encodeURIComponent(sitrepActiveFile)}`);
    report = await resp.json();
    if (report.error) throw new Error(report.error);
  } catch (err) {
    alert('Could not load SITREP report: ' + err.message);
    return;
  }

  // Build a comprehensive context string
  const raw = report.file_name || sitrepActiveFile.replace(/_report\.json$/, '');
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
        else addMsg('assistant', md(m.content));
      }
    }
    currentAiText = '';
    await loadChatList();

    // Focus input
    const inp = document.getElementById('chat-input');
    if (inp) inp.focus();
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════

// ═════════════════════════════════════════════════════════════════════════
// PDF UPLOAD MODAL (admin-only, on Database tab)
// ═════════════════════════════════════════════════════════════════════════

function showUploadModal() {
  document.getElementById('upload-modal').classList.add('open');
}
function hideUploadModal() {
  document.getElementById('upload-modal').classList.remove('open');
}

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

function clearUploadForm() {
  document.getElementById('upload-form').reset();
  tagReset();
}

function submitUpload(e) {
  e.preventDefault();
  if (!_tags.country.length) {
    toast('Please add at least one country tag.', 'warning');
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
  if (!pdfFile) { toast('Please select a PDF file.', 'warning'); return false; }
  fd.append('pdf', pdfFile);

  const btn = document.getElementById('up-submit-btn');
  btn.disabled = true;
  toast('Uploading and ingesting…', 'info');

  api('/api/ingest/upload', { method: 'POST', body: fd })
  .then(r => r.json())
  .then(data => {
    btn.disabled = false;
    if (data.error) { toast(data.error, 'error'); return; }
    toast(`✓ Ingested as ${data.tr_id} — ${data.pdf_pages} page(s), ${data.chunks_added} chunks added.`, 'success', 5000);
    clearUploadForm();
    hideUploadModal();
    if (currentTab === 'db') reloadReports();
  })
  .catch(err => {
    btn.disabled = false;
    toast('Error: ' + err.message, 'error');
  });
  return false;
}

// Show/hide upload button based on admin status
function updateUploadBtnVisibility() {
  const btn = document.getElementById('btn-upload-pdf');
  if (btn) btn.style.display = (window.__userRole === 'admin') ? '' : 'none';
}

// ═════════════════════════════════════════════════════════════════════════
// ADMIN PANEL — User role management
// ═════════════════════════════════════════════════════════════════════════

async function loadAdminUsers() {
  const tbody = document.getElementById('admin-user-tbody');
  if (!tbody) return;
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) { tbody.innerHTML = '<tr><td colspan="4">Not authenticated</td></tr>'; return; }
  try {
    const resp = await fetch('/api/admin/users', { headers: { 'Authorization': 'Bearer ' + tok } });
    if (!resp.ok) { tbody.innerHTML = '<tr><td colspan="4">Failed to load users</td></tr>'; return; }
    const data = await resp.json();
    const users = data.users || [];
    if (!users.length) { tbody.innerHTML = '<tr><td colspan="4">No users found</td></tr>'; return; }
    tbody.innerHTML = users.map(u => {
      const roleClass = u.role === 'admin' ? 'role-admin' : u.role === 'premium' ? 'role-premium' : 'role-free';
      return `<tr>
        <td>${esc(u.email || u.uid)}</td>
        <td>${esc(u.displayName || '—')}</td>
        <td><span class="admin-role-badge ${roleClass}">${u.role}</span></td>
        <td class="admin-actions">
          ${u.role !== 'free' ? `<button class="btn btn-xs" onclick="setUserRole('${u.uid}','free')">Free</button>` : ''}
          ${u.role !== 'premium' ? `<button class="btn btn-xs btn-premium" onclick="setUserRole('${u.uid}','premium')">Premium</button>` : ''}
          ${u.role !== 'admin' ? `<button class="btn btn-xs btn-admin" onclick="setUserRole('${u.uid}','admin')">Admin</button>` : ''}
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="4">Error loading users</td></tr>';
  }
}

async function setUserRole(uid, role) {
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) return;
  if (!confirm(`Set role to "${role}" for user ${uid.substring(0, 8)}...?`)) return;
  try {
    const resp = await fetch(`/api/admin/users/${uid}/role`, {
      method: 'PUT',
      headers: { 'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    if (!resp.ok) { const err = await resp.json(); toast(err.error || 'Failed', 'error'); return; }
    toast(`Role set to ${role}`, 'success');
    loadAdminUsers();
  } catch (e) {
    toast('Failed to set role', 'error');
  }
}
window.loadAdminUsers = loadAdminUsers;
window.setUserRole = setUserRole;

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
    // Block input when rate limit is exhausted
    const rl = window.__rateLimit;
    const role = window.__userRole || 'free';
    if (rl && rl.remaining <= 0 && role !== 'admin') {
      e.preventDefault();
      toast('Daily message limit reached. Upgrade to Premium for more access — contact serkankizilirmaak@gmail.com', 'warning', 5000);
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

  // SITREP event listeners (non-auth, safe to init early)
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

  const countryEl = document.getElementById('inp-country');
  if (countryEl) {
    countryEl.addEventListener('change', () => fetchCountryDateRange(countryEl.value.trim()));
  }

  ['inp-date-from', 'inp-date-to'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', scheduleChunkPreview);
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

  // Init SITREP steps grid
  buildStepsGrid();
  sitrepStepStates = new Array(STEPS.length).fill('waiting');
  showSitrepView('welcome');

  // Ingest tag input: Enter key support
  ['country', 'theme'].forEach(field => {
    const inp = document.getElementById(`up-${field}-input`);
    if (!inp) return;
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); tagAdd(field); }
    });
  });

  ['mq-country','mq-query'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') mqSearch(); });
  });

  // Wait for auth before making auth-required API calls
  let _appInited = false;
  function initAppData() {
    if (_appInited) return;
    _appInited = true;
    const tok = window.getIdToken ? window.getIdToken() : '';
    if (!tok) return;
    switchTab('agent');
    loadChatList();
    updateVisibilityFromAuth();
  }

  function updateVisibilityFromAuth() {
    if (typeof window.updateVisibility === 'function') {
      window.updateVisibility();
    } else {
      const role = window.__userRole || 'free';
      const isPremium = role === 'premium' || role === 'admin';
      const sitrepRunForm = document.getElementById("btn-toggle-form");
      if (sitrepRunForm) sitrepRunForm.style.display = isPremium ? "" : "none";
    }
    updateUploadBtnVisibility();
  }

  if (window.__authReady) {
    initAppData();
  } else {
    window.addEventListener('auth-ready', initAppData, { once: true });
    setTimeout(() => {
      if (!_appInited && window.getIdToken && window.getIdToken()) {
        console.log('[app] auth-ready event missed, initializing with cached token');
        initAppData();
      }
    }, 3000);
  }
});
