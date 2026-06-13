// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for Sightline
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
    // Also strip href/src attributes with javascript: protocol
    ['href', 'src', 'action', 'formaction', 'xlink:href'].forEach(attrName => {
      const val = el.getAttribute(attrName);
      if (val && val.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attrName);
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
function toggleSidebarNav() {
  const nav = document.getElementById('sidebar-nav');
  if (nav) nav.classList.toggle('collapsed');
}

function switchTab(name) {
  currentTab = name;
  const allTabs = ['home', 'agent', 'sitrep', 'bulletin', 'db', 'admin'];
  const sidebar = document.getElementById('sidebar-nav');
  const main = document.querySelector('.main');
  const hamburger = document.getElementById('hamburger-btn');

  allTabs.forEach(t => {
    const panel = document.getElementById('panel-' + t);
    const tab = document.getElementById('tab-' + t);
    if (panel) panel.classList.toggle('active', t === name);
    if (tab) tab.classList.toggle('active', t === name);
  });

  // Home: hide sidebar, show hamburger
  if (name === 'home') {
    if (sidebar) sidebar.classList.add('hidden');
    if (main) main.style.marginLeft = '0';
    if (hamburger) hamburger.style.display = 'none';
    // Leaflet needs invalidateSize when container becomes visible
    setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 100);
  } else {
    if (sidebar) sidebar.classList.remove('hidden');
    if (sidebar && sidebar.classList.contains('collapsed')) {
      if (main) main.style.marginLeft = '72px';
    } else {
      if (main) main.style.marginLeft = '';
    }
    if (hamburger) hamburger.style.display = '';
    if (name === 'db') reloadReports();
    if (name === 'sitrep') { loadSitrepReportsList(); loadCountryDropdown(); }
    if (name === 'bulletin') loadBulletinList();
    if (name === 'admin') loadAdminUsers();
  }

  if (name === 'home') loadDashboard();
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 2 — AGENT CHAT (multi-chat)
// ═══════════════════════════════════════════════════════════════════════════

const QUICK_PROMPTS = [
  // Search & Discovery
  { label: "Latest Headlines", text: "What are the latest humanitarian headlines?", cat: "search" },
  { label: "Country Search", text: "Search for recent situation reports about Sudan", cat: "search" },
  { label: "Theme Filter", text: "Find health reports from WHO in the last month", cat: "search" },
  { label: "Disaster Tracker", text: "What ongoing disasters are there in Southeast Asia?", cat: "search" },
  // Knowledge Base
  { label: "Ask a Question", text: "What is the current food security situation in East Africa?", cat: "kb" },
  { label: "Summarize Topic", text: "Summarize displacement trends in the Middle East", cat: "kb" },
  // Ingest & Download
  { label: "Fetch Reports", text: "Find and download the latest Ukraine situation reports", cat: "ingest" },
  { label: "Paste a URL", text: "Fetch this report: https://reliefweb.int/report/sudan/humanitarian-snapshot", cat: "ingest" },
  // Deep Analysis
  { label: "Full Report", text: "Show me the full content of report 12345", cat: "analysis" },
  { label: "Convert to MD", text: "Convert report 12345 to markdown format", cat: "analysis" },
];

const WELCOME_HTML = `<div class="chat-center">
  <div class="msg assistant">
    <div class="msg-label">Sightline</div>
    <div class="msg-body">
      <div class="welcome-greeting">Welcome to Sightline</div>
      <div class="welcome-desc">Your AI-powered humanitarian data analyst. I search, analyze, and synthesize reports from ReliefWeb and your local knowledge base.</div>
      <div class="welcome-section">
        <div class="welcome-section-title">Search & Discover</div>
        <div class="welcome-section-desc">Search ReliefWeb's entire database by country, theme, organization, disaster type, or date range. Get the latest headlines or deep-dive into specific crises.</div>
      </div>
      <div class="welcome-section">
        <div class="welcome-section-title">Ask Questions</div>
        <div class="welcome-section-desc">Ask natural-language questions — I'll search the knowledge base and provide cited answers from downloaded reports. Every claim is linked to its source.</div>
      </div>
      <div class="welcome-section">
        <div class="welcome-section-title">Ingest & Save</div>
        <div class="welcome-section-desc">Found a useful report? I can fetch and save it to the knowledge base with one command. Paste a ReliefWeb URL or ask me to batch-download search results.</div>
      </div>
      <div class="welcome-section">
        <div class="welcome-section-title">More Features</div>
        <div class="welcome-section-desc">Switch to the <strong>Database</strong> tab to browse and filter all stored reports. Use the <strong>SITREP</strong> tab to generate automated situation reports with clustering and AI analysis.</div>
      </div>
    </div>
  </div>
  <div class="quick-prompts">
    <div class="quick-prompts-title">Try asking:</div>
    ${QUICK_PROMPTS.map(p => `<button class="quick-prompt-btn cat-${p.cat}" data-action="quick-prompt" data-text="${esc(p.text.replace(/"/g, '&quot;'))}">${p.label}</button>`).join('')}
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
      <div class="msg-label">Sightline</div>
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
  // Exit welcome mode on first message
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.remove('welcome-mode');
  // Block sending when rate limit is exhausted
  const rl = window.__rateLimit;
  const role = window.__userRole || "free";
  if (rl && rl.remaining <= 0 && role !== "admin") {
    // Show inline message instead of toast, input is already locked
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
  }
}

function updateChatRateUI(rateData) {
  if (!rateData) return;
  window.__rateLimit = rateData;
  if (typeof updateRateLimitUI === 'function') updateRateLimitUI();
  lockChatInput();
}

function lockChatInput() {
  const rl = window.__rateLimit;
  const role = window.__userRole || "free";
  if (role === "admin" || !rl || rl.remaining > 0) {
    chatInput.disabled = false;
    chatInput.placeholder = 'Message Sightline...';
    return;
  }
  // Rate limit exhausted — lock input
  chatInput.disabled = true;
  chatInput.placeholder = 'Daily limit reached';
}

async function resetChat() {
  if (!confirm('Clear chat history?')) return;
  await api('/api/agent/chat/reset', { method: 'POST' });
  chatDiv.innerHTML = WELCOME_HTML;
  currentAiText = '';
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.add('welcome-mode');
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
          <button class="chat-item-btn" data-action="rename-chat" data-chat-id="${esc(c.id)}" title="Rename">R</button>
          <button class="chat-item-btn delete" data-action="delete-chat" data-chat-id="${esc(c.id)}" title="Delete">X</button>
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
          <button class="chat-item-btn" data-action="rename-chat" data-chat-id="${esc(c.id)}" title="Rename">R</button>
          <button class="chat-item-btn delete" data-action="delete-chat" data-chat-id="${esc(c.id)}" title="Delete">X</button>
        </span>`;
      item.addEventListener('click', () => selectChat(c.id));
      list.appendChild(item);
    }
    // If there's an active chat, load its messages
    const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
    if (d.active) {
      try {
        const mr = await api(`/api/agent/chats/${d.active}/messages`);
        const msgData = await mr.json();
        if (msgData.messages && msgData.messages.length > 0) {
          if (chatMain) chatMain.classList.remove('welcome-mode');
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
          if (chatMain) chatMain.classList.add('welcome-mode');
          chatDiv.innerHTML = WELCOME_HTML;
          currentAiText = '';
        }
      } catch { chatDiv.innerHTML = WELCOME_HTML; currentAiText = ''; }
    } else {
      if (chatMain) chatMain.classList.add('welcome-mode');
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
    const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
    if (chatMain) chatMain.classList.add('welcome-mode');
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
    const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
    chatDiv.innerHTML = '';
    if (d.messages && d.messages.length > 0) {
      if (chatMain) chatMain.classList.remove('welcome-mode');
      for (const m of d.messages) {
        if (m.role === 'user') {
          addMsg('user', esc(m.content));
        } else {
          addMsg('assistant', md(m.content));
        }
      }
    } else {
      if (chatMain) chatMain.classList.add('welcome-mode');
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
    <button class="dc-yes" data-action="confirm-delete-chat" data-chat-id="${esc(chatId)}">Delete</button>
    <button class="dc-no" data-action="cancel-delete-chat">Cancel</button>`;
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
    th.classList.toggle('sorted', th.dataset.sort === key);
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

    return `<tr class="db-report-row" data-report-id="${r.report_id}">
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

function connectSSE(jobId, nonce) {
  sitrepActiveJobId = jobId;
  const es  = new EventSource(`/api/sitrep/stream/${jobId}?nonce=${encodeURIComponent(nonce || '')}`);
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
        appendLog('Tip: Check the log above for error details. You can re-run with "Skip cache" to restart from scratch.');
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
      body:    JSON.stringify({ country, event, skip_cache: skipCache, date_from: dateFrom, date_to: dateTo }),
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
    const resp  = await api('/api/sitrep/reports');
    const items = await resp.json();
    if (!items.length) {
      list.innerHTML = '<div class="empty-state">No reports yet.</div>';
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

      div.innerHTML = `<span>${escHtml(country)}</span>${evt ? `<span style="font-size:10px;color:var(--text-muted);margin-left:4px">${escHtml(evt)}</span>` : ''}`;
      div.addEventListener('click', () => openSitrepReport(item.filename, div));
      list.appendChild(div);
    });
  } catch {
    list.innerHTML = '<div class="empty-state">Could not connect to server.</div>';
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
  const rThemes = report.themes || [];
  const rDateFrom = report.date_from || '';
  const rDateTo   = report.date_to   || '';
  const clusters = report.clusters || [];
  const narrSources = hasNarrative ? (report.narrative_sources || {}) : {};
  const sourceCount = Object.entries(narrSources).filter(([k, v]) => !isNaN(Number(k)) && v && typeof v === 'object' && (v.url || v.title)).length;

  // ── Hero banner ──
  let html = `
    <div class="report-hero">
      <div class="report-hero-content">
        <div class="report-hero-badge">📋 SITREP</div>
        <h1 class="report-hero-title">${escHtml(country)}</h1>
        <div class="report-hero-subtitle">${escHtml(evt)}</div>
        <div class="report-hero-meta">
          ${(rDateFrom || rDateTo) ? `<span class="report-hero-date">📅 ${escHtml(rDateFrom || '…')} — ${escHtml(rDateTo || '…')}</span>` : ''}
          ${rThemes.length ? rThemes.map(t => `<span class="report-hero-theme">${escHtml(t)}</span>`).join('') : ''}
        </div>
      </div>
      <div class="report-hero-actions">
        <button class="btn-sm btn-discuss-agent" data-action="discuss-sitrep">💬 Discuss with Sightline</button>
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
        <button class="report-view-btn active" data-mode="narrative" data-action="switch-report-view">Narrative Report</button>
        <button class="report-view-btn" data-mode="qa" data-action="switch-report-view">Q&A View</button>
      </div>`;
  }

  // ── Narrative view ──
  if (hasNarrative) {
    let narrativeHtml = renderNarrativeCitations(md(sanitizeHtml(report.narrative_html)), narrSources);
    // Add id attributes to headings for TOC anchor links
    narrativeHtml = narrativeHtml.replace(/<h([1-3])([^>]*)>([\s\S]*?)<\/h[1-3]>/gi, (match, level, attrs, inner) => {
      const text = inner.replace(/<[^>]+>/g, '').trim();
      const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').substring(0, 60);
      return `<h${level} id="${esc(id)}"${attrs}>${inner}</h${level}>`;
    });
    const tocHtml = buildNarrativeToc(narrativeHtml);
    html += `<div id="report-narrative-view" class="report-view-section">`;
    html += `<div class="narrative-layout">`;
    if (tocHtml) html += `<nav class="narrative-toc"><div class="narrative-toc-title">Contents</div>${tocHtml}</nav>`;
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
        <div class="sitrep-section-header" data-action="toggle-card">
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

  if (!clusterList.length) {
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
    return `<span class="citation" data-action="show-citation" data-num="${num}" data-date="${ctxDate}" data-title="${ctxTitle}" data-url="${ctxUrl}">[${num}]</span>`;
  });
}

function buildNarrativeToc(html) {
  const headingRegex = /<h([1-3])[^>]*id=["']([^"']*)["'][^>]*>([\s\S]*?)<\/h[1-3]>/gi;
  const headings = [];
  let match;
  while ((match = headingRegex.exec(html)) !== null) {
    headings.push({ level: parseInt(match[1]), id: match[2], text: match[3].replace(/<[^>]+>/g, '').trim() });
  }
  if (headings.length < 2) return '';
  return headings.map(h => `<a href="#${esc(h.id)}" class="level-h${h.level}" onclick="event.preventDefault();document.getElementById('${esc(h.id)}')?.scrollIntoView({behavior:'smooth',block:'start'})">${escHtml(h.text.substring(0, 60))}${h.text.length > 60 ? '…' : ''}</a>`).join('\n');
}

function buildNarrativeSourcesList(narrativeSources) {
  // Filter out non-citation keys (cluster_titles, exec_summary_used)
  const entries = Object.entries(narrativeSources)
    .filter(([num, src]) => src && typeof src === 'object' && (src.url || src.title))
    .filter(([num]) => !isNaN(Number(num)))  // only numeric keys
    .sort((a, b) => parseInt(a[0]) - parseInt(b[0]));
  if (!entries.length) return '';
  let items = '';
  entries.forEach(([num, src]) => {
    let domain = '';
    try { domain = new URL(src.url || '').hostname.replace(/^www\./, ''); } catch {}
    const href  = src.url ? escHtml(src.url) : '#';
    const noUrl = src.url ? '' : 'style="opacity:0.6;pointer-events:none"';
    // Determine source type icon
    let icon = '📄';
    if (domain.includes('reliefweb')) icon = '🌐';
    else if (domain.includes('un')) icon = '🇺🇳';
    else if (domain.includes('ocha')) icon = '📍';
    else if (src.url) icon = '🔗';
    items += `
      <a class="source-card" href="${href}" target="_blank" rel="noopener noreferrer" ${noUrl}>
        <div class="source-card-icon">${icon}</div>
        <div class="source-card-body">
          <div class="source-card-title">${escHtml(src.title || '—')}</div>
          <div class="source-card-meta">
            ${domain ? `<span class="source-card-domain">${escHtml(domain)}</span>` : ''}
            ${src.date ? `<span class="source-card-date">${escHtml(src.date)}</span>` : ''}
          </div>
        </div>
        <span class="source-card-num">[${escHtml(num)}]</span>
      </a>`;
  });
  return `<div class="sources-section"><div class="sources-title">📎 Sources (${entries.length})</div><div class="sources-grid">${items}</div></div>`;
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
    return `<span class="citation" data-action="show-citation" data-num="${newNum}" data-date="${ctxText}" data-title="${ctxTitle}" data-url="${ctxUrl}">[${newNum}]</span>`;
  });
}

function renderCitations(escapedText, contexts) {
  return escapedText.replace(/\[(\d+)\]/g, (match, num) => {
    const ctx = contexts && (contexts[num] || contexts[String(num)]);
    if (!ctx) return `<span class="citation" style="background:#94a3b8">[${num}]</span>`;
    const ctxText  = encodeURIComponent(ctx.context || '');
    const ctxTitle = encodeURIComponent(ctx.title || '');
    const ctxUrl   = encodeURIComponent(ctx.url || '');
    return `<span class="citation" data-action="show-citation" data-num="${num}" data-date="${ctxText}" data-title="${ctxTitle}" data-url="${ctxUrl}">[${num}]</span>`;
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
  const dateTo   = document.getElementById('inp-date-to')?.value || '';

  try {
    const resp = await api('/api/sitrep/chunk-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ country, date_from: dateFrom, date_to: dateTo }),
    });
    const data = await resp.json();
    if (data.error) { el.classList.add('hidden'); return; }

    el.classList.remove('hidden', 'ok', 'warn', 'err');
    if (data.count === 0) {
      el.classList.add('err');
      const filterParts = [];
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
    `<span class="tag-chip">${escHtml(v)}<button type="button" data-action="tag-remove" data-field="${field}" data-idx="${i}">×</button></span>`
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
          ${u.role !== 'free' ? `<button class="btn btn-xs" data-action="set-role" data-uid="${esc(u.uid)}" data-role="free">Free</button>` : ''}
          ${u.role !== 'premium' ? `<button class="btn btn-xs btn-premium" data-action="set-role" data-uid="${esc(u.uid)}" data-role="premium">Premium</button>` : ''}
          ${u.role !== 'admin' ? `<button class="btn btn-xs btn-admin" data-action="set-role" data-uid="${esc(u.uid)}" data-role="admin">Admin</button>` : ''}
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

// ═══════════════════════════════════════════════════════════════════════════
// HOME DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════

let dashboardLoaded = false;
let latestBulletinData = null;
let crisisMapData = {};
let leafletMap = null;
let leafletMarkers = [];

function humanizeWeekLabel(label) {
  if (!label) return label;
  const isoMatch = label.match(/^(\d{4})-(\d{2})-(\d{2})\s+to\s+(\d{4})-(\d{2})-(\d{2})/);
  if (!isoMatch) return label;
  const [_, ys, ms, ds, ye, me, de] = isoMatch.map(Number);
  const sd = new Date(ys, ms - 1, ds);
  const ed = new Date(ye, me - 1, de);
  const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const ordinals = ['First','Second','Third','Fourth','Fifth'];
  if (sd.getMonth() === ed.getMonth() && sd.getFullYear() === ed.getFullYear()) {
    const weekOfMonth = Math.floor((ds - 1) / 7);
    return `${ordinals[Math.min(weekOfMonth, 4)]} week of ${monthNames[sd.getMonth()]} ${sd.getFullYear()}`;
  }
  return `${sd.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${ed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
}

async function loadDashboard() {
  if (dashboardLoaded) return;
  dashboardLoaded = true;

  // Load stats
  try {
    const r = await api('/api/db/stats');
    const d = await r.json();
    const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    el('dash-reports', d.report_count != null ? d.report_count.toLocaleString() : '—');
    el('dash-chunks', d.chunk_count != null ? d.chunk_count.toLocaleString() : '—');
  } catch { /* ignore */ }

  // Load bulletins + latest bulletin detail
  try {
    const r = await api('/api/sitrep/bulletins');
    const d = await r.json();
    const bulletins = d.bulletins || d || [];

    // Render weekly overview from latest bulletin
    if (Array.isArray(bulletins) && bulletins.length > 0) {
      const latest = bulletins[0];
      const elDate = document.getElementById('dash-weekly-date');
      if (elDate) elDate.textContent = humanizeWeekLabel(latest.week_label || '');

      // Load bulletin detail for overview
      try {
        const br = await api('/api/sitrep/bulletin/' + latest.filename);
        if (br.ok) {
          latestBulletinData = await br.json();
          renderDashOverview(latestBulletinData);
          // Store crisis data for map markers
          if (latestBulletinData.crises) {
            latestBulletinData.crises.forEach(c => {
              if (c.country) crisisMapData[c.country] = c;
            });
          }
        }
      } catch { /* ignore */ }

      const linkBtn = document.getElementById('dash-weekly-link');
      if (linkBtn) {
        linkBtn.style.display = '';
        linkBtn.addEventListener('click', () => {
           switchTab('bulletin');
           setTimeout(() => {
             const pills = document.querySelectorAll('.bulletin-tab-pill');
             if (pills.length > 0) pills[0].click();
           }, 300);
        });
      }
    } else {
      document.getElementById('dash-overview-stats').innerHTML = '<div class="dash-weekly-loading">No bulletins available yet.</div>';
    }
  } catch { /* ignore */ }

  // Initialize map first (creates Leaflet map), then add markers after data loads
  initWorldMap();
}

function renderDashOverview(b) {
  if (!b) return;

  // Key figures
  const statsEl = document.getElementById('dash-overview-stats');
  if (statsEl && b.key_figures) {
    statsEl.innerHTML = b.key_figures.map(f => `
      <div class="dash-kf-card">
        <div class="dash-kf-value">${esc(f.value)}</div>
        <div class="dash-kf-label">${esc(f.label)}</div>
      </div>
    `).join('');
  }

  // Weekly overview text (global_overview)
  const textEl = document.getElementById('dash-weekly-text');
  if (textEl) {
    const overview = b.global_overview || '';
    if (overview) {
      textEl.innerHTML = `<p>${esc(overview)}</p>`;
    } else {
      textEl.innerHTML = '<p class="dash-weekly-loading">No overview available for this week.</p>';
    }
  }
}

function initWorldMap() {
  const container = document.getElementById('world-map');
  if (!container) return;

  if (typeof L === 'undefined') {
    container.innerHTML = '<div class="dash-weekly-loading" style="min-height:200px;display:flex;align-items:center;justify-content:center;color:var(--text-muted)">Loading map…</div>';
    let retries = 0;
    const tryInit = () => {
      if (typeof L !== 'undefined') {
        initWorldMap();
      } else if (retries < 10) {
        retries++;
        setTimeout(tryInit, 500);
      } else {
        container.innerHTML = '<div class="dash-weekly-loading" style="min-height:200px;display:flex;align-items:center;justify-content:center;color:var(--text-muted)">Map unavailable. Please refresh.</div>';
      }
    };
    setTimeout(tryInit, 500);
    return;
  }

  if (leafletMap) {
    updateMapMarkers();
    leafletMap.invalidateSize();
    return;
  }

  try {
    leafletMap = L.map(container, {
      center: [20, 15],
      zoom: 2,
      minZoom: 2,
      maxZoom: 8,
      zoomControl: false,
      attributionControl: true,
      worldCopyJump: true,
    });

    L.control.zoom({ position: 'bottomright' }).addTo(leafletMap);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(leafletMap);

    setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 300);
  } catch (err) {
    console.error('[map] Leaflet init error:', err);
    container.innerHTML = '<div class="dash-weekly-loading" style="min-height:200px;display:flex;align-items:center;justify-content:center;color:var(--text-muted)">Map unavailable.</div>';
    return;
  }

  updateMapMarkers();
}

function updateMapMarkers() {
  if (!leafletMap || typeof L === 'undefined') return;

  // Remove existing markers
  leafletMarkers.forEach(m => leafletMap.removeLayer(m));
  leafletMarkers = [];

  const crises = Object.values(crisisMapData);
  if (!crises.length) return;

  crises.forEach(c => {
    const lat = c.coords?.lat;
    const lng = c.coords?.lng;
    if (!lat || !lng) return;

    const sevClass = (c.severity === 'high') ? 'severity-high' : (c.severity === 'medium') ? 'severity-medium' : 'severity-low';
    const sevLabels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
    const sevColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
    const color = sevColors[c.severity] || '#007AFF';

    const icon = L.divIcon({
      className: 'crisis-marker',
      html: `<div class="crisis-marker-dot ${sevClass}"></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });

    const themes = (c.themes || []).slice(0, 3).join(', ');
    const popupContent = `
      <div class="dash-popup-card">
        <div class="dash-popup-severity" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[c.severity] || ''}</div>
        <div class="dash-popup-country">${esc(c.country)}</div>
        <div class="dash-popup-headline">${esc(c.headline || '')}</div>
        <div class="dash-popup-summary">${esc((c.summary || '').substring(0, 180))}${c.summary && c.summary.length > 180 ? '…' : ''}</div>
        <div class="dash-popup-meta">${c.report_count || 0} reports${themes ? ' · ' + esc(themes) : ''}</div>
        ${c.has_sitrep ? `<button class="dash-popup-action" onclick="viewCrisisSitrep('${esc(c.country)}')">View SITREP →</button>` : ''}
      </div>
    `;

    const marker = L.marker([lat, lng], { icon })
      .addTo(leafletMap)
      .bindPopup(popupContent, {
        maxWidth: 280,
        closeButton: true,
        className: 'crisis-popup',
      });

    leafletMarkers.push(marker);
  });

  // Fit map to show all markers
  if (leafletMarkers.length > 0) {
    const group = L.featureGroup(leafletMarkers);
    leafletMap.fitBounds(group.getBounds().pad(0.3));
  }
}

function viewCrisisSitrep(country) {
  leafletMap.closePopup();
  switchTab('sitrep');
   setTimeout(() => {
     const sel = document.getElementById('inp-country');
     if (sel) sel.value = country;
   }, 100);
}

function renderDashBulletins() { /* deprecated — overview renders inline */ }
function renderDashCrises() { /* deprecated — overview renders inline */ }


document.addEventListener('DOMContentLoaded', () => {
  // Agent DOM refs
  chatInput = document.getElementById('chat-input');
  sendBtn   = document.getElementById('send-btn');
  chatDiv   = document.getElementById('chat-messages');
  busyDot   = document.getElementById('busy-dot');

  // Welcome mode — center content until user sends first message
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.add('welcome-mode');

  // ── Static element bindings ────────────────────────────────────────────

  // Sidebar nav
  const sidebar = document.getElementById('sidebar-nav');
  if (sidebar) sidebar.classList.add('collapsed');
  document.body.classList.add('sidebar-collapsed');
  const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
  if (sidebarCollapseBtn) sidebarCollapseBtn.addEventListener('click', toggleSidebarNav);
  const sidebarExpandHandle = document.getElementById('sidebar-expand-handle');
  if (sidebarExpandHandle) sidebarExpandHandle.addEventListener('click', toggleSidebarNav);
  const hamburgerBtn = document.getElementById('hamburger-btn');
  if (hamburgerBtn) hamburgerBtn.addEventListener('click', () => {
    const sb = document.getElementById('sidebar-nav');
    if (sb) { sb.classList.remove('hidden', 'collapsed'); sb.classList.add('expanded-once'); }
    document.body.classList.remove('sidebar-collapsed');
  });

  // Tab buttons
  document.querySelectorAll('.sidebar-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Logout button
  const logoutBtn = document.getElementById('user-logout');
  if (logoutBtn) logoutBtn.addEventListener('click', () => { if (typeof signOut === 'function') signOut(); });

  // DB tab
  const btnUploadPdf = document.getElementById('btn-upload-pdf');
  if (btnUploadPdf) btnUploadPdf.addEventListener('click', showUploadModal);
  const btnRefreshReports = document.getElementById('btn-refresh-reports');
  if (btnRefreshReports) btnRefreshReports.addEventListener('click', reloadReports);
  const fSearch = document.getElementById('f-search');
  if (fSearch) fSearch.addEventListener('input', dbFilter);
  const fCountry = document.getElementById('f-country');
  if (fCountry) fCountry.addEventListener('change', applyFilters);
  const fSource = document.getElementById('f-source');
  if (fSource) fSource.addEventListener('change', applyFilters);
  const fFrom = document.getElementById('f-from');
  if (fFrom) fFrom.addEventListener('change', applyFilters);
  const fTo = document.getElementById('f-to');
  if (fTo) fTo.addEventListener('change', applyFilters);

  // Table header sort
  document.querySelectorAll('.rtable thead th[data-sort]').forEach(th => {
    th.addEventListener('click', () => sortBy(th.dataset.sort));
  });

  // Chat sidebar
  const chatOverlay = document.getElementById('chat-sidebar-overlay');
  if (chatOverlay) chatOverlay.addEventListener('click', toggleChatSidebar);
  const chatCloseBtn = document.getElementById('chat-sidebar-close-btn');
  if (chatCloseBtn) chatCloseBtn.addEventListener('click', toggleChatSidebar);
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggleChatSidebar);
  const chatNewBtn = document.getElementById('chat-new-btn');
  if (chatNewBtn) chatNewBtn.addEventListener('click', newChat);
  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  // DB modal
  const dbModal = document.getElementById('db-modal');
  if (dbModal) dbModal.addEventListener('click', e => { if (e.target === dbModal) closeDbModal(); });
  const dbModalCloseBtn = document.getElementById('db-modal-close-btn');
  if (dbModalCloseBtn) dbModalCloseBtn.addEventListener('click', closeDbModal);
  const btnAskAbout = document.getElementById('btn-ask-about');
  if (btnAskAbout) btnAskAbout.addEventListener('click', askAbout);

  // Upload modal
  const uploadModal = document.getElementById('upload-modal');
  if (uploadModal) uploadModal.addEventListener('click', e => { if (e.target === uploadModal) hideUploadModal(); });
  const uploadModalCloseBtn = document.getElementById('upload-modal-close-btn');
  if (uploadModalCloseBtn) uploadModalCloseBtn.addEventListener('click', hideUploadModal);
  const uploadForm = document.getElementById('upload-form');
  if (uploadForm) uploadForm.addEventListener('submit', e => { e.preventDefault(); submitUpload(e); });
  const btnClearUpload = document.getElementById('btn-clear-upload');
  if (btnClearUpload) btnClearUpload.addEventListener('click', clearUploadForm);

  // Agent keyboard
  chatInput.addEventListener('keydown', e => {
    // Block input when rate limit is exhausted
    const rl = window.__rateLimit;
    const role = window.__userRole || 'free';
    if (rl && rl.remaining <= 0 && role !== 'admin') {
      e.preventDefault();
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

  // SITREP event listeners
  const btnRun = document.getElementById('btn-run');
  if (btnRun) btnRun.addEventListener('click', runPipeline);

  ['inp-event', 'inp-themes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') runPipeline(); });
  });

  const countryEl = document.getElementById('inp-country');
  if (countryEl) {
    countryEl.addEventListener('change', () => fetchCountryDateRange(countryEl.value));
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

  // ── Event delegation for dynamic elements ──────────────────────────────
  document.addEventListener('click', e => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;

    switch (action) {
      case 'quick-prompt':
        sendQuickPrompt(target.dataset.text);
        break;
      case 'rename-chat':
        e.stopPropagation();
        renameChat(target.dataset.chatId, target);
        break;
      case 'delete-chat':
        e.stopPropagation();
        confirmDeleteChat(target.dataset.chatId, target);
        break;
      case 'confirm-delete-chat':
        e.stopPropagation();
        executeDeleteChat(target.dataset.chatId, target);
        break;
      case 'cancel-delete-chat':
        e.stopPropagation();
        target.closest('.delete-confirm')?.remove();
        break;
      case 'discuss-sitrep':
        discussSitrepWithAgent();
        break;
      case 'go-chat':
        switchTab('agent');
        break;
      case 'go-sitrep':
        switchTab('sitrep');
        break;
      case 'go-db':
        switchTab('db');
        break;
      case 'go-sitrep-country':
         switchTab('sitrep');
         setTimeout(() => {
           const sel = document.getElementById('inp-country');
           if (sel) { sel.value = target.dataset.country || ''; }
         }, 100);
         break;
      case 'go-bulletin':
        switchTab('bulletin');
        break;
      case 'dash-view-crisis':
        const crisisCountry = target.dataset.country;
        if (crisisCountry) {
          const crisis = crisisMapData[crisisCountry];
          if (crisis && crisis.has_sitrep) {
            switchTab('sitrep');
            setTimeout(() => {
              const sel = document.getElementById('inp-country');
              if (sel) sel.value = crisisCountry;
             }, 100);
          }
        }
        break;
      case 'switch-report-view':
        switchReportView(target.dataset.mode);
        break;
      case 'toggle-card':
        toggleCard(target);
        break;
      case 'show-citation':
        showCitationFromEl(target);
        break;
      case 'tag-add':
        tagAdd(target.dataset.field);
        break;
      case 'tag-remove':
        tagRemove(target.dataset.field, parseInt(target.dataset.idx, 10));
        break;
      case 'set-role':
        setUserRole(target.dataset.uid, target.dataset.role);
        break;
      case 'generate-bulletin':
        generateBulletin();
        break;
      case 'open-bulletin':
        // Highlight active tab-pill
        document.querySelectorAll('.bulletin-tab-pill').forEach(p => p.classList.remove('active'));
        target.classList.add('active');
        openBulletin(target.dataset.filename);
        break;
      case 'view-bulletin-sitrep':
        viewBulletinSitrep(target.dataset.country);
        break;
    }
  });

  // DB report row click delegation
  document.getElementById('rtbody')?.addEventListener('click', e => {
    const row = e.target.closest('.db-report-row');
    if (row && row.dataset.reportId) openDbReport(parseInt(row.dataset.reportId, 10));
  });

  // Chat list click delegation (for rename/delete buttons that stop propagation)
  document.getElementById('chat-list')?.addEventListener('click', e => {
    const actionEl = e.target.closest('[data-action]');
    if (actionEl) return; // handled by global delegation
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
    switchTab('home');
    loadChatList();
    updateVisibilityFromAuth();
  }

  function updateVisibilityFromAuth() {
    if (typeof window.updateVisibility === 'function') {
      window.updateVisibility();
    } else {
       const role = window.__userRole || 'free';
       const isPremium = role === 'premium' || role === 'admin';
       const sitrepFormBar = document.getElementById('sitrep-form-bar');
       if (sitrepFormBar) sitrepFormBar.style.display = isPremium ? '' : 'none';
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
          <button class="bulletin-gen-btn" data-action="generate-bulletin" style="margin-left:8px">Generate Weekly Bulletin</button>
        </div>`;
      return;
    }
    container.innerHTML = bulletins.map((b, i) => {
      const fallbackTag = b.data_date_range?.fallback
        ? ' <span style="color:#f59e0b;font-size:10px">⚠</span>'
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
  const crises = (b.crises || []).sort((a, c) =>
    (severityOrder[a.severity] ?? 3) - (severityOrder[c.severity] ?? 3)
  );

  const severityBadge = (s) => {
    const colors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
    const labels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
    return `<span class="severity-badge" style="background:${colors[s]||'#6b7280'}22;color:${colors[s]||'#6b7280'};border:1px solid ${colors[s]||'#6b7280'}44">${labels[s]||s.toUpperCase()}</span>`;
  };

  const keyFigures = (b.key_figures || []).map(f => `
    <div class="bulletin-kf-card">
      <div class="bulletin-kf-value">${f.value}</div>
      <div class="bulletin-kf-label">${f.label}</div>
    </div>
  `).join('');

  const crisisCards = crises.map(c => {
    const hdxFigures = (c.hdx_key_figures || []).map(f => `
      <div class="hdx-kf-mini">
        <span class="hdx-kf-value">${f.value}</span>
        <span class="hdx-kf-label">${f.label}</span>
      </div>
    `).join('');

    return `
    <div class="crisis-card crisis-${c.severity}">
      <div class="crisis-card-header">
        <div class="crisis-card-country">${c.country}</div>
        ${severityBadge(c.severity)}
      </div>
      <div class="crisis-card-headline">${c.headline}</div>
      <div class="crisis-card-summary">${c.summary}</div>
      ${hdxFigures ? `<div class="hdx-kf-row">${hdxFigures}</div>` : ''}
      <div class="crisis-card-meta">
        <span>${c.report_count} reports</span>
        ${(c.themes || []).slice(0, 3).map(t => `<span class="crisis-theme-tag">${t}</span>`).join('')}
      </div>
      ${c.has_sitrep ? `<button class="crisis-sitrep-btn" data-action="view-bulletin-sitrep" data-country="${escHtml(c.country)}">View SITREP →</button>` : ''}
    </div>
  `;}).join('');

  // Show fallback notice if data date range differs from requested range
  const fallbackNotice = b.data_date_range?.fallback
    ? `<div class="bulletin-fallback-notice">
        ⚠️ No data available for ${b.data_date_range.requested_from} to ${b.data_date_range.requested_to}.
        Showing data from ${b.data_date_range.actual_from} to ${b.data_date_range.actual_to} instead.
      </div>`
    : '';

  container.innerHTML = `
    <div class="bulletin-header">
      <div class="bulletin-title-row">
        <h2 class="bulletin-title">📰 Weekly Humanitarian Bulletin</h2>
        <span class="bulletin-date">${humanizeWeekLabel(b.week_label)}</span>
      </div>
      ${fallbackNotice}
      <div class="bulletin-kf-row">${keyFigures}</div>
    </div>

    <div class="bulletin-overview">
      <h3>Global Overview</h3>
      <p>${b.global_overview}</p>
    </div>

    <div class="bulletin-crises">
      <h3>Active Crises</h3>
      <div class="crisis-grid">${crisisCards}</div>
    </div>
  `;
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
