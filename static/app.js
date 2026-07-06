// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for Sightline
//
// Tab 1: Database  → /api/db/*
// Tab 2: Agent     → /api/agent/chat
// Tab 3: SITREP    → /api/sitrep/*
// ═══════════════════════════════════════════════════════════════════════════

// ── Constants ──────────────────────────────────────────────────────────────
const ADMIN_EMAIL = 'serkankizilirmak@gmail.com';
const TAB_NAMES = ['home', 'agent', 'sitrep', 'bulletin', 'db', 'admin'];
const DEFAULT_MODEL = 'thinking';
const CHAT_MODELS = {
  flash: { name: 'Flash', desc: 'Fast responses', premium: false },
  thinking: { name: 'Thinking', desc: 'Balanced', premium: false },
  ultra: { name: 'Ultra', desc: 'Best quality — Premium', premium: true },
  deep_think: { name: 'Deep Think', desc: 'Deep analysis — Premium', premium: true },
};

// ── Shared state ────────────────────────────────────────────────────────────
let currentTab = 'agent';

// DB tab state
const dbState = {
  allReports: [],
  sortKey: 'date',
  sortAsc: false,
  filterTimer: null,
  currentReportTitle: '',
  currentReportId: null,
};

// Agent tab state
const chatState = {
  isStreaming: false,
  currentAiEl: null,
  currentAiText: '',
  selectedModel: DEFAULT_MODEL,
};

// SITREP tab state
const sitrepState = {
  currentStep: -1,
  stepStates: [],
  activeJobId: null,
  activeFile: null,
};

// Upload modal state
const _tags = { country: [], theme: [] };

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
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
  const main = document.querySelector('.main');
  if (nav) {
    const wasCollapsed = nav.classList.contains('collapsed');
    nav.classList.toggle('collapsed');
    if (nav.classList.contains('collapsed')) {
      document.body.classList.add('sidebar-collapsed');
      if (main) main.style.marginLeft = '72px';
    } else {
      document.body.classList.remove('sidebar-collapsed');
      if (main) main.style.marginLeft = '';
    }
  }
}

function switchTab(name) {
  currentTab = name;
  const allTabs = TAB_NAMES;
  const sidebar = document.getElementById('sidebar-nav');
  const main = document.querySelector('.main');
  const hamburger = document.getElementById('hamburger-btn');

  allTabs.forEach(t => {
    const panel = document.getElementById('panel-' + t);
    const tab = document.getElementById('tab-' + t);
    if (panel) panel.classList.toggle('active', t === name);
    if (tab) tab.classList.toggle('active', t === name);
  });

  // Sync mobile bottom tab bar
  document.querySelectorAll('.mobile-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });

  // Home: hide sidebar, show hamburger
  if (name === 'home') {
    if (sidebar) sidebar.classList.add('hidden');
    if (main) main.style.marginLeft = '0';
    if (hamburger) hamburger.style.display = 'none';
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
    if (name === 'admin') {
      loadAdminUsers();
      // Load analytics too (charts render lazily once section is shown)
      loadAnalytics();
    }
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
  // Deep Analysis
  { label: "Full Report", text: "Show me the full content of report 12345", cat: "analysis" },
  { label: "Convert to MD", text: "Convert report 12345 to markdown format", cat: "analysis" },
];

function getWelcomeHTML() {
  return `<div class="chat-center">
  <div class="quick-prompts">
    <div class="quick-prompts-title">Try asking:</div>
    ${QUICK_PROMPTS.map(p => `<button class="quick-prompt-btn cat-${p.cat}" data-action="quick-prompt" data-text="${esc(p.text.replace(/"/g, '&quot;'))}">${p.label}</button>`).join('')}
  </div>
  <button class="welcome-history-btn" data-action="open-chat-history" title="Chat history">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="10"/></svg>
    Chat history
  </button>
</div>`;
}

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
  const rl = window.__rateLimit;
  const role = window.__userRole || 'free';
  if (rl && rl.remaining <= 0 && role !== 'admin') {
    toast('Daily message limit reached. Upgrade to Premium for unlimited access.', 'warning');
    return;
  }
  chatInput.value = text;
  sendMessage();
}

async function sendMessage() {
  if (chatState.isStreaming) return;
  // Exit welcome mode — animate input bar sliding down
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain && chatMain.classList.contains('welcome-mode')) {
    const footer = chatMain.querySelector('.chat-footer');
    if (footer) {
      footer.style.animation = 'slideDownReturn .3s ease forwards';
      await new Promise(r => setTimeout(r, 280));
    }
    chatMain.classList.remove('welcome-mode');
    if (footer) footer.style.animation = '';
  }
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

  chatState.isStreaming = true;
  sendBtn.disabled    = true;
  sendBtn.innerHTML   = '<div class="spin spin-lg"></div>';
  busyDot.classList.add('visible');

  chatState.currentAiEl   = addMsg('assistant',
    '<div class="typing-dots"><span></span><span></span><span></span></div>');
  chatState.currentAiText = '';

  try {
    const resp = await api('/api/agent/chat', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text, model: chatState.selectedModel }),
    });

    if (resp.status === 429) {
      try {
        const errData = await resp.json();
        if (errData.remaining === 0) {
          chatState.currentAiEl.innerHTML = `<div class="rate-limit-msg"><div class="rate-limit-msg-title">Daily message limit reached (${errData.used}/${errData.limit})</div><div class="rate-limit-msg-body">Upgrade to Premium for unlimited access.</div><div class="rate-limit-msg-contact">Contact: <a href="mailto:${ADMIN_EMAIL}">${ADMIN_EMAIL}</a></div></div>`;
          updateChatRateUI(errData);
        } else {
          chatState.currentAiEl.innerHTML = '<span class="msg-warn">Agent is busy, please wait.</span>';
          toast('Agent is busy, please try again in a moment', 'warning');
        }
      } catch {
        chatState.currentAiEl.innerHTML = '<span class="msg-warn">Agent is busy, please wait.</span>';
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
          if (!chatState.currentAiText) chatState.currentAiEl.innerHTML = '';
          chatState.currentAiText += evt.text;
          chatState.currentAiEl.innerHTML = sanitizeHtml(md(chatState.currentAiText));
          chatDiv.scrollTop = chatDiv.scrollHeight;
        } else if (evt.type === 'tool_start') {
          if (!chatState.currentAiText) chatState.currentAiEl.innerHTML = '';
          addToolInd(evt.name);
        } else if (evt.type === 'error') {
          chatState.currentAiEl.innerHTML = `<span class="msg-error">Error: ${esc(evt.text)}</span>`;
          clearToolInds();
        } else if (evt.type === 'done') {
          clearToolInds();
          if (!chatState.currentAiText) chatState.currentAiEl.innerHTML = '<span class="msg-placeholder">—</span>';
          if (typeof checkAdminStatus === 'function') checkAdminStatus();
        }
      }
    }
  } catch (err) {
    if (chatState.currentAiEl) {
      chatState.currentAiEl.innerHTML = `<span class="msg-error">Connection error: ${esc(err.message)}</span>`;
    }
    clearToolInds();
  } finally {
    chatState.isStreaming          = false;
    sendBtn.disabled     = false;
    sendBtn.innerHTML    = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 2L11 13"/><path d="M22 2L15 22 11 13 2 9l20-7z"/></svg>';
    busyDot.classList.remove('visible');
    chatState.currentAiEl          = null;
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
    document.querySelectorAll('.quick-prompt-btn').forEach(b => b.disabled = false);
    return;
  }
  // Rate limit exhausted — lock input
  chatInput.disabled = true;
  chatInput.placeholder = 'Daily limit reached';
  document.querySelectorAll('.quick-prompt-btn').forEach(b => b.disabled = true);
}

async function resetChat() {
  if (!confirm('Clear chat history?')) return;
  await api('/api/agent/chat/reset', { method: 'POST' });
  chatDiv.innerHTML = getWelcomeHTML();
  chatState.currentAiText = '';
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.add('welcome-mode');
  loadChatList();
}

// ── Multi-chat management ────────────────────────────────────────────────

function renderChatList(listEl, chats, activeId) {
  listEl.innerHTML = '';
  for (const c of chats) {
    const item = document.createElement('div');
    item.className = 'chat-item' + (c.id === activeId ? ' active' : '');
    item.innerHTML = `
      <span class="chat-item-title" title="${esc(c.title)}">${esc(c.title)}</span>
      <span class="chat-item-actions">
        <button class="chat-item-btn" data-action="rename-chat" data-chat-id="${esc(c.id)}" title="Rename">R</button>
        <button class="chat-item-btn delete" data-action="delete-chat" data-chat-id="${esc(c.id)}" title="Delete">X</button>
      </span>`;
    item.addEventListener('click', (e) => {
      if (e.target.closest('.chat-item-btn')) return;
      selectChat(c.id);
    });
    listEl.appendChild(item);
  }
}

async function loadChatSidebar() {
  try {
    const r = await api('/api/agent/chats');
    const d = await r.json();
    const list = document.getElementById('chat-list');
    if (!list) return;
    renderChatList(list, d.chats, d.active);
  } catch { /* ignore */ }
}

async function loadChatList() {
  if (typeof checkAdminStatus === 'function' && typeof getIdToken === 'function' && getIdToken()) {
    await checkAdminStatus();
  }
  if (typeof updateVisibility === 'function') updateVisibility();
  try {
    const r = await api('/api/agent/chats');
    const d = await r.json();
    const list = document.getElementById('chat-list');
    if (!list) return;
    renderChatList(list, d.chats, d.active);
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
              addMsg('assistant', sanitizeHtml(md(m.content)));
            }
          }
          chatState.currentAiText = '';
        } else {
          if (chatMain) chatMain.classList.add('welcome-mode');
          chatDiv.innerHTML = getWelcomeHTML();
          chatState.currentAiText = '';
        }
      } catch { chatDiv.innerHTML = getWelcomeHTML(); chatState.currentAiText = ''; }
    } else {
      if (chatMain) chatMain.classList.add('welcome-mode');
      chatDiv.innerHTML = getWelcomeHTML();
      chatState.currentAiText = '';
    }
  } catch { /* ignore */ }
}

async function newChat() {
  if (chatState.isStreaming) return;
  try {
    // Close sidebar first for smooth transition
    const sb = document.getElementById('chat-sidebar');
    const ov = document.getElementById('chat-sidebar-overlay');
    if (sb) sb.classList.remove('open');
    if (ov) ov.classList.remove('open');

    // Check if there's an empty chat we can reuse
    const listR = await api('/api/agent/chats');
    const listD = await listR.json();
    const emptyChat = listD.chats.find(c => c.title === 'New Chat' || c.title.startsWith('New Chat'));
    if (emptyChat) {
      await selectChat(emptyChat.id);
      return;
    }
    // No empty chat found — create a new one
    await api('/api/agent/chats/new', { method: 'POST' });
    chatDiv.innerHTML = getWelcomeHTML();
    chatState.currentAiText = '';
    const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
    if (chatMain) chatMain.classList.add('welcome-mode');
    await loadChatList();
  } catch { /* ignore */ }
}

async function selectChat(chatId) {
  if (chatState.isStreaming) return;
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
      chatDiv.innerHTML = getWelcomeHTML();
    }
    chatState.currentAiText = '';
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
  overlay.addEventListener('click', (e) => {
    e.stopPropagation();
    const t = e.target.closest('[data-action]');
    if (!t) return;
    const a = t.dataset.action;
    if (a === 'confirm-delete-chat') executeDeleteChat(t.dataset.chatId, t);
    else if (a === 'cancel-delete-chat') overlay.remove();
  });
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
          else addMsg('assistant', sanitizeHtml(md(m.content)));
        }
      } else {
        chatDiv.innerHTML = getWelcomeHTML();
      }
      chatState.currentAiText = '';
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
    document.getElementById('s-chunks').textContent  = (d.chunk_count  || 0).toLocaleString();
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
    if (va < vb) return dbState.sortAsc ? -1 :  1;
    if (va > vb) return dbState.sortAsc ?  1 : -1;
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
    const r   = await res.json();
    dbState.currentReportTitle = r.title || '';

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
  chatInput.value = `Tell me about the report "${dbState.currentReportTitle}" (ID: ${dbState.currentReportId}). What are the key findings and summary?`;
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
  sitrepState.currentStep = -1;
  sitrepState.stepStates  = new Array(STEPS.length).fill('waiting');
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
      div.dataset.action = 'open-sitrep-report';
      const country = item.filename.split('_')[0].replace(/\(/g, ' ').replace(/\)/g, '').trim();
      div.innerHTML = `<span>${escHtml(country)}</span>`;
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
    const resp   = await api(`/api/sitrep/report?file=${encodeURIComponent(filename)}`);
    const report = await resp.json();
    if (report.error) throw new Error(report.error);
    renderSitrepReport(report, filename);
  } catch (err) {
    document.getElementById('report-content').innerHTML =
      `<div class="error-placeholder">Could not load report: ${escHtml(err.message)}</div>`;
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
    .filter(([num, src]) => src && typeof src === 'object' && (src.url || src.title))
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

function buildSourcesList(sources, { cardStyle = false } = {}) {
  const valid = sources.filter(s => s.url || s.title);
  if (!valid.length) return '';
  let items = '';
  valid.forEach(src => {
    let domain = '';
    try { domain = new URL(src.url || '').hostname.replace(/^www\./, ''); } catch {}
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
  const containerClass = cardStyle ? 'sources-grid' : '';
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

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS DASHBOARD
// ─────────────────────────────────────────────────────────────────────────────

async function loadAnalytics() {
  const tok = window.getIdToken ? window.getIdToken() : '';
  if (!tok) return;
  try {
    const resp = await fetch('/api/admin/analytics', {
      headers: { 'Authorization': 'Bearer ' + tok }
    });
    if (!resp.ok) throw new Error('Failed to load analytics');
    const data = await resp.json();

    // KPI Cards
    const kpiContainer = document.getElementById('analytics-kpi-cards');
    if (kpiContainer) {
      kpiContainer.innerHTML = [
        { label: 'Total Users', value: data.users.total, icon: '👥' },
        { label: 'DAU (24h)', value: data.users.dau, icon: '🔥' },
        { label: 'WAU (7d)', value: data.users.wau, icon: '📅' },
        { label: 'New This Week', value: data.users.new_this_week, icon: '✨' },
      ].map(k => `
        <div class="kpi-card">
          <div class="kpi-value">${k.value}</div>
          <div class="kpi-label">${k.icon} ${k.label}</div>
        </div>
      `).join('');
    }

    // DAU Trend Chart
    renderLineChart('chart-dau', data.dau_trend.map(d => d.day).reverse(),
                    data.dau_trend.map(d => d.users).reverse(), 'DAU');

    // Event Timeline Chart
    renderBarChart('chart-events', data.events.timeline.map(d => d.day).reverse(),
                   data.events.timeline.map(d => d.count).reverse(), 'Events');

    // Top Events Chart
    renderDoughnutChart('chart-top-events',
                        data.events.top_events.map(e => e.event),
                        data.events.top_events.map(e => e.count));

    // SITREP Runs Chart
    renderBarChart('chart-sitrep',
                   data.sitrep_runs.map(s => s.country),
                   data.sitrep_runs.map(s => s.count), 'Runs');

    // Recent Users Table
    const tbody = document.querySelector('#analytics-recent-users tbody');
    if (tbody) {
      tbody.innerHTML = data.recent_users.map(u => {
        const roleClass = u.role === 'admin' ? 'role-admin' : u.role === 'premium' ? 'role-premium' : 'role-free';
        return `<tr>
          <td>${esc(u.email || '—')}</td>
          <td><span class="admin-role-badge ${roleClass}">${u.role}</span></td>
          <td>${u.created_at ? new Date(u.created_at * 1000).toLocaleDateString() : '—'}</td>
          <td>${u.last_seen ? new Date(u.last_seen * 1000).toLocaleDateString() : '—'}</td>
        </tr>`;
      }).join('');
    }
  } catch (e) {
    console.error('Analytics load error:', e);
  }
}
window.loadAnalytics = loadAnalytics;

// Chart.js helpers
function _getOrCreateChartCtx(canvasId) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return null;
  if (!window._analyticsCharts) window._analyticsCharts = {};
  if (window._analyticsCharts[canvasId]) window._analyticsCharts[canvasId].destroy();
  return ctx;
}

function renderLineChart(canvasId, labels, data, label) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label, data, borderColor: '#4f9eff', backgroundColor: 'rgba(79,158,255,0.1)', tension: 0.3 }] },
    options: { responsive: true, plugins: { legend: { display: false } } }
  });
}

function renderBarChart(canvasId, labels, data, label) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label, data, backgroundColor: '#4f9eff' }] },
    options: { responsive: true, plugins: { legend: { display: false } } }
  });
}

function renderDoughnutChart(canvasId, labels, data) {
  const ctx = _getOrCreateChartCtx(canvasId);
  if (!ctx) return;
  window._analyticsCharts[canvasId] = new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: ['#4f9eff','#ff6b6b','#4ecdc4','#f7df1e','#a55eea','#fd7e14','#26de81','#fc5c65','#45aaf2','#fd9644'] }] },
    options: { responsive: true }
  });
}
window.renderLineChart = renderLineChart;
window.renderBarChart = renderBarChart;
window.renderDoughnutChart = renderDoughnutChart;

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

  // Freemium preview: check if user is authenticated
  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;
  const statsUrl = isAuthed ? '/api/db/stats' : '/api/public/stats';
  const bulletinsUrl = isAuthed ? '/api/sitrep/bulletins' : '/api/public/bulletins';
  const bulletinDetailUrl = isAuthed ? '/api/sitrep/bulletin/' : '/api/public/bulletin/';

  // Load stats
  try {
    const r = await api(statsUrl);
    const d = await r.json();
    const el = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    el('dash-reports', d.report_count != null ? d.report_count.toLocaleString() : '—');
    el('dash-chunks', d.chunk_count != null ? d.chunk_count.toLocaleString() : '—');
  } catch { /* ignore */ }

  // Load bulletins + latest bulletin detail
  try {
    const r = await api(bulletinsUrl);
    const d = await r.json();
    const bulletins = d.bulletins || d || [];

    // Render weekly overview from latest bulletin
    if (Array.isArray(bulletins) && bulletins.length > 0) {
      const latest = bulletins[0];
      const elDate = document.getElementById('dash-weekly-date');
      if (elDate) elDate.textContent = humanizeWeekLabel(latest.week_label || '');

      // Load bulletin detail for overview
      try {
        const br = await api(bulletinDetailUrl + latest.filename);
        if (br.ok) {
          latestBulletinData = await br.json();
          renderDashOverview(latestBulletinData);
          // Store crisis data for map markers
          if (latestBulletinData.crises) {
            latestBulletinData.crises.forEach(c => {
              if (c.country) crisisMapData[c.country] = c;
            });
          }
          // Update map markers after data is loaded
          setTimeout(() => updateMapMarkers(), 300);
        }
      } catch { /* ignore */ }

      const linkBtn = document.getElementById('dash-weekly-link');
      if (linkBtn) {
        linkBtn.style.display = '';
        linkBtn.addEventListener('click', () => {
           if (!isAuthed) {
             // Preview mode: scroll to login panel
             const overlay = document.getElementById('auth-overlay');
             if (overlay) overlay.classList.add('slide-in', 'shake');
             setTimeout(() => overlay && overlay.classList.remove('shake'), 500);
             return;
           }
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

  // Initialize map after a short delay to ensure container has height
  setTimeout(() => { initWorldMap(); }, 200);
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
      const rendered = typeof marked !== 'undefined' ? marked.parse(overview) : `<p>${esc(overview)}</p>`;
      textEl.innerHTML = sanitizeHtml(rendered);
    } else {
      textEl.innerHTML = '<p class="dash-weekly-loading">No overview available for this week.</p>';
    }
  }
}

function initWorldMap() {
  const container = document.getElementById('world-map');
  if (!container) return;

  if (typeof L === 'undefined') {
    container.innerHTML = '<div class="center-loading dash-weekly-loading">Loading map…</div>';
    let retries = 0;
    const tryInit = () => {
      if (typeof L !== 'undefined') {
        initWorldMap();
      } else if (retries < 10) {
        retries++;
        setTimeout(tryInit, 500);
      } else {
        container.innerHTML = '<div class="center-loading dash-weekly-loading">Map unavailable. Please refresh.</div>';
      }
    };
    setTimeout(tryInit, 500);
    return;
  }

  if (leafletMap) {
    updateMapMarkers();
    setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 100);
    return;
  }

  // Ensure container has dimensions before init
  const wrap = container.closest('.dash-map-wrap');
  if (wrap && wrap.offsetHeight < 100) {
    // Container not visible yet, retry
    setTimeout(() => { initWorldMap(); }, 300);
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

    setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 500);
  } catch (err) {
    console.error('[map] Leaflet init error:', err);
    container.innerHTML = '<div class="center-loading dash-weekly-loading">Map unavailable.</div>';
    return;
  }

  updateMapMarkers();
}

function updateMapMarkers() {
  if (!leafletMap || typeof L === 'undefined') return;

  leafletMarkers.forEach(m => leafletMap.removeLayer(m));
  leafletMarkers = [];

  const crises = Object.values(crisisMapData);
  if (!crises.length) return;

  const sevColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };

  crises.forEach(c => {
    const lat = c.coords?.lat;
    const lng = c.coords?.lng;
    if (!lat || !lng) return;

    const sevClass = (c.severity === 'high') ? 'severity-high' : (c.severity === 'medium') ? 'severity-medium' : 'severity-low';
    const color = sevColors[c.severity] || '#007AFF';

    const icon = L.divIcon({
      className: 'crisis-marker',
      html: `<div class="crisis-marker-dot ${sevClass}"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });

    const marker = L.marker([lat, lng], { icon })
      .addTo(leafletMap)
      .on('click', () => openCrisisPanel(c));

    leafletMarkers.push(marker);
  });

  if (leafletMarkers.length > 0) {
    const group = L.featureGroup(leafletMarkers);
    leafletMap.fitBounds(group.getBounds().pad(0.3));
  }
}

function openCrisisPanel(crisis) {
  const panel = document.getElementById('dash-crisis-panel');
  const mapEl = document.getElementById('world-map');
  const countryEl = document.getElementById('dash-crisis-panel-country');
  const bodyEl = document.getElementById('dash-crisis-panel-body');
  if (!panel || !countryEl || !bodyEl) return;

  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;

  const sevColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
  const sevLabels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
  const color = sevColors[crisis.severity] || '#007AFF';

  countryEl.textContent = crisis.country || '';

  let html = '';

  html += `<span class="crisis-severity-badge" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[crisis.severity] || ''}</span>`;

  if (crisis.headline) {
    html += `<div class="crisis-headline">${esc(crisis.headline)}</div>`;
  }

  if (isAuthed) {
    // Authenticated: show full crisis detail
    if (crisis.summary) {
      html += `<div class="crisis-summary">${esc(crisis.summary)}</div>`;
    }

    html += `<div class="crisis-meta">`;
    if (crisis.report_count) {
      html += `<span class="crisis-meta-item"><strong>${crisis.report_count}</strong> reports</span>`;
    }
    if (crisis.sources && crisis.sources.length) {
      html += `<span class="crisis-meta-item"><strong>${crisis.sources.length}</strong> sources</span>`;
    }
    html += `</div>`;

    if (crisis.themes && crisis.themes.length) {
      html += `<div class="crisis-themes">${crisis.themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
    }

    if (crisis.has_sitrep) {
      html += `<button class="crisis-sitrep-btn" data-action="dash-view-crisis" data-country="${esc(crisis.country)}">View SITREP →</button>`;
    }
  } else {
    // Preview mode: show limited info + sign-up prompt
    html += `<div class="crisis-meta">`;
    if (crisis.report_count) {
      html += `<span class="crisis-meta-item"><strong>${crisis.report_count}</strong> reports</span>`;
    }
    html += `</div>`;

    // Lock prompt
    html += `<div class="preview-lock-msg">
      <div class="preview-lock-icon">🔒</div>
      <div class="preview-lock-text">Sign in to read full crisis analysis, sources, and themes.</div>
      <button class="preview-lock-btn" onclick="document.getElementById('auth-overlay').classList.remove('hidden');document.getElementById('auth-overlay').classList.add('slide-in');">Sign In with Google</button>
    </div>`;
  }

  bodyEl.innerHTML = html;

  panel.classList.add('open');
  if (mapEl) mapEl.classList.add('panel-open');

  if (leafletMap) {
    setTimeout(() => { leafletMap.invalidateSize(); }, 400);
  }
}

function closeCrisisPanel() {
  const panel = document.getElementById('dash-crisis-panel');
  const mapEl = document.getElementById('world-map');
  if (panel) panel.classList.remove('open');
  if (mapEl) mapEl.classList.remove('panel-open');
  if (leafletMap) {
    setTimeout(() => { leafletMap.invalidateSize(); }, 400);
  }
}

function viewCrisisSitrep(country) {
  closeCrisisPanel();
  switchTab('sitrep');
   setTimeout(() => {
     const sel = document.getElementById('inp-country');
     if (sel) sel.value = country;
   }, 100);
}




document.addEventListener('DOMContentLoaded', () => {
  // Legal modal
  const termsLink = document.getElementById('terms-link');
  const privacyLink = document.getElementById('privacy-link');
  const legalModal = document.getElementById('legal-modal');
  const legalTitle = document.getElementById('legal-modal-title');
  const legalBody = document.getElementById('legal-modal-body');
  const legalClose = document.getElementById('legal-modal-close');

  const legalContent = {
    terms: `<h4>1. Acceptance</h4>
<p>By accessing and using Sightline, you agree to be bound by these Terms of Use. If you do not agree, please do not use the service.</p>
<h4>2. Purpose</h4>
<p>Sightline is a humanitarian data analytics platform that aggregates publicly available information from ReliefWeb and HDX to support humanitarian analysis, research, and decision-making.</p>
<h4>3. Data Sources</h4>
<p>All data displayed on Sightline originates from publicly accessible humanitarian sources, primarily the ReliefWeb API and the HDX HAPI API. We do not claim ownership of source data. All rights to original data remain with their respective publishers.</p>
<h4>4. AI-Generated Content</h4>
<p>Sightline uses AI to analyze data and generate situation reports, summaries, and responses. AI-generated content may contain inaccuracies. Users should verify critical information against original sources. Every AI response includes citations to source documents.</p>
<h4>5. User Conduct</h4>
<ul>
<li>Use the service only for lawful humanitarian analysis purposes</li>
<li>Do not attempt to overwhelm or disrupt the service</li>
<li>Do not misrepresent AI-generated content as official humanitarian guidance</li>
<li>Respect intellectual property rights of data publishers</li>
</ul>
<h4>6. Disclaimer</h4>
<p>Sightline is provided "as is" without warranties of any kind. We make no guarantees about accuracy, completeness, or timeliness of data or AI-generated content. The service is not a substitute for professional humanitarian assessment.</p>
<h4>7. Changes</h4>
<p>We may update these terms at any time. Continued use after changes constitutes acceptance.</p>`,
    privacy: `<h4>Data We Collect</h4>
<ul>
<li><strong>Authentication data:</strong> Google account email and display name when you sign in</li>
<li><strong>Usage data:</strong> Chat messages, SITREP reports, and bulletin requests you create</li>
<li><strong>Analytics:</strong> We do not use third-party analytics or tracking services</li>
</ul>
<h4>Data We Do NOT Collect</h4>
<ul>
<li>We do not sell, share, or distribute your personal data to third parties</li>
<li>We do not use your data for advertising</li>
<li>We do not track your browsing across other websites</li>
<li>We do not collect device fingerprints or location data</li>
</ul>
<h4>Data Storage</h4>
<p>Your chat history and reports are stored securely on our servers and are accessible only to you through your authenticated session. You can delete your data at any time by contacting us.</p>
<h4>Security</h4>
<p>We use industry-standard encryption (HTTPS/TLS) for all data in transit. Authentication is handled through Firebase Auth with Google Sign-In. Access tokens are validated on every request.</p>
<h4>Your Rights</h4>
<ul>
<li>Access your data at any time through the platform</li>
<li>Request deletion of your account and all associated data</li>
<li>Withdraw consent by discontinuing use of the service</li>
</ul>
<h4>Contact</h4>
<p>For privacy inquiries or data deletion requests, please contact us through the platform.</p>`
  };

  function showLegal(type) {
    if (!legalModal || !legalTitle || !legalBody) return;
    legalTitle.textContent = type === 'terms' ? 'Terms of Use' : 'Privacy Policy';
    legalBody.innerHTML = legalContent[type] || '';
    legalModal.classList.add('open');
  }

  if (termsLink) termsLink.addEventListener('click', (e) => { e.preventDefault(); showLegal('terms'); });
  if (privacyLink) privacyLink.addEventListener('click', (e) => { e.preventDefault(); showLegal('privacy'); });
  if (legalClose) legalClose.addEventListener('click', () => { legalModal.classList.remove('open'); });
  if (legalModal) legalModal.addEventListener('click', (e) => { if (e.target === legalModal) legalModal.classList.remove('open'); });

  // Crisis panel close button
  const crisisPanelClose = document.getElementById('dash-crisis-panel-close');
  if (crisisPanelClose) crisisPanelClose.addEventListener('click', closeCrisisPanel);

  // Mobile bottom tab bar
  document.querySelectorAll('.mobile-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Mobile user button (logout)
  const mobileUserBtn = document.getElementById('mobile-user-btn');
  if (mobileUserBtn) {
    mobileUserBtn.addEventListener('click', () => {
      if (typeof signOut === 'function') {
        if (confirm('Sign out of Sightline?')) signOut();
      }
    });
  }

  // Agent DOM refs
  chatInput = document.getElementById('chat-input');
  sendBtn   = document.getElementById('send-btn');
  chatDiv   = document.getElementById('chat-messages');
  busyDot   = document.getElementById('busy-dot');

  // Model selector
  const modelToggle = document.getElementById('model-selector-toggle');
  const modelMenu = document.getElementById('model-menu');
  if (modelToggle && modelMenu) {
    modelToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      modelMenu.classList.toggle('open');
    });
    document.addEventListener('click', () => modelMenu.classList.remove('open'));
    modelMenu.addEventListener('click', (e) => e.stopPropagation());
    modelMenu.querySelectorAll('.model-option').forEach(opt => {
      opt.addEventListener('click', () => {
        const key = opt.dataset.model;
        if (!key) return;
        const cfg = CHAT_MODELS[key];
        if (cfg.premium && window.__userRole !== 'premium' && window.__userRole !== 'admin') {
          toast(`${cfg.name} requires a Premium account`, 'warning');
          return;
        }
        chatState.selectedModel = key;
        const label = document.getElementById('model-selector-label');
        if (label) label.textContent = cfg.name;
        modelMenu.querySelectorAll('.model-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        modelMenu.classList.remove('open');
      });
    });
    // Lock premium models for non-premium users (Ultra + Deep Think)
    if (window.__userRole !== 'premium' && window.__userRole !== 'admin') {
      modelMenu.querySelectorAll('.model-option-premium').forEach(opt => opt.classList.add('locked'));
    }
  }

  // Welcome mode — center content until user sends first message
  const chatMain = chatDiv ? chatDiv.closest('.chat-main') : null;
  if (chatMain) chatMain.classList.add('welcome-mode');

  // ── Static element bindings ────────────────────────────────────────────

  // Sidebar nav
  const sidebar = document.getElementById('sidebar-nav');
  if (sidebar) sidebar.classList.add('collapsed');
  document.body.classList.add('sidebar-collapsed');
  const hamburgerBtn = document.getElementById('hamburger-btn');
  if (hamburgerBtn) hamburgerBtn.addEventListener('click', () => {
    const sb = document.getElementById('sidebar-nav');
    const mn = document.querySelector('.main');
    if (sb) { sb.classList.remove('hidden', 'collapsed'); }
    document.body.classList.remove('sidebar-collapsed');
    if (mn) mn.style.marginLeft = '';
    sidebarJustOpened = true;
    setTimeout(() => { sidebarJustOpened = false; }, 100);
  });

  // Click outside sidebar → collapse it (premium UX)
  let sidebarJustOpened = false;
  const mainEl = document.querySelector('.main');
  if (mainEl) {
    mainEl.addEventListener('click', (e) => {
      if (sidebarJustOpened) { sidebarJustOpened = false; return; }
      const sb = document.getElementById('sidebar-nav');
      if (sb && !sb.classList.contains('collapsed') && !sb.classList.contains('hidden')) {
        sb.classList.add('collapsed');
        document.body.classList.add('sidebar-collapsed');
      }
    });
  }

  // Prevent sidebar clicks from collapsing
  const sidebarEl = document.getElementById('sidebar-nav');
  if (sidebarEl) {
    sidebarEl.addEventListener('click', (e) => e.stopPropagation());
  }

  // Tab buttons — double-click any tab to toggle sidebar
  let lastTabClickTime = 0;
  let lastTabClickTarget = null;
  document.querySelectorAll('.sidebar-tab[data-tab]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const now = Date.now();
      if (lastTabClickTarget === btn && now - lastTabClickTime < 400) {
        e.stopImmediatePropagation();
        toggleSidebarNav();
        lastTabClickTime = 0;
        lastTabClickTarget = null;
        return;
      }
      lastTabClickTime = now;
      lastTabClickTarget = btn;
      switchTab(btn.dataset.tab);
    });
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
  const sidebarToggleBtn = document.getElementById('sidebar-toggle-btn');
  if (sidebarToggleBtn) sidebarToggleBtn.addEventListener('click', toggleChatSidebar);
  // User photo click opens chat sidebar
  const userPhoto = document.getElementById('user-photo');
  if (userPhoto) userPhoto.addEventListener('click', toggleChatSidebar);
  const mobileUserPhoto = document.getElementById('mobile-user-photo');
  if (mobileUserPhoto) mobileUserPhoto.addEventListener('click', toggleChatSidebar);
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
      case 'open-chat-history':
        toggleChatSidebar();
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
          closeCrisisPanel();
          switchTab('sitrep');
          setTimeout(() => {
            const sel = document.getElementById('inp-country');
            if (sel) sel.value = crisisCountry;
          }, 100);
        }
        break;
      case 'switch-report-view':
        switchReportView(target.dataset.mode);
        break;
      case 'view-recent-report':
        const rid = parseInt(target.dataset.reportId, 10);
        if (rid) openDbReport(rid);
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
        closeCrisisPanel();
        viewBulletinSitrep(target.dataset.country);
        break;
      case 'open-sitrep-report':
        openSitrepReport(target.dataset.file, target);
        break;
      case 'toggle-model-menu':
        // Handled by direct event listener above
        break;
    }
  });

  // Admin sub-tab switching (Users / Analytics)
  document.querySelectorAll('.admin-subtab').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.adminTab;
      document.querySelectorAll('.admin-subtab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const usersSec = document.getElementById('admin-users');
      const analyticsSec = document.getElementById('admin-analytics');
      if (tab === 'analytics') {
        if (usersSec) usersSec.style.display = 'none';
        if (analyticsSec) analyticsSec.style.display = '';
        loadAnalytics();
      } else {
        if (analyticsSec) analyticsSec.style.display = 'none';
        if (usersSec) usersSec.style.display = '';
      }
    });
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
  sitrepState.stepStates = new Array(STEPS.length).fill('waiting');
  showSitrepView('welcome');

  // SITREP tag input: Enter key support
  ['country', 'theme'].forEach(field => {
    const inp = document.getElementById(`up-${field}-input`);
    if (!inp) return;
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); tagAdd(field); }
    });
  });

  // Wait for auth before making auth-required API calls
  let _appInited = false;
  let _previewInited = false;

  function initPreviewData() {
    // Freemium preview: load public data without auth
    if (_previewInited) return;
    _previewInited = true;
    console.log('[app] initPreviewData — loading public content for anonymous visitor');
    switchTab('home');
    // loadDashboard() will detect no token and use public endpoints
    loadDashboard();
  }

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

  // Preview mode: load public data immediately (no auth needed)
  if (window.__authReady) {
    initAppData();
  } else {
    // Listen for preview-ready (anonymous visitor — show limited content)
    window.addEventListener('preview-ready', () => {
      console.log('[app] preview-ready event — loading preview data');
      initPreviewData();
    }, { once: true });
    // Listen for auth-ready (user signed in — load full app)
    window.addEventListener('auth-ready', () => {
      console.log('[app] auth-ready event — loading full app');
      // Reload dashboard with authed endpoints
      _previewInited = true; // prevent double-load
      initAppData();
      // Reload dashboard now that we have a token
      setTimeout(() => loadDashboard(), 100);
    }, { once: true });
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
          <button class="bulletin-gen-btn bulletin-gen-inline" data-action="generate-bulletin">Generate Weekly Bulletin</button>
        </div>`;
      return;
    }
    container.innerHTML = bulletins.map((b, i) => {
      const fallbackTag = b.data_date_range?.fallback
        ? ' <span class="severity-warn-icon">⚠</span>'
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
    const colors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
    const labels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
    return `<span class="severity-badge" style="background:${colors[s]||'#6b7280'}22;color:${colors[s]||'#6b7280'};border:1px solid ${colors[s]||'#6b7280'}44">${labels[s]||s.toUpperCase()}</span>`;
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
  `;}).join('');

  const counts = { high: 0, medium: 0, low: 0 };
  allCrises.forEach(c => { if (counts[c.severity] !== undefined) counts[c.severity]++; });

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
