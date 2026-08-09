// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for Sightline
//
// Tab 1: Database  → /api/db/*
// Tab 2: Agent     → /api/agent/chat
// Tab 3: SITREP    → /api/sitrep/*
// ═══════════════════════════════════════════════════════════════════════════

// ── Constants ──────────────────────────────────────────────────────────────
const ADMIN_EMAIL = document.querySelector('meta[name="contact-email"]')?.content || 'support@sightline.ai';
const TAB_NAMES = ['home', 'crisis-map', 'agent', 'sitrep', 'bulletin', 'db', 'proposal', 'admin'];
const DEFAULT_MODEL = 'flash';
const CHAT_MODELS = {
  flash: { name: 'Flash', desc: 'Fast responses', premium: false },
  thinking: { name: 'Thinking', desc: 'Balanced', premium: false },
  ultra: { name: 'Ultra', desc: 'Best quality — Premium', premium: true },
  deep_think: { name: 'Deep Think', desc: 'Deep analysis — Premium', premium: true },
  vision: { name: 'Vision', desc: 'Image + document analysis — Premium', premium: true, vision: true },
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
  mode: 'analyst',         // analyst | proposal | me_reviewer
  proposalId: null,       // active proposal for proposal/review modes
  proposalsLoaded: false,
  attachment: null,       // { name, dataUrl, mime } for Vision model
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
async function api(url, opts = {}) {
  if (!opts.headers) opts.headers = {};
  // Merge existing headers if provided (keep Content-Type etc)
  const tok = typeof getIdToken === 'function' ? getIdToken() : '';
  if (tok) opts.headers['Authorization'] = 'Bearer ' + tok;
  let res = await fetch(url, opts);

  // 401 = token expired → refresh and retry once
  if (res.status === 401 && typeof auth !== 'undefined' && auth.currentUser) {
    try {
      const freshTok = await auth.currentUser.getIdToken(true);
      localStorage.setItem('id_token', freshTok);
      opts.headers['Authorization'] = 'Bearer ' + freshTok;
      res = await fetch(url, opts);
    } catch (e) {
      // Refresh failed — return original 401
    }
  }
  return res;
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
  '\\rightarrow': '→', '\\leftarrow': '←', '\\leftrightarrow': '↔',
  '\\Rightarrow': '⇒', '\\Leftarrow': '⇐', '\\Leftrightarrow': '⇔',
  '\\uparrow': '↑', '\\downarrow': '↓', '\\updownarrow': '↕',
  '\\Uparrow': '⇑', '\\Downarrow': '⇓',
  '\\geq': '≥', '\\leq': '≤', '\\neq': '≠',
  '\\approx': '≈', '\\pm': '±', '\\times': '×',
  '\\div': '÷', '\\infty': '∞', '\\sum': '∑',
  '\\prod': '∏', '\\sqrt': '√', '\\alpha': 'α',
  '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ',
  '\\lambda': 'λ', '\\mu': 'μ', '\\pi': 'π',
  '\\sigma': 'σ', '\\omega': 'ω', '\\theta': 'θ',
  '\\cdot': '·', '\\dots': '…', '\\ldots': '…',
  '\\degree': '°', '\\checkmark': '✓', '\\star': '★',
  '\\triangle': '△', '\\bullet': '•', '\\circ': '○',
  '\\sim': '∼', '\\cong': '≅', '\\propto': '∝',
  '\\in': '∈', '\\notin': '∉', '\\subset': '⊂',
  '\\supset': '⊃', '\\cup': '∪', '\\cap': '∩',
  '\\forall': '∀', '\\exists': '∃', '\\nabla': '∇',
  '\\partial': '∂', '\\emptyset': '∅',
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
_markedRenderer.link = function (href, title, text) {
  // marked v5+ passes an object; v4 passes positional args
  if (typeof href === 'object') { title = href.title; text = href.text; href = href.href; }
  const t = title ? ` title="${esc(title)}"` : '';
  return `<a href="${esc(href)}"${t} target="_blank" rel="noopener noreferrer">${text}</a>`;
};

function md(text) {
  try { return marked.parse(cleanLatex(text), { breaks: true, gfm: true, renderer: _markedRenderer }); }
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
    if (currentTab === 'crisis-map') scheduleWorldMapResize();
  }
}

function switchTab(name) {
  // Freemium preview: gated tabs require auth
  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;
  const GATED_TABS = ['agent', 'sitrep', 'bulletin', 'db', 'proposal', 'admin'];
  if (!isAuthed && GATED_TABS.includes(name)) {
    // Show login panel instead of switching tab
    if (window.showLoginPanel) {
      window.showLoginPanel();
    }
    // Stay on home tab
    return;
  }

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
    document.body.classList.add('sidebar-hidden');
    if (main) main.style.marginLeft = '0';
    if (hamburger) hamburger.style.display = '';
  } else if (name === 'crisis-map') {
    if (sidebar) sidebar.classList.remove('hidden');
    document.body.classList.remove('sidebar-hidden');
    if (sidebar && sidebar.classList.contains('collapsed')) {
      if (main) main.style.marginLeft = '72px';
    } else {
      if (main) main.style.marginLeft = '';
    }
    if (hamburger) hamburger.style.display = '';
  } else {
    if (sidebar) sidebar.classList.remove('hidden');
    document.body.classList.remove('sidebar-hidden');
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

  // Proposal is a dense authoring workspace. Give it the full canvas while
  // keeping the global navigation available from the hamburger button.
  if (name === 'proposal') {
    if (sidebar) sidebar.classList.add('hidden');
    document.body.classList.add('sidebar-hidden');
    document.body.classList.remove('sidebar-collapsed');
    if (main) main.style.marginLeft = '0';
  }

  if (name === 'home') loadCommandCenter();
  if (name === 'crisis-map') {
    // Build and measure Leaflet only after its panel is visible.
    initWorldMap();
    loadDashboard();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// TAB 2 — AGENT CHAT (multi-chat)
// ═══════════════════════════════════════════════════════════════════════════

const QUICK_PROMPTS = [
  { label: "Latest Headlines", text: "What are the latest humanitarian headlines?", cat: "search" },
  { label: "Theme Filter", text: "Find health reports from WHO in the last month", cat: "search" },
  { label: "Disaster Tracker", text: "What ongoing disasters are there in Southeast Asia?", cat: "search" },
  { label: "Displacement Trends", text: "Summarize displacement trends in the Middle East", cat: "kb" },
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

async function loadChatProposals() {
  try {
    const res = await api('/api/proposals');
    const data = await res.json();
    chatState.proposals = Array.isArray(data) ? data : [];
    chatState.proposalsLoaded = true;
  } catch (err) {
    chatState.proposals = [];
  }
}

function showProposalPicker(mode) {
  let picker = document.getElementById('chat-proposal-picker');
  if (!picker) {
    picker = document.createElement('div');
    picker.id = 'chat-proposal-picker';
    picker.style.cssText = 'padding: 6px 16px; background: var(--bg-elevated, var(--bg-card)); border-bottom: 1px solid var(--border-light); display:flex; align-items:center; gap:8px; font-size:12px;';
    const chatScroll = document.querySelector('.chat-footer');
    if (chatScroll && chatScroll.parentNode) {
      chatScroll.parentNode.insertBefore(picker, chatScroll);
    }
  }
  const label = mode === 'me_reviewer' ? 'Review proposal:' : 'Work on proposal:';
  const proposals = chatState.proposals || [];
  let options = '<option value="">— Select —</option>';
  for (const p of proposals) {
    options += `<option value="${p.id}" ${chatState.proposalId === p.id ? 'selected' : ''}>${escHtml(p.title)} (${escHtml(p.country || '?')})</option>`;
  }
  picker.innerHTML = `
    <span style="color:var(--text-muted); white-space:nowrap;">${label}</span>
    <select id="chat-proposal-select" style="flex:1; font-size:12px; padding:4px 8px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg-card); color:var(--text-primary);">
      ${options}
    </select>
  `;
  const sel = document.getElementById('chat-proposal-select');
  if (sel) {
    sel.addEventListener('change', () => {
      chatState.proposalId = sel.value || null;
      if (mode === 'proposal') {
        updateChatPlaceholder('Ask me to write or improve a proposal section...');
      } else {
        updateChatPlaceholder('Ask me to review the proposal...');
      }
    });
  }
  picker.style.display = 'flex';
  if (mode === 'proposal') {
    updateChatPlaceholder('Select a proposal above, then ask me to write or improve sections...');
  } else {
    updateChatPlaceholder('Select a proposal above, then ask me to review it...');
  }
}

function hideProposalPicker() {
  const picker = document.getElementById('chat-proposal-picker');
  if (picker) picker.style.display = 'none';
}

function updateChatPlaceholder(text) {
  const inp = document.getElementById('chat-input');
  if (inp) inp.placeholder = text;
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
    chatDiv.innerHTML = '';
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
  sendBtn.disabled = true;
  sendBtn.innerHTML = '<div class="spin spin-lg"></div>';
  busyDot.classList.add('visible');

  chatState.currentAiEl = addMsg('assistant',
    '<div class="typing-dots"><span></span><span></span><span></span></div>');
  chatState.currentAiText = '';

  try {
    const body = { message: text, model: chatState.selectedModel, mode: chatState.mode };
    if (chatState.proposalId) body.proposal_id = chatState.proposalId;
    if (chatState.attachment) {
      body.attachment = chatState.attachment;
      chatState.attachment = null;
    }

    const resp = await api('/api/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
      // Show a retry button so the user can re-send the message
      if (text) {
        const retryEl = document.createElement('button');
        retryEl.className = 'btn btn-sm btn-retry';
        retryEl.textContent = 'Retry';
        retryEl.onclick = () => {
          retryEl.remove();
          chatInput.value = text;
          sendChatMessage();
        };
        chatState.currentAiEl.appendChild(retryEl);
      }
      return;
    }

    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';

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
    chatState.isStreaming = false;
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M22 2L11 13"/><path d="M22 2L15 22 11 13 2 9l20-7z"/></svg>';
    busyDot.classList.remove('visible');
    chatState.currentAiEl = null;
    chatDiv.scrollTop = chatDiv.scrollHeight;
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

    // Check if there's an empty chat we can reuse (using msg_count)
    const listR = await api('/api/agent/chats');
    const listD = await listR.json();
    const emptyChat = listD.chats.find(c => c.msg_count === 0);
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
      body: JSON.stringify({ country, event, skip_cache: skipCache, date_from: dateFrom, date_to: dateTo }),
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
    const resp = await api(`/api/sitrep/report?file=${encodeURIComponent(filename)}`);
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
  const dateTo = document.getElementById('inp-date-to')?.value || '';

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
  _tags.theme = [];
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
  fd.append('title', document.getElementById('up-title').value.trim());
  fd.append('source', document.getElementById('up-source').value.trim());
  fd.append('format', document.getElementById('up-format').value.trim());
  fd.append('language', document.getElementById('up-language').value);
  fd.append('date', document.getElementById('up-date').value);
  fd.append('country', JSON.stringify(_tags.country));
  fd.append('theme', JSON.stringify(_tags.theme));
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
    data: { labels, datasets: [{ data, backgroundColor: ['#4f9eff', '#ff6b6b', '#4ecdc4', '#f7df1e', '#a55eea', '#fd7e14', '#26de81', '#fc5c65', '#45aaf2', '#fd9644'] }] },
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
let dashboardLoading = false;
let latestBulletinData = null;

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

let ccLoaded = false;

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

  // 2. Recent proposals
  const proposalsContainer = document.getElementById('cc-recent-proposals');
  if (proposalsContainer) {
    if (isAuthed) {
      try {
        const res = await api('/api/proposals');
        const proposals = await res.json();
        if (Array.isArray(proposals)) {
          if (proposals.length > 0) {
            proposalsContainer.innerHTML = proposals.slice(0, 5).map(p =>
              `<div class="cc-recent-item" data-action="cc-open-proposal" data-id="${p.id}" style="font-size:13px; padding:6px 0; cursor:pointer; color:var(--primary); font-weight:500;">
                <span style="display:inline-flex; align-items:center; gap:6px;">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                  ${escHtml(p.title)}
                </span>
              </div>`
            ).join('');
          } else {
            proposalsContainer.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">No proposals yet</div>';
          }
        }
      } catch {
        proposalsContainer.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">Failed to load</div>';
      }
    } else {
      proposalsContainer.innerHTML = '<div style="font-size:12.5px; color:var(--text-secondary);">Sign in to view proposals</div>';
    }
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
  if (!tok || role === 'free') {
    if (window.showLoginPanel) window.showLoginPanel();
    return;
  }
  const sel = document.getElementById('cc-sitrep-country');
  const country = sel ? sel.value : '';
  switchTab('sitrep');
  if (country) {
    setTimeout(() => {
      const inp = document.getElementById('inp-country');
      if (inp) inp.value = country;
    }, 200);
  }
}

function ccStartProposal() {
  switchTab('proposal');
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
              hdx_key_figures: c.hdx_key_figures || {},
              gdacs_alerts: c.gdacs_alerts || [],
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

  // ── Load latest bulletin data (for map markers, not displayed on map page) ──
  const bulletinsUrl = isAuthed ? '/api/sitrep/bulletins' : '/api/public/bulletins';
  const bulletinDetailUrl = isAuthed ? '/api/sitrep/bulletin/' : '/api/public/bulletin/';
  try {
    const r = await api(bulletinsUrl);
    const d = await r.json();
    const bulletins = d.bulletins || d || [];

    if (Array.isArray(bulletins) && bulletins.length > 0) {
      const latest = bulletins[0];
      // Load bulletin detail (used for severity data, etc.)
      try {
        const br = await api(bulletinDetailUrl + latest.filename);
        if (br.ok) {
          latestBulletinData = await br.json();
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  // A failed map request must remain retryable on the next Map visit.
  dashboardLoaded = mapDataLoaded;
  dashboardLoading = false;
  if (currentTab === 'crisis-map') initWorldMap();
}

function renderDashOverview(b) {
  if (!b) return;

  // Key figures for Floating Hero Stats (First 3)
  const heroStatsEl = document.getElementById('dash-hero-stats');
  const bentoStatsEl = document.getElementById('dash-overview-stats');

  if (b.key_figures && b.key_figures.length > 0) {
    // 3 Floating glass panels over map (no longer hidden on mobile, just flex)
    if (heroStatsEl) {
      const heroStats = b.key_figures.slice(0, 3);
      heroStatsEl.innerHTML = heroStats.map((f, idx) => `
        <div class="bg-white/90 backdrop-blur-xl border border-zinc-200/40 shadow-[0_8px_30px_rgba(0,0,0,0.03)] p-6 rounded-2xl flex flex-col justify-end min-h-[130px] transform hover:-translate-y-1 transition-all duration-300 animate-fade-in-up" style="animation-delay: ${idx * 80}ms;">
          <span class="text-3xl lg:text-4xl font-extrabold tracking-tight text-zinc-950 mb-1">${esc(f.value)}</span>
          <span class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">${esc(f.label)}</span>
        </div>
      `).join('');
    }

    // Populate Bento Grid with aggregated metrics from bulletin data
    if (bentoStatsEl) {
      const highSeverityCount = b.crises ? b.crises.filter(c => c.severity === 'high').length : 0;
      const highSeverityReports = b.crises ? b.crises.filter(c => c.severity === 'high').reduce((acc, c) => acc + (c.report_count || 0), 0) : 0;

      const topCountries = b.crises ? [...b.crises].sort((x, y) => (y.report_count || 0) - (x.report_count || 0)).slice(0, 3) : [];
      const topCountriesStr = topCountries.map(c => `${c.country} (${c.report_count})`).join(', ');

      const bentoCards = [
        {
          title: "Critical Hotspots",
          value: `${highSeverityCount} High Severity`,
          subtitle: `${highSeverityReports} reports require urgent action`,
          isLarge: true
        },
        {
          title: "Primary Category",
          value: `${b.top_themes && b.top_themes.length > 0 ? b.top_themes[0] : 'N/A'}`,
          subtitle: "Most active theme",
          isLarge: false
        },
        {
          title: "Data Chunks",
          value: `${b.total_chunks || '—'}`,
          subtitle: "Vector chunks analyzed",
          isLarge: false
        },
        {
          title: "Top Focus Areas",
          value: `${topCountriesStr || 'None'}`,
          subtitle: "Most reported locations",
          isLarge: true
        }
      ];

      bentoStatsEl.innerHTML = bentoCards.map((c, idx) => {
        const isCritical = c.title === "Critical Hotspots";
        const isFocus = c.title === "Top Focus Areas";
        const accentClass = isCritical ? 'text-[#E8364E]' : 'text-zinc-500';
        const titleClass = isCritical ? 'text-[#E8364E]' : (isFocus ? 'text-zinc-600' : 'text-zinc-400');
        const cardBg = isCritical ? 'bg-gradient-to-br from-rose-50/40 to-white' : 'bg-gradient-to-br from-zinc-50/40 to-white';
        const cardBorder = isCritical ? 'border-rose-100/80' : 'border-zinc-200/50';

        return `
          <div class="${cardBg} border ${cardBorder} shadow-[0_4px_20px_rgba(0,0,0,0.01)] p-6 rounded-2xl flex flex-col justify-center ${c.isLarge ? 'col-span-2' : ''} hover:shadow-[0_8px_30px_rgba(0,0,0,0.04)] hover:-translate-y-0.5 transition-all duration-300 animate-fade-in-up" style="animation-delay: ${(idx + 3) * 80}ms;">
            <span class="text-[10px] font-bold ${titleClass} uppercase tracking-wider mb-1">${esc(c.title)}</span>
            <span class="text-xl font-extrabold text-zinc-950 truncate" title="${esc(c.value)}">${esc(c.value)}</span>
            <span class="text-xs text-zinc-500 mt-1">${esc(c.subtitle)}</span>
          </div>
        `;
      }).join('');
    }
  }

  // Weekly overview text
  const textEl = document.getElementById('dash-weekly-text');
  if (textEl) {
    const overview = b.global_overview || '';
    if (overview) {
      const rendered = typeof marked !== 'undefined' ? marked.parse(overview) : `<p>${esc(overview)}</p>`;
      textEl.innerHTML = sanitizeHtml(rendered);
    } else {
      textEl.innerHTML = '<p class="text-gray-500 animate-pulse">No overview available for this week.</p>';
    }
  }
}

function isWorldMapVisible(container = document.getElementById('world-map')) {
  const panel = document.getElementById('panel-crisis-map');
  if (!container || !panel || !panel.classList.contains('active')) return false;
  const rect = container.getBoundingClientRect();
  return rect.width >= 100 && rect.height >= 100;
}

function scheduleWorldMapResize() {
  if (!leafletMap || !isWorldMapVisible()) return;
  if (leafletResizeFrame) cancelAnimationFrame(leafletResizeFrame);
  leafletResizeFrame = requestAnimationFrame(() => {
    leafletResizeFrame = 0;
    if (leafletMap && isWorldMapVisible()) {
      leafletMap.invalidateSize({ animate: false, pan: false });
    }
  });
}

function observeWorldMapSize(container) {
  if (leafletResizeObserver || typeof ResizeObserver === 'undefined') return;
  leafletResizeObserver = new ResizeObserver(() => scheduleWorldMapResize());
  leafletResizeObserver.observe(container);
}

function initWorldMap() {
  const container = document.getElementById('world-map');
  if (!container) return;

  // Leaflet calculates its internal grid from the container's first size.
  // Never initialize it inside a hidden (0 x 0) tab.
  if (!isWorldMapVisible(container)) return;

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
    scheduleWorldMapResize();
    return;
  }

  try {
    leafletMap = L.map(container, {
      center: [20, 15],
      zoom: 3,
      minZoom: 3,
      maxZoom: 8,
      zoomControl: true,
      attributionControl: false,
      worldCopyJump: true,
      scrollWheelZoom: true,
      doubleClickZoom: true,
      dragging: true,
      touchZoom: true,
    });

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(leafletMap);

    // No scroll interception — let Leaflet handle zoom natively
    observeWorldMapSize(container);
    scheduleWorldMapResize();
  } catch (err) {
    console.error('[map] Leaflet init error:', err);
    container.innerHTML = '<div class="center-loading dash-weekly-loading">Map unavailable.</div>';
    return;
  }

  updateMapMarkers();
}

let leafletMarkerGroup = null;   // L.FeatureGroup for all markers (efficient batch ops)

function updateMapMarkers() {
  if (!leafletMap || typeof L === 'undefined') return;

  // Remove previous marker group in one shot
  if (leafletMarkerGroup) {
    leafletMap.removeLayer(leafletMarkerGroup);
  }
  leafletMarkerGroup = L.featureGroup();
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
      .on('click', () => openCountryCard(c));

    leafletMarkerGroup.addLayer(marker);
    leafletMarkers.push(marker);
  });

  // Add entire group to map at once
  leafletMarkerGroup.addTo(leafletMap);

  // Only fit bounds on first load, not on zoom/pan
  if (!window._mapBoundsSet) {
    leafletMap.fitBounds(leafletMarkerGroup.getBounds().pad(0.3));
    window._mapBoundsSet = true;
  }
}

function openCountryCard(crisis) {
  const panel = document.getElementById('dash-crisis-panel');
  const mapEl = document.getElementById('world-map');
  const countryEl = document.getElementById('dash-crisis-panel-country');
  const bodyEl = document.getElementById('dash-crisis-panel-body');
  if (!panel || !countryEl || !bodyEl) return;

  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;
  const country = crisis.country || '';
  const sevColors = { high: '#ef4444', medium: '#f59e0b', low: '#22c55e' };
  const sevLabels = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' };
  const color = sevColors[crisis.severity] || '#007AFF';

  // Look up full data from mapCountries
  const fullData = mapCountries[country] || {};
  const lastUpdated = fullData.last_updated || crisis.last_updated || '';
  const hasSummary = fullData.has_summary || crisis.has_summary || false;

  countryEl.textContent = country;

  // Show loading state
  bodyEl.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);">Loading country intelligence...</div>';
  panel.classList.add('open');
  // Note: don't add panel-open class to map — it causes resize/marker lag
  // The crisis panel overlays the map absolutely, no layout shift needed

  // If we have full summary data from /api/map/countries, render immediately
  if (hasSummary && fullData.narrative) {
    renderCountryCard(bodyEl, fullData, color, sevLabels);
  } else if (isAuthed) {
    // Authed: fetch full country summary
    api('/api/country/' + encodeURIComponent(country) + '/summary')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data) {
          renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
          return;
        }
        renderCountryCard(bodyEl, data, color, sevLabels);
      })
      .catch(() => {
        renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
      });
  } else {
    // Preview mode: show what we have from map data + register prompt
    renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels);
  }
}

function renderCountryCard(bodyEl, data, color, sevLabels) {
  let html = '';
  const severity = data.severity || 'low';

  html += `<span class="crisis-severity-badge" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[severity] || ''}</span>`;

  // Last updated date
  const lastUpdated = data.last_updated || (data.date_range && data.date_range.max_date) || '';
  if (lastUpdated) {
    const dateStr = lastUpdated.length > 10 ? lastUpdated.substring(0, 10) : lastUpdated;
    html += `<div class="crisis-meta" style="margin-bottom:8px;"><span class="crisis-meta-item" style="color:var(--text-muted);font-size:11px;">Updated ${esc(dateStr)}</span>`;
    if (data.report_count) html += `<span class="crisis-meta-item" style="font-size:11px;"><strong>${data.report_count}</strong> reports</span>`;
    html += `</div>`;
  }

  if (data.headline) {
    html += `<div class="crisis-headline">${esc(data.headline)}</div>`;
  }

  if (data.narrative) {
    html += `<div class="crisis-summary">${esc(data.narrative)}</div>`;
  }

  if (data.hdx_key_figures && data.hdx_key_figures.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Key Figures</div>`;
    html += `<div class="country-card-figures">`;
    data.hdx_key_figures.forEach(f => {
      html += `<div class="country-card-figure"><span class="country-card-figure-value">${esc(String(f.value || ''))}</span><span class="country-card-figure-label">${esc(f.label || '')}</span></div>`;
    });
    html += `</div></div>`;
  }

  if (data.gdacs_alerts && data.gdacs_alerts.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Active Alerts</div>`;
    data.gdacs_alerts.forEach(a => {
      const alertColor = a.alert_level === 'Red' ? '#ef4444' : a.alert_level === 'Orange' ? '#f59e0b' : '#22c55e';
      html += `<div class="country-card-alert"><span class="country-card-alert-badge" style="background:${alertColor}1a;color:${alertColor};">${esc(a.alert_level || '')}</span> ${esc(a.event_type || '')} — ${esc(a.title || '')}</div>`;
    });
    html += `</div>`;
  }

  if (data.top_themes && data.top_themes.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Themes</div>`;
    html += `<div class="crisis-themes">${data.top_themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
    html += `</div>`;
  }

  if (data.recent_reports && data.recent_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Recent Reports</div>`;
    html += `<div class="country-card-reports">`;
    data.recent_reports.slice(0, 5).forEach(r => {
      html += `<div class="country-card-report"><a href="${esc(r.url || '#')}" target="_blank" rel="noopener">${esc(r.title || '')}</a><span class="country-card-report-meta">${esc(r.date || '')} · ${esc(r.source || '')}</span></div>`;
    });
    html += `</div></div>`;
  }

  if (data.worldbank_indicators && Object.keys(data.worldbank_indicators).length > 0) {
    const wbLabels = {
      gdp_per_capita: 'GDP per capita (USD)',
      population: 'Population',
      life_expectancy: 'Life expectancy (years)',
      poverty_rate: 'Poverty rate (%)',
      electricity_access: 'Electricity access (%)',
    };
    html += `<div class="country-card-section"><div class="country-card-section-title">Country Profile</div>`;
    html += `<div class="country-card-figures">`;
    for (const [key, val] of Object.entries(data.worldbank_indicators)) {
      if (val && val.value) {
        const label = wbLabels[key] || key.replace(/_/g, ' ');
        html += `<div class="country-card-figure"><span class="country-card-figure-value">${esc(String(val.value))}</span><span class="country-card-figure-label">${esc(label)} · ${esc(val.year || '')}</span></div>`;
      }
    }
    html += `</div></div>`;
  }

  if (data.sitrep_reports && data.sitrep_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">SITREP Reports</div>`;
    data.sitrep_reports.forEach(f => {
      html += `<div class="country-card-report"><a href="#" onclick="switchTab('sitrep');setTimeout(()=>{document.querySelectorAll('#sitrep-reports-list .report-item').forEach(i=>{if(i.textContent.includes('${esc(data.country)}'))i.click()})},300);return false;">${esc(f)}</a></div>`;
    });
    html += `</div>`;
  }

  bodyEl.innerHTML = html;
}

function renderCrisisPanelContent(bodyEl, crisis, isAuthed, color, sevLabels) {
  let html = '';
  html += `<span class="crisis-severity-badge" style="background:${color}1a;color:${color};border:1px solid ${color}44">${sevLabels[crisis.severity] || ''}</span>`;
  if (crisis.headline) html += `<div class="crisis-headline">${esc(crisis.headline)}</div>`;
  if (crisis.summary || crisis.narrative) html += `<div class="crisis-summary">${esc(crisis.summary || crisis.narrative)}</div>`;
  html += `<div class="crisis-meta">`;
  if (crisis.report_count) html += `<span class="crisis-meta-item"><strong>${crisis.report_count}</strong> reports</span>`;
  // Show last updated date
  const lastUpdated = crisis.last_updated || (crisis.date_range && crisis.date_range.max_date) || '';
  if (lastUpdated) {
    const dateStr = lastUpdated.length > 10 ? lastUpdated.substring(0, 10) : lastUpdated;
    html += `<span class="crisis-meta-item" style="color:var(--text-muted);">Updated ${esc(dateStr)}</span>`;
  }
  html += `</div>`;
  if (crisis.themes && crisis.themes.length) {
    html += `<div class="crisis-themes">${crisis.themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
  } else if (crisis.top_themes && crisis.top_themes.length) {
    html += `<div class="crisis-themes">${crisis.top_themes.map(t => `<span class="crisis-theme-tag">${esc(t)}</span>`).join('')}</div>`;
  }
  // Show recent reports (from map data)
  if (crisis.recent_reports && crisis.recent_reports.length > 0) {
    html += `<div class="country-card-section"><div class="country-card-section-title">Latest Reports</div>`;
    html += `<div class="country-card-reports">`;
    crisis.recent_reports.slice(0, 3).forEach(r => {
      html += `<div class="country-card-report"><a href="${esc(r.url || '#')}" target="_blank" rel="noopener">${esc(r.title || '')}</a><span class="country-card-report-meta">${esc(r.date || '')} · ${esc(r.source || '')}</span></div>`;
    });
    html += `</div></div>`;
  }
  if (!isAuthed) {
    html += `<div class="preview-lock-msg"><div class="preview-lock-text">Register to view report sources and full SITREP analysis.</div><button class="preview-lock-btn">Register</button></div>`;
  } else if (crisis.has_sitrep) {
    html += `<button class="crisis-sitrep-btn" data-action="dash-view-crisis" data-country="${esc(crisis.country)}">View SITREP →</button>`;
  }
  bodyEl.innerHTML = html;
}

function closeCrisisPanel() {
  const panel = document.getElementById('dash-crisis-panel');
  const mapEl = document.getElementById('world-map');
  if (panel) panel.classList.remove('open');
  // No panel-open class to remove — map stays full-screen
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
  // Menu navigation hint tooltip logic (appears on load, fades out after 5s or on click)
  const menuHint = document.getElementById('menu-hint-tooltip');
  if (menuHint) {
    setTimeout(() => {
      menuHint.classList.add('visible');
    }, 600);

    const hideHint = () => {
      menuHint.classList.remove('visible');
    };

    setTimeout(hideHint, 5000);
    const hamBtn = document.getElementById('hamburger-btn');
    if (hamBtn) hamBtn.addEventListener('click', hideHint, { once: true });
    document.addEventListener('click', hideHint, { once: true });
  }

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

  // Country search on map
  const searchInput = document.getElementById('map-search-input');
  if (searchInput) {
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => {
        const query = e.target.value.toLowerCase().trim();
        if (!query || !leafletMap) return;
        for (const [country, data] of Object.entries(crisisMapData)) {
          if (country.toLowerCase().includes(query)) {
            const coords = data.coords || { lat: 0, lng: 0 };
            if (coords.lat && coords.lng) {
              leafletMap.setView([coords.lat, coords.lng], 5);
              openCountryCard(data);
              break;
            }
          }
        }
      }, 300);
    });
  }

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
  sendBtn = document.getElementById('send-btn');
  chatDiv = document.getElementById('chat-messages');
  busyDot = document.getElementById('busy-dot');

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
  // On initial load, home is default, so sidebar starts hidden
  document.body.classList.add('sidebar-hidden');
  const hamburgerBtn = document.getElementById('hamburger-btn');
  if (hamburgerBtn) hamburgerBtn.addEventListener('click', () => {
    const sb = document.getElementById('sidebar-nav');
    const mn = document.querySelector('.main');
    if (sb) { sb.classList.remove('hidden', 'collapsed'); }
    document.body.classList.remove('sidebar-collapsed');
    document.body.classList.remove('sidebar-hidden');
    if (mn) mn.style.marginLeft = '';
    sidebarJustOpened = true;
    setTimeout(() => { sidebarJustOpened = false; }, 100);
  });

  // Click outside sidebar → hide it completely (premium UX)
  let sidebarJustOpened = false;
  const mainEl = document.querySelector('.main');
  if (mainEl) {
    mainEl.addEventListener('click', (e) => {
      if (sidebarJustOpened) { sidebarJustOpened = false; return; }
      const sb = document.getElementById('sidebar-nav');
      if (sb && !sb.classList.contains('hidden')) {
        sb.classList.add('hidden');
        document.body.classList.add('sidebar-hidden');
        if (mainEl) mainEl.style.marginLeft = '0';
        setTimeout(() => { if (leafletMap) leafletMap.invalidateSize(); }, 150);
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

  // Attach image for Vision model
  const attachBtn = document.getElementById('attach-btn');
  const attachInput = document.getElementById('attach-input');
  if (attachBtn && attachInput) {
    attachBtn.addEventListener('click', () => {
      if (chatState.selectedModel !== 'vision') {
        toast('Select the Vision model to attach an image (Premium)', 'warning');
        return;
      }
      attachInput.click();
    });
    attachInput.addEventListener('change', () => {
      const file = attachInput.files && attachInput.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        chatState.attachment = { name: file.name, mime: file.type || 'application/octet-stream', dataUrl: reader.result };
        toast(`📎 ${file.name} attached`, 'success', 3000);
      };
      reader.readAsDataURL(file);
      attachInput.value = '';
    });
  }

  // Mode selector
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const mode = btn.dataset.mode;
      chatState.mode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      if (mode === 'proposal' || mode === 'me_reviewer') {
        if (!chatState.proposalsLoaded) {
          await loadChatProposals();
        }
        showProposalPicker(mode);
      } else {
        hideProposalPicker();
        updateChatPlaceholder('Message Sightline...');
      }
    });
  });

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

  // Mount the established Proposal design against the Guided V2 setup store.
  // The legacy proposals table remains intact for migration/export safety but
  // is no longer loaded into this workspace.
  initGuidedProposalPipelineActive();

  // ── Event delegation for dynamic elements ──────────────────────────────
  document.addEventListener('click', e => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.dataset.action;

    switch (action) {
      case 'quick-prompt':
        sendQuickPrompt(target.dataset.text);
        break;
      case 'select-proposal':
        selectProposal(target.dataset.id);
        break;
      case 'delete-proposal':
        e.stopPropagation();
        deleteProposalItem(target.dataset.id);
        break;
      case 'open-rag-drawer':
        openRagDrawer(parseInt(target.dataset.index));
        break;
      case 'edit-toc-node':
        editTocNode(parseInt(target.dataset.index));
        break;
      case 'open-smart-scorecard':
        openSmartScorecard(target.dataset.level, target);
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
      case 'create-new-proposal':
        switchTab('proposal');
        break;
      case 'generate-toc':
        generateSection('toc');
        break;
      case 'generate-logframe':
        generateSection('logframe');
        break;
      case 'generate-narrative':
        generateSection('final_review');
        break;
      case 'generate-section':
        generateSection(target.dataset.step);
        break;
      case 'save-section':
        saveSectionManual(target.dataset.step);
        break;
      case 'approve-section':
        approveSection(target.dataset.step);
        break;
      case 'skip-section':
        skipSection(target.dataset.step);
        break;
      case 'wizard-select-step':
        wizardSelectStep(target.dataset.step);
        break;
      case 'proposal-view-mode':
        window.toggleProposalViewMode(target.dataset.step, target.dataset.mode);
        break;
      case 'open-diff-modal':
        openDiffModal();
        break;
      case 'discuss-sitrep':
        discussSitrepWithAgent();
        break;
      case 'proposal-from-sitrep':
        createProposalFromSitrep(target.dataset);
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
      case 'cc-start-sitrep':
        ccStartSitrep();
        break;
      case 'cc-start-proposal':
        ccStartProposal();
        break;
      case 'cc-start-bulletin':
        ccStartBulletin();
        break;
      case 'cc-open-crisis-map':
        switchTab('crisis-map');
        break;
      case 'cc-open-db':
        switchTab('db');
        break;
      case 'cc-open-agent':
        switchTab('agent');
        break;
      case 'cc-open-proposal':
        selectProposal(target.dataset.id);
        switchTab('proposal');
        break;
      case 'cc-open-sitrep':
        const file = target.dataset.file;
        switchTab('sitrep');
        setTimeout(() => {
          const itemEl = document.querySelector(`#sitrep-reports-list .report-item[data-file="${file}"]`);
          if (itemEl) {
            itemEl.click();
          } else {
            openSitrepReport(file);
          }
        }, 150);
        break;
      case 'cc-open-bulletin':
        const bFile = target.dataset.file;
        switchTab('bulletin');
        setTimeout(() => {
          const itemEl = document.querySelector(`#bulletin-tabs .bulletin-tab-pill[data-filename="${bFile}"]`);
          if (itemEl) {
            itemEl.click();
          } else {
            openBulletin(bFile);
          }
        }, 150);
        break;
      case 'toggle-cc-acc':
        const targetId = target.dataset.target;
        const targetCard = document.getElementById(targetId);
        if (targetCard) {
          const isOpen = targetCard.classList.contains('open');
          document.querySelectorAll('.cc-acc-card').forEach(card => card.classList.remove('open'));
          if (!isOpen) {
            targetCard.classList.add('open');
          }
        }
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
    // Login required but app visible behind overlay
    if (_previewInited) return;
    _previewInited = true;
    console.log('[app] initPreviewData — showing app with login overlay');
    // Load Command Center (visible behind login panel)
    switchTab('home');
    loadCommandCenter();
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
      console.log('[app] preview-ready event — forcing login');
      initPreviewData();
    }, { once: true });
    // Listen for auth-ready (user signed in — load full app)
    window.addEventListener('auth-ready', () => {
      console.log('[app] auth-ready event — loading full app after sign-in');
      _previewInited = true; // prevent double-load
      // Reset dashboard loaded flag so it reloads with authed endpoints
      dashboardLoaded = false;
      initAppData();
      // Reload dashboard now that we have a token — force reload
      setTimeout(() => {
        dashboardLoaded = false;
        loadDashboard();
        // Also load chat list and other authed data
        loadChatList();
      }, 100);
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

// ═══════════════════════════════════════════════════════════════════════════
// FREEMIUM PREVIEW — login panel controls
// ═══════════════════════════════════════════════════════════════════════════

// Close button removed — login is required, no dismiss option
document.addEventListener('DOMContentLoaded', () => {
  // No close button — user must sign in
});

// Register buttons inside crisis panel (delegated — works for dynamically added elements)
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.preview-lock-btn');
  if (!btn) return;
  e.preventDefault();
  e.stopPropagation();
  const el = document.getElementById('auth-overlay');
  if (el) {
    el.classList.remove('hidden');
    el.classList.add('slide-in');
    el.style.display = '';
  }
});

// ── Proposal Wizard — Step-by-step donor proposal generator ──
const OPTIONAL_STEPS = [];

const PROPOSAL_STEPS = [
  { key: 'setup', label: 'Project Setup', num: 1 },
  { key: 'context', label: 'Context & Needs', num: 2 },
  { key: 'technical', label: 'Technical Design', num: 3 },
  { key: 'financial', label: 'Commitments & Financials', num: 4 },
  { key: 'review', label: 'Final Review & Export', num: 5 },
];

let proposalState = {
  activeProposalId: null,
  currentStep: 'cover',
  proposals: [],
  activeProposal: null,
  dbCountries: [],
  generating: false,
};

let proposalSaveTimeout;
function debouncedSaveProposal() {
  clearTimeout(proposalSaveTimeout);
  proposalSaveTimeout = setTimeout(saveActiveProposal, 1000);
}

async function initProposalPipeline() {
  const btnNew = document.getElementById('btn-new-proposal');
  const btnCreateFirst = document.getElementById('btn-create-first-proposal');
  const btnExport = document.getElementById('btn-proposal-export');
  const btnExportPdf = document.getElementById('btn-proposal-export-pdf');
  const btnRunReview = document.getElementById('btn-run-review');

  if (btnNew) btnNew.addEventListener('click', createNewProposal);
  if (btnCreateFirst) btnCreateFirst.addEventListener('click', createNewProposal);
  if (btnExport) btnExport.addEventListener('click', exportProposalMarkdown);
  if (btnExportPdf) btnExportPdf.addEventListener('click', exportProposalPDF);
  if (btnRunReview) btnRunReview.addEventListener('click', runProposalReview);

  // Sidebar Toggles & Focus Mode
  const btnTogglePropSidebar = document.getElementById('btn-toggle-proposal-sidebar');
  const btnToggleStepsSidebar = document.getElementById('btn-toggle-steps-sidebar');
  const btnTogglePropChat = document.getElementById('btn-toggle-proposal-chat');
  const btnToggleLeftSidebars = document.getElementById('btn-toggle-left-sidebars');
  const btnFocusMode = document.getElementById('btn-focus-mode');
  const chatCollapsedBar = document.getElementById('proposal-chat-collapsed-bar');

  const propSidebar = document.getElementById('proposal-sidebar');
  const stepsSidebar = document.getElementById('wizard-steps-sidebar');
  const chatPanel = document.getElementById('proposal-advisor-panel');
  const propPage = document.getElementById('proposal-page');
  const propWorkspace = document.getElementById('proposal-workspace');
  let proposalPreChatState = null;

  if (btnTogglePropSidebar && propSidebar) {
    btnTogglePropSidebar.addEventListener('click', () => {
      propSidebar.classList.toggle('collapsed');
    });
  }

  if (btnToggleStepsSidebar && stepsSidebar) {
    btnToggleStepsSidebar.addEventListener('click', () => {
      stepsSidebar.classList.toggle('collapsed');
    });
  }

  const syncProposalControls = () => {
    const chatOpen = !!chatPanel && !chatPanel.classList.contains('collapsed');
    const leftOpen = (!!propSidebar && !propSidebar.classList.contains('collapsed')) ||
      (!!stepsSidebar && !stepsSidebar.classList.contains('collapsed'));
    btnToggleLeftSidebars?.classList.toggle('active', leftOpen);
    btnToggleLeftSidebars?.setAttribute('aria-pressed', String(leftOpen));
  };

  const toggleReviewPanelLegacy = () => {
    if (!chatPanel) return;
    const willOpen = chatPanel.classList.contains('collapsed');
    const isCompact = window.matchMedia('(max-width: 760px)').matches;
    if (willOpen && !isCompact) {
      proposalPreChatState = {
        proposalCollapsed: !!propSidebar?.classList.contains('collapsed'),
        stepsCollapsed: !!stepsSidebar?.classList.contains('collapsed'),
      };
      propSidebar?.classList.add('collapsed');
      stepsSidebar?.classList.add('collapsed');
    }
    chatPanel.classList.toggle('collapsed', !willOpen);
    propWorkspace?.classList.toggle('chat-open', willOpen);
    if (!willOpen && proposalPreChatState && !isCompact) {
      propSidebar?.classList.toggle('collapsed', proposalPreChatState.proposalCollapsed);
      stepsSidebar?.classList.toggle('collapsed', proposalPreChatState.stepsCollapsed);
      proposalPreChatState = null;
    }
    syncProposalControls();
  };

  if (btnTogglePropChat) btnTogglePropChat.addEventListener('click', toggleReviewPanelLegacy);
  if (chatCollapsedBar) chatCollapsedBar.addEventListener('click', toggleReviewPanelLegacy);

  if (btnToggleLeftSidebars) {
    btnToggleLeftSidebars.addEventListener('click', () => {
      if (window.matchMedia('(max-width: 760px)').matches) {
        propSidebar?.classList.toggle('collapsed');
        syncProposalControls();
        return;
      }
      const isAnyOpen = !propSidebar?.classList.contains('collapsed') || !stepsSidebar?.classList.contains('collapsed');
      if (isAnyOpen) {
        propSidebar?.classList.add('collapsed');
        stepsSidebar?.classList.add('collapsed');
      } else {
        propSidebar?.classList.remove('collapsed');
        stepsSidebar?.classList.remove('collapsed');
      }
      syncProposalControls();
    });
  }

  let proposalPreFocusState = null;
  const setFocusButtonState = (focused) => {
    btnFocusMode?.classList.toggle('active', focused);
    btnFocusMode?.setAttribute('aria-pressed', String(focused));
    const label = btnFocusMode?.querySelector('span');
    if (label) label.textContent = focused ? 'Exit Focus' : 'Focus Mode';
    if (btnFocusMode) btnFocusMode.title = focused ? 'Exit Full Screen Focus Mode' : 'Full Screen Document Focus Mode';
  };

  const leaveProposalFocus = ({ exitFullscreen = true } = {}) => {
    if (!propPage?.classList.contains('focus-mode')) return;
    propPage.classList.remove('focus-mode');
    if (proposalPreFocusState) {
      propSidebar?.classList.toggle('collapsed', proposalPreFocusState.proposalCollapsed);
      stepsSidebar?.classList.toggle('collapsed', proposalPreFocusState.stepsCollapsed);
      chatPanel?.classList.toggle('collapsed', proposalPreFocusState.chatCollapsed);
    }
    proposalPreFocusState = null;
    setFocusButtonState(false);
    syncProposalControls();
    if (exitFullscreen && document.fullscreenElement === propPage) {
      document.exitFullscreen().catch(() => {});
    }
  };

  if (btnFocusMode) {
    btnFocusMode.addEventListener('click', async () => {
      const isFocused = propPage?.classList.contains('focus-mode');
      if (isFocused) {
        leaveProposalFocus();
      } else {
        proposalPreFocusState = {
          proposalCollapsed: !!propSidebar?.classList.contains('collapsed'),
          stepsCollapsed: !!stepsSidebar?.classList.contains('collapsed'),
          chatCollapsed: !!chatPanel?.classList.contains('collapsed'),
        };
        propPage?.classList.add('focus-mode');
        setFocusButtonState(true);
        if (propPage?.requestFullscreen && !document.fullscreenElement) {
          try { await propPage.requestFullscreen(); } catch (_) { /* CSS focus mode remains available. */ }
        }
      }
    });
  }

  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && propPage?.classList.contains('focus-mode')) {
      leaveProposalFocus({ exitFullscreen: false });
    }
  });

  // Keep the document wide by default. The advisor stays one click away as an
  // overlay and compact screens start with the proposal drawer tucked away.
  chatPanel?.classList.add('collapsed');
  propWorkspace?.classList.remove('chat-open');
  if (window.matchMedia('(max-width: 760px)').matches) propSidebar?.classList.add('collapsed');
  syncProposalControls();

  const createModal = document.getElementById('proposal-create-modal');
  const closeBtn = document.getElementById('proposal-create-modal-close-btn');
  const createForm = document.getElementById('proposal-create-form');
  if (closeBtn) closeBtn.addEventListener('click', () => createModal.classList.remove('open'));
  if (createForm) {
    createForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const title = document.getElementById('prop-create-title').value.trim();
      const country = document.getElementById('prop-create-country').value;
      const donor = document.getElementById('prop-create-donor').value;
      const themeChecks = document.querySelectorAll('#prop-create-themes-check input[type="checkbox"]:checked');
      const themes = Array.from(themeChecks).map(cb => cb.value);
      const briefing = document.getElementById('prop-create-briefing').value.trim();
      const referenceFiles = document.getElementById('prop-create-reference').files;
      createModal.classList.remove('open');
      await executeCreateProposal({ title, country, donor, themes, briefing, referenceFiles });
    });
  }

  // Event delegation for editable proposal elements
  const workspace = document.getElementById('panel-proposal');
  if (workspace) {
    workspace.addEventListener('input', (e) => {
      if (!proposalState.activeProposal) return;
      const target = e.target;

      if (target.classList.contains('cover-input')) {
        const field = target.dataset.field;
        if (!proposalState.activeProposal.cover_page) proposalState.activeProposal.cover_page = {};
        proposalState.activeProposal.cover_page[field] = target.value;
        debouncedSaveProposal();
      }

      if (target.classList.contains('logframe-input')) {
        const field = target.dataset.field;
        if (!proposalState.activeProposal.logframe) proposalState.activeProposal.logframe = {};
        proposalState.activeProposal.logframe[field] = target.value;
        debouncedSaveProposal();
      }

      if (target.classList.contains('budget-meta-input')) {
        const meta = target.dataset.meta;
        if (!proposalState.activeProposal.budget) proposalState.activeProposal.budget = {};
        proposalState.activeProposal.budget[meta] = target.value;
        debouncedSaveProposal();
      }

      if (target.classList.contains('budget-line-input')) {
        const tr = target.closest('tr');
        const idx = parseInt(tr.dataset.index);
        const field = target.dataset.field;
        if (proposalState.activeProposal.budget && Array.isArray(proposalState.activeProposal.budget.lines)) {
          proposalState.activeProposal.budget.lines[idx][field] = target.value;
          debouncedSaveProposal();
        }
      }

      if (target.classList.contains('mne-approach-input')) {
        if (!proposalState.activeProposal.mne_framework) proposalState.activeProposal.mne_framework = {};
        proposalState.activeProposal.mne_framework.framework_approach = target.value;
        debouncedSaveProposal();
      }

      if (target.classList.contains('mne-indicator-input') && target.tagName !== 'SELECT') {
        const tr = target.closest('tr');
        const idx = parseInt(tr.dataset.index);
        const field = target.dataset.field;
        if (proposalState.activeProposal.mne_framework && Array.isArray(proposalState.activeProposal.mne_framework.indicators)) {
          proposalState.activeProposal.mne_framework.indicators[idx][field] = target.value;
          debouncedSaveProposal();
        }
      }

      if (target.classList.contains('risk-item-input') && target.tagName !== 'SELECT') {
        const card = target.closest('.risk-detail-card');
        const idx = card ? parseInt(card.dataset.index) : -1;
        const field = target.dataset.field;
        if (idx >= 0 && Array.isArray(proposalState.activeProposal.risk_matrix)) {
          proposalState.activeProposal.risk_matrix[idx][field] = target.value;
          debouncedSaveProposal();
        }
      }

      if (target.classList.contains('toc-node-input') && target.tagName !== 'SELECT') {
        const tr = target.closest('tr');
        const idx = parseInt(tr.dataset.index);
        const field = target.dataset.field;
        if (Array.isArray(proposalState.activeProposal.toc)) {
          proposalState.activeProposal.toc[idx][field] = target.value;
          debouncedSaveProposal();
        }
      }
    });

    workspace.addEventListener('change', (e) => {
      if (!proposalState.activeProposal) return;
      const target = e.target;

      if (target.classList.contains('mne-indicator-input') && target.tagName === 'SELECT') {
        const tr = target.closest('tr');
        const idx = parseInt(tr.dataset.index);
        const field = target.dataset.field;
        proposalState.activeProposal.mne_framework.indicators[idx][field] = target.value;
        debouncedSaveProposal();
      }

      if (target.classList.contains('risk-item-input') && target.tagName === 'SELECT') {
        const card = target.closest('.risk-detail-card');
        const idx = card ? parseInt(card.dataset.index) : -1;
        const field = target.dataset.field;
        if (idx >= 0 && Array.isArray(proposalState.activeProposal.risk_matrix)) {
          proposalState.activeProposal.risk_matrix[idx][field] = target.value;
          // Re-render to update heatmap position
          renderSectionContent('risk_matrix');
          debouncedSaveProposal();
        }
      }

      if (target.classList.contains('toc-node-input') && target.tagName === 'SELECT') {
        const tr = target.closest('tr');
        const idx = parseInt(tr.dataset.index);
        const field = target.dataset.field;
        proposalState.activeProposal.toc[idx][field] = target.value;
        debouncedSaveProposal();
      }
    });

    workspace.addEventListener('click', async (e) => {
      if (!proposalState.activeProposal) return;
      const target = e.target.closest('[data-action]');
      if (!target) return;
      const action = target.dataset.action;
      const step = proposalState.currentStep;

      if (action === 'add-budget-line') {
        if (!proposalState.activeProposal.budget) proposalState.activeProposal.budget = {};
        if (!Array.isArray(proposalState.activeProposal.budget.lines)) proposalState.activeProposal.budget.lines = [];
        proposalState.activeProposal.budget.lines.push({ category: '', amount: '', percentage: '' });
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'delete-budget-line') {
        const idx = parseInt(target.dataset.index);
        proposalState.activeProposal.budget.lines.splice(idx, 1);
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'add-mne-indicator') {
        if (!proposalState.activeProposal.mne_framework) proposalState.activeProposal.mne_framework = {};
        if (!Array.isArray(proposalState.activeProposal.mne_framework.indicators)) proposalState.activeProposal.mne_framework.indicators = [];
        proposalState.activeProposal.mne_framework.indicators.push({ name: '', type: 'output', baseline: '', target: '', source: '' });
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'delete-mne-indicator') {
        const idx = parseInt(target.dataset.index);
        proposalState.activeProposal.mne_framework.indicators.splice(idx, 1);
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'add-risk') {
        if (!Array.isArray(proposalState.activeProposal.risk_matrix)) proposalState.activeProposal.risk_matrix = [];
        proposalState.activeProposal.risk_matrix.push({ risk: '', probability: 'Medium', impact: 'Medium', mitigation: '' });
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'delete-risk') {
        const idx = parseInt(target.dataset.index);
        proposalState.activeProposal.risk_matrix.splice(idx, 1);
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'add-toc-node' || action === 'add-toc-node-svg') {
        if (!Array.isArray(proposalState.activeProposal.toc)) proposalState.activeProposal.toc = [];
        let level = 'output';
        if (action === 'add-toc-node-svg') {
          const sel = document.getElementById('toc-new-level');
          if (sel) level = sel.value;
        }
        proposalState.activeProposal.toc.push({ level, text: '' });
        renderSectionContent(step);
        await saveActiveProposal();
      }

      if (action === 'delete-toc-node') {
        const idx = parseInt(target.dataset.index);
        proposalState.activeProposal.toc.splice(idx, 1);
        renderSectionContent(step);
        await saveActiveProposal();
      }
    });
  }

  await fetchDbCountries();
  await fetchProposals();
}

async function fetchDbCountries() {
  try {
    const res = await api('/api/db/countries');
    const data = await res.json();
    proposalState.dbCountries = data || [];
  } catch (err) { proposalState.dbCountries = []; }
}

async function fetchProposals() {
  try {
    const res = await api('/api/proposals');
    const data = await res.json();
    proposalState.proposals = Array.isArray(data) ? data : [];
    renderProposalList();
  } catch (err) { proposalState.proposals = []; renderProposalList(); }
}

async function createProposalFromSitrep(dataset) {
  const country = dataset.country || '';
  const event = dataset.event || '';
  const themes = dataset.themes ? dataset.themes.split(',') : [];
  const dateFrom = dataset.dateFrom || '';
  const dateTo = dataset.dateTo || '';
  switchTab('proposal');
  try {
    const res = await api('/api/proposals/new', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: `${country} ${event ? '- ' + event : ''} Proposal`, country, event, themes, donor: 'ECHO', date_from: dateFrom, date_to: dateTo })
    });
    const newProp = await res.json();
    if (newProp.error) throw new Error(newProp.error);
    proposalState.proposals.unshift(newProp);
    proposalState.activeProposalId = newProp.id;
    proposalState.activeProposal = newProp;
    proposalState.currentStep = newProp.current_step || 'cover';
    renderProposalList();
    renderProposalWorkspace();
    if (window.renderPinnedSourcesList) window.renderPinnedSourcesList();
  } catch (err) { alert("Could not create proposal: " + err.message); }
}

function createNewProposal() {
  const createModal = document.getElementById('proposal-create-modal');
  if (!createModal) return;
  const select = document.getElementById('prop-create-country');
  if (select && proposalState.dbCountries) {
    select.innerHTML = '<option value="">— Select Country —</option>' + proposalState.dbCountries.map(c => `<option value="${escHtml(c)}">${escHtml(c)}</option>`).join('');
  }
  document.getElementById('prop-create-title').value = '';
  document.querySelectorAll('#prop-create-themes-check input[type="checkbox"]').forEach(cb => cb.checked = false);
  createModal.classList.add('open');
}
async function executeCreateProposal({ title, country, donor, themes, briefing, referenceFiles }) {
  try {
    const body = { title, country, event: 'Emergency Response', themes, donor };
    if (briefing) body.briefing = briefing;

    const res = await api('/api/proposals/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const newProp = await res.json();
    if (newProp.error) throw new Error(newProp.error);
    proposalState.proposals.unshift(newProp);
    proposalState.activeProposalId = newProp.id;
    proposalState.activeProposal = newProp;
    proposalState.currentStep = newProp.current_step || 'cover';

    if (referenceFiles && referenceFiles.length > 0) {
      showAdvisorMessage('System', `Uploading ${referenceFiles.length} reference file(s)...`);
      const formData = new FormData();
      for (const file of referenceFiles) {
        formData.append('file', file);
      }
      const token = localStorage.getItem('id_token') || '';
      const uploadRes = await fetch(`/api/proposals/${newProp.id}/upload-reference`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
      });
      const uploadData = await uploadRes.json();
      if (!uploadData.error) {
        const refreshed = await api(`/api/proposals/${newProp.id}`);
        const prop = await refreshed.json();
        if (!prop.error) proposalState.activeProposal = prop;
        showAdvisorMessage('System', `${uploadData.files ? uploadData.files.length : 1} file(s) uploaded (${uploadData.chars} chars total)`);
      }
    }

    if (briefing) {
      await api(`/api/proposals/${newProp.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reference_text: `--- PROJECT BRIEFING ---\n${briefing}` }),
      });
    }

    renderProposalList();
    renderProposalWorkspace();
    if (briefing || (referenceFiles && referenceFiles.length > 0)) {
      showAdvisorMessage('Sightline Advisor', `Proposal created with your briefing and reference document(s). Click "Generate with AI" on any section — the agent will use your inputs as context.`);
    } else {
      showAdvisorMessage('Sightline Advisor', 'Proposal created. Click "Generate with AI" to start. You can add instructions before generating each section.');
    }
  } catch (err) {
    alert("Could not create proposal: " + err.message);
  }
}

async function deleteProposalItem(id) {
  if (!confirm('Delete this proposal permanently? This will remove all sections, drafts, and reference data.')) return;
  try {
    const res = await api(`/api/admin/proposals/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    proposalState.proposals = proposalState.proposals.filter(p => p.id !== id);
    if (proposalState.activeProposalId === id) {
      proposalState.activeProposalId = null;
      proposalState.activeProposal = null;
      renderProposalWorkspace();
    }
    renderProposalList();
    showAdvisorMessage('System', 'Proposal deleted permanently.');
  } catch (err) {
    alert("Delete failed: " + err.message);
  }
}

async function selectProposal(id) {
  try {
    const res = await api(`/api/proposals/${id}`);
    const prop = await res.json();
    if (prop.error) throw new Error(prop.error);
    proposalState.activeProposalId = id;
    proposalState.activeProposal = prop;
    proposalState.currentStep = prop.current_step || 'cover';
    renderProposalList();
    renderProposalWorkspace();
    if (window.matchMedia('(max-width: 760px)').matches) {
      document.getElementById('proposal-sidebar')?.classList.add('collapsed');
    }
    if (window.renderPinnedSourcesList) window.renderPinnedSourcesList();
  } catch (err) { alert("Could not load proposal: " + err.message); }
}

function renderProposalList() {
  const list = document.getElementById('proposal-list');
  if (!list) return;
  if (!proposalState.proposals || proposalState.proposals.length === 0) {
    list.innerHTML = `<div class="empty-state">No proposals yet</div>`;
    return;
  }
  const isAdmin = window.__userRole === 'admin';
  list.innerHTML = proposalState.proposals.map(p => {
    const activeClass = p.id === proposalState.activeProposalId ? 'active' : '';
    const stepIdx = PROPOSAL_STEPS.findIndex(s => s.key === (p.current_step || 'cover'));
    const statusIcon = p.completed_at ? '\u2713' : `${stepIdx + 1}/12`;
    const deleteBtn = isAdmin ? `
      <button class="proposal-delete-btn" data-action="delete-proposal" data-id="${p.id}" title="Delete proposal"
        style="position:absolute; right:8px; top:50%; transform:translateY(-50%); background:none; border:none; color:var(--text-muted); cursor:pointer; padding:4px; opacity:0.5; transition:opacity 0.2s;"
        onmouseover="this.style.opacity=1;this.style.color='var(--red)';" onmouseout="this.style.opacity=0.5;this.style.color='var(--text-muted)';">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
      </button>` : '';
    return `
      <div class="report-item ${activeClass}" data-action="select-proposal" data-id="${p.id}" style="cursor:pointer; padding:10px; padding-right:36px; border-bottom:1px solid var(--border-light); position:relative;">
        <div class="report-item-title" style="font-weight:600; font-size:13px">${escHtml(p.title)}</div>
        <div class="report-item-meta" style="font-size:11px; color:var(--text-muted)">${escHtml(p.country || '')} | ${escHtml(p.donor || '')} | ${statusIcon}</div>
        ${deleteBtn}
      </div>`;
  }).join('');
}

function renderProposalWorkspace() {
  const contentEl = document.getElementById('wizard-section-content');
  const stepsEl = document.getElementById('wizard-steps-list');
  const titleEl = document.getElementById('proposal-project-title');
  const ctxEl = document.getElementById('proposal-project-context');
  const exportBtn = document.getElementById('btn-proposal-export');
  const exportPdfBtn = document.getElementById('btn-proposal-export-pdf');
  const prop = proposalState.activeProposal;
  if (!prop) {
    if (contentEl) contentEl.innerHTML = `
      <div class="proposal-welcome-placeholder">
        <div class="welcome-icon">📋</div>
        <h3>Humanitarian Proposal Design Studio</h3>
        <p>Generate a complete donor-ready proposal step by step. The AI agent researches crisis data, builds your ToC, Logframe, Budget, and full narrative.</p>
        <button class="btn btn-primary btn-with-icon" id="btn-create-first-proposal" data-action="create-new-proposal">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          <span>Create New Proposal</span>
        </button>
      </div>`;
    if (stepsEl) stepsEl.innerHTML = '';
    if (titleEl) titleEl.textContent = 'Select or Create a Proposal';
    if (ctxEl) ctxEl.textContent = 'Step-by-step AI-assisted donor proposal wizard';
    if (exportBtn) exportBtn.disabled = true;
    if (exportPdfBtn) exportPdfBtn.disabled = true;
    return;
  }
  if (titleEl) titleEl.textContent = prop.title;
  if (ctxEl) ctxEl.innerHTML = `${prop.country} | ${prop.donor} | ${prop.event || 'Emergency Response'}
    ${prop.has_reference ? `<span style="margin-left:12px; padding:2px 8px; background:var(--blue); color:#fff; border-radius:4px; font-size:10px;">REF: ${escHtml(prop.reference_filename || 'doc')}</span>` : ''}`;
  if (exportBtn) exportBtn.disabled = false;
  if (exportPdfBtn) exportPdfBtn.disabled = false;

  // Re-bind export buttons (innerHTML replacement kills listeners)
  if (exportBtn) exportBtn.onclick = exportProposalMarkdown;
  if (exportPdfBtn) exportPdfBtn.onclick = exportProposalPDF;

  const actionsEl = document.querySelector('.proposal-actions');
  if (actionsEl) {
    let refHtml = '';
    if (prop.can_edit !== false) {
      refHtml = `
        <input type="file" id="reference-file-input" accept=".pdf,.docx,.doc,.txt,.md" multiple style="display:none" onchange="uploadReference()">
        <button class="btn btn-secondary btn-sm btn-with-icon" onclick="document.getElementById('reference-file-input').click()" ${prop.has_reference ? 'disabled' : ''}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <span>${prop.has_reference ? 'Reference Attached' : 'Upload Reference'}</span>
        </button>
        ${prop.has_reference ? `<button class="btn btn-secondary btn-sm" onclick="deleteReference()" title="Remove reference">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>` : ''}
      `;
    }
    const existing = actionsEl.innerHTML;
    if (!existing.includes('reference-file-input')) {
      actionsEl.innerHTML = refHtml + existing;
      // Re-bind after innerHTML change
      const eb = document.getElementById('btn-proposal-export');
      const pb = document.getElementById('btn-proposal-export-pdf');
      if (eb) { eb.disabled = false; eb.onclick = exportProposalMarkdown; }
      if (pb) { pb.disabled = false; pb.onclick = exportProposalPDF; }
    }
  }

  renderWizardSteps();
  renderSectionContent(proposalState.currentStep);
  updateProposalBreadcrumbs();
}

function updateProposalBreadcrumbs() {
  const bcProp = document.getElementById('bc-proposal-name');
  const bcStep = document.getElementById('bc-step-name');
  if (proposalState.activeProposal) {
    if (bcProp) bcProp.textContent = proposalState.activeProposal.title || 'Untitled Proposal';
  } else {
    if (bcProp) bcProp.textContent = 'No Active Proposal';
  }
  if (proposalState.currentStep) {
    const stepInfo = PROPOSAL_STEPS.find(s => s.key === proposalState.currentStep);
    if (bcStep && stepInfo) {
      bcStep.textContent = `${stepInfo.num}. ${stepInfo.label}`;
    }
  }
}

function renderWizardSteps() {
  updateProposalBreadcrumbs();
  const stepsEl = document.getElementById('wizard-steps-list');
  if (!stepsEl || !proposalState.activeProposal) return;
  const stepStatus = proposalState.activeProposal.step_status || {};
  const currentStep = proposalState.currentStep;
  const currentIdx = PROPOSAL_STEPS.findIndex(s => s.key === currentStep);
  const completedCount = Object.values(stepStatus).filter(s => s === 'complete').length;
  const progressFill = document.getElementById('wizard-progress-fill');
  if (progressFill) progressFill.style.width = `${(completedCount / PROPOSAL_STEPS.length) * 100}%`;

  stepsEl.innerHTML = PROPOSAL_STEPS.map((step, idx) => {
    const status = stepStatus[step.key] || 'empty';
    const canClick = status === 'complete' || status === 'draft' || idx <= currentIdx;
    const isActive = step.key === currentStep;
    let icon = '○'; let cls = 'wizard-step';
    if (status === 'complete') { icon = '✓'; cls += ' complete'; }
    if (status === 'draft' || status === 'reviewing') { icon = '✎'; cls += ' draft'; }
    if (isActive) cls += ' active';
    return `
      <div class="${cls}" data-step="${step.key}" ${canClick ? 'data-action="wizard-select-step"' : ''}>
        <span class="wizard-step-num">${step.num}</span>
        <span class="wizard-step-label">${step.label}</span>
        <span class="wizard-step-icon">${icon}</span>
      </div>`;
  }).join('');
}

function renderSectionContent(step) {
  const contentEl = document.getElementById('wizard-section-content');
  if (!contentEl || !proposalState.activeProposal) return;
  const prop = proposalState.activeProposal;
  const stepStatus = prop.step_status || {};
  const status = stepStatus[step] || 'empty';
  const stepInfo = PROPOSAL_STEPS.find(s => s.key === step) || {};
  const canEdit = prop.can_edit !== false;
  const sectionContent = getSectionContent(prop, step);
  const isMarkdownSection = ['background', 'needs_assessment', 'methodology', 'sustainability', 'coordination', 'final_review'].includes(step);

  // Final Review step: show inline review panel instead of normal content
  if (step === 'final_review') {
    renderFinalReviewStep(contentEl, step, stepInfo, status, canEdit, sectionContent);
    return;
  }

  contentEl.innerHTML = `
    <div class="wizard-section-inner">
      <div class="wizard-section-header-row">
        <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
          <h3>${stepInfo.num || ''}. ${stepInfo.label || step}</h3>
          <span class="wizard-status-badge wizard-status-${status}">${status}</span>
        </div>
        ${sectionContent && isMarkdownSection ? `
          <div class="report-view-toggle proposal-view-toggle">
            <button id="btn-view-formatted-${step}" class="view-toggle-btn active" data-action="proposal-view-mode" data-step="${step}" data-mode="formatted">
              <svg class="icon-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
              <span>Document View</span>
            </button>
            <button id="btn-view-editor-${step}" class="view-toggle-btn" data-action="proposal-view-mode" data-step="${step}" data-mode="editor">
              <svg class="icon-svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
              <span>Markdown Editor</span>
            </button>
          </div>
        ` : ''}
      </div>

      ${canEdit ? `
        <div class="wizard-instructions-area">
          <label style="font-size:12px; font-weight:600; display:block; margin-bottom:6px; color:var(--text-muted)">
            Custom Instructions (optional)
          </label>
          <textarea id="wizard-instructions-${step}" class="wizard-instructions-input" rows="2"
            placeholder="e.g. Focus on women and children. Include 2024 displacement data. Use ECHO HIP template format."
            style="width:100%; font-size:13px; padding:8px 10px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg-card); color:var(--text-primary); resize:vertical;"></textarea>
        </div>
      ` : ''}

      <div class="wizard-section-body" id="wizard-section-body">
        ${sectionContent
      ? (isMarkdownSection
        ? `
          <div id="narrative-formatted-${step}" class="proposal-narrative-doc">
            <div class="proposal-narrative-card">
              ${md(sanitizeHtml((typeof sectionContent === 'string' ? sectionContent : JSON.stringify(sectionContent, null, 2)).replace(/<\/h[1-6]>/gi, '$&\n\n')))}
            </div>
          </div>
          <div id="narrative-editor-${step}" class="proposal-narrative-editor-wrap" style="display:none;">
            <textarea id="wizard-editor-${step}" class="wizard-content-editor" style="width:100%; min-height:320px; font-family:var(--font-mono, monospace); font-size:13px; padding:14px; border:1px solid var(--border); border-radius:var(--radius); background:var(--bg-card); color:var(--text-primary); resize:vertical; line-height:1.6;">${escHtml(typeof sectionContent === 'string' ? sectionContent : JSON.stringify(sectionContent, null, 2))}</textarea>
          </div>
        `
        : renderJsonSection(typeof sectionContent === 'string' ? (() => { try { return JSON.parse(sectionContent); } catch(e) { return sectionContent; } })() : sectionContent, step))
      : '<div class="empty-state" style="padding:40px; text-align:center; color:var(--text-muted)">No content yet. Write instructions above and click Generate, or just click Generate to let AI create this section.</div>'}
      </div>

      <div class="wizard-section-actions" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; padding:12px 0; border-top:1px solid var(--border-light);">
        ${canEdit ? `
          <button class="btn btn-primary btn-sm btn-with-icon" data-action="generate-section" data-step="${step}" ${proposalState.generating ? 'disabled' : ''}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
            <span>${proposalState.generating ? 'Generating...' : (step === 'final_review' ? (sectionContent ? 'Recompile' : 'Compile & Review') : (sectionContent ? 'Regenerate' : 'Generate with AI'))}</span>
          </button>
          ${sectionContent && isMarkdownSection ? `
            <button class="btn btn-secondary btn-sm btn-with-icon" data-action="save-section" data-step="${step}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              <span>Save Draft</span>
            </button>
          ` : ''}
          ${sectionContent ? `
            <button class="btn btn-green btn-sm btn-with-icon" data-action="approve-section" data-step="${step}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span>Approve &amp; Continue</span>
            </button>
          ` : ''}
          ${OPTIONAL_STEPS.includes(step) ? `
            <button class="btn btn-secondary btn-sm" data-action="skip-section" data-step="${step}">
              <span>${sectionContent ? 'Skip for now' : 'Skip (optional)'}</span>
            </button>
          ` : ''}
        ` : `<span class="text-muted" style="font-size:12px">Read-only \u2014 upgrade to premium to create proposals</span>`}
      </div>

      ${prop.has_reference ? `
        <div class="reference-attached" style="margin-top:8px; font-size:11px; color:var(--text-muted); display:flex; align-items:center; gap:6px;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          <span>Reference: ${escHtml(prop.reference_filename || 'document')} attached</span>
        </div>
      ` : ''}
    </div>`;
}

window.toggleProposalViewMode = function(step, mode) {
  const formattedEl = document.getElementById(`narrative-formatted-${step}`);
  const editorEl = document.getElementById(`narrative-editor-${step}`);
  const btnFormatted = document.getElementById(`btn-view-formatted-${step}`);
  const btnEditor = document.getElementById(`btn-view-editor-${step}`);

  if (mode === 'formatted') {
    if (formattedEl) formattedEl.style.display = 'block';
    if (editorEl) editorEl.style.display = 'none';
    if (btnFormatted) btnFormatted.classList.add('active');
    if (btnEditor) btnEditor.classList.remove('active');
  } else {
    if (formattedEl) formattedEl.style.display = 'none';
    if (editorEl) editorEl.style.display = 'block';
    if (btnFormatted) btnFormatted.classList.remove('active');
    if (btnEditor) btnEditor.classList.add('active');
  }
};

function getSectionContent(prop, step) {
  const fieldMap = { cover: 'cover_page', background: 'background', needs_assessment: 'needs_assessment', toc: 'toc', logframe: 'logframe', methodology: 'methodology', budget: 'budget', mne_framework: 'mne_framework', risk_matrix: 'risk_matrix', sustainability: 'sustainability', coordination: 'coordination', final_review: 'narrative' };
  return prop[fieldMap[step]] || '';
}

function renderFinalReviewStep(contentEl, step, stepInfo, status, canEdit, sectionContent) {
  const prop = proposalState.activeProposal;
  if (!prop) { contentEl.innerHTML = '<div class="empty-state">No proposal selected.</div>'; return; }

  // Count how many sections have content
  const fieldMap = { cover: 'cover_page', background: 'background', needs_assessment: 'needs_assessment', toc: 'toc', logframe: 'logframe', methodology: 'methodology', budget: 'budget', mne_framework: 'mne_framework', risk_matrix: 'risk_matrix', sustainability: 'sustainability', coordination: 'coordination' };
  const totalSections = Object.keys(fieldMap).length;
  let filledSections = 0;
  for (const [s, f] of Object.entries(fieldMap)) {
    const c = prop[f];
    if (c && c !== '{}' && c !== '[]' && c !== '' && c !== null && c !== undefined) filledSections++;
  }
  const progressPct = Math.round((filledSections / totalSections) * 100);

  // Get existing review data
  let review = null;
  try { review = prop.review ? (typeof prop.review === 'string' ? JSON.parse(prop.review) : prop.review) : null; } catch(e) { review = null; }

  const score = review?.overall_score || 0;
  const scoreColor = score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--warning)' : 'var(--danger)';
  const scoreLabel = score >= 80 ? 'Strong' : score >= 60 ? 'Needs Work' : score >= 40 ? 'Weak' : 'Incomplete';

  let html = `
  <div class="wizard-section-inner">
    <div class="wizard-section-header-row">
      <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
        <h3>${stepInfo.num || 12}. Final Review</h3>
        <span class="wizard-status-badge wizard-status-${status}">${status}</span>
      </div>
    </div>

    <!-- Progress Bar -->
    <div style="margin-bottom:20px; padding:16px; background:var(--bg-light); border-radius:8px; border:1px solid var(--border-color);">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
        <span style="font-size:13px; font-weight:600; color:var(--text-primary);">Section Completion</span>
        <span style="font-size:13px; font-weight:600; color:var(--primary);">${filledSections}/${totalSections} sections</span>
      </div>
      <div style="height:8px; background:var(--border-color); border-radius:4px; overflow:hidden;">
        <div style="height:100%; width:${progressPct}%; background:var(--primary); border-radius:4px; transition:width 0.3s;"></div>
      </div>
    </div>`;

  if (review) {
    // Review exists — show full review panel inline
    html += `
    <!-- Overall Score -->
    <div style="text-align:center; padding:20px 0 16px; border-bottom:1px solid var(--border-color); margin-bottom:16px;">
      <div style="font-size:56px; font-weight:800; color:${scoreColor}; line-height:1;">${score}</div>
      <div style="font-size:16px; font-weight:600; color:${scoreColor}; margin-top:4px;">${escHtml(scoreLabel)}</div>
      <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Overall Proposal Score</div>
    </div>`;

    // Overall feedback
    if (review.overall_feedback) {
      html += `<div style="padding:10px 14px; margin-bottom:16px; background:var(--bg-light); border-radius:8px; font-size:13px; color:var(--text-secondary); line-height:1.6;">${escHtml(review.overall_feedback)}</div>`;
    }

    // Section scores
    if (review.sections && review.sections.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin-bottom:8px;">Section Scores</div>`;
      html += `<div style="border:1px solid var(--border-color); border-radius:8px; overflow:hidden; margin-bottom:16px;">`;
      for (const sec of review.sections) {
        const sScore = sec.score || 0;
        const sColor = sScore >= 80 ? 'var(--success)' : sScore >= 60 ? 'var(--warning)' : 'var(--danger)';
        const statusIcon = sec.status === 'complete' ? '✅' : sec.status === 'needs_improvement' ? '⚠️' : sec.status === 'incomplete' ? '❌' : sec.status === 'skipped' ? '⏭️' : '⬜';
        html += `
        <div style="display:flex; align-items:center; padding:10px 14px; border-bottom:1px solid var(--border-color); cursor:pointer; transition:background 0.15s;" onmouseover="this.style.background='var(--bg-light)'" onmouseout="this.style.background='transparent'" onclick="wizardSelectStep('${escHtml(sec.step)}')">
          <span style="margin-right:10px; font-size:14px;">${statusIcon}</span>
          <span style="flex:1; font-size:14px; font-weight:500;">${escHtml(sec.step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()))}</span>
          <span style="font-size:16px; font-weight:700; color:${sColor};">${sScore}</span>
        </div>`;
      }
      html += `</div>`;
    }

    // High priority
    if (review.high_priority && review.high_priority.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--danger); margin-bottom:8px;">🔴 High Priority</div>`;
      for (const issue of review.high_priority) {
        html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary); margin-bottom:4px;">• ${escHtml(issue)}</div>`;
      }
      html += `<div style="margin-bottom:12px;"></div>`;
    }

    // Medium priority
    if (review.medium_priority && review.medium_priority.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--warning); margin-bottom:8px;">🟡 Medium Priority</div>`;
      for (const issue of review.medium_priority) {
        html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary); margin-bottom:4px;">• ${escHtml(issue)}</div>`;
      }
      html += `<div style="margin-bottom:12px;"></div>`;
    }

    // Strengths
    if (review.strengths && review.strengths.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--success); margin-bottom:8px;">🟢 Strengths</div>`;
      for (const s of review.strengths) {
        html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary); margin-bottom:4px;">• ${escHtml(s)}</div>`;
      }
      html += `<div style="margin-bottom:12px;"></div>`;
    }

    // Suggested actions with Revise buttons
    if (review.suggested_actions && review.suggested_actions.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--primary); margin-bottom:8px;">💡 Suggested Actions</div>`;
      for (const action of review.suggested_actions) {
        html += `
        <div style="padding:10px 12px; margin:6px 0; background:var(--bg-light); border:1px solid var(--border-color); border-radius:8px; display:flex; justify-content:space-between; align-items:center; gap:10px;">
          <div style="flex:1;">
            <strong style="color:var(--primary); font-size:13px;">${escHtml(action.step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()))}</strong>
            <p style="margin:2px 0 0 0; font-size:13px; color:var(--text-secondary);">${escHtml(action.action)}</p>
          </div>
          <button class="btn btn-xs btn-secondary" onclick="reviseFromReview('${escHtml(action.step)}', '${escHtml(action.action).replace(/'/g, "\\'")}')" style="white-space:nowrap; font-size:11px; padding:4px 10px;">✏️ Revise</button>
        </div>`;
      }
    }

    // Sources
    if (review.sources && review.sources.length > 0) {
      html += `<div style="font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin:16px 0 8px;">📎 Sources Used</div>`;
      for (const src of review.sources.slice(0, 10)) {
        const title = escHtml(src.title || src.url || 'Source');
        const url = src.url || '#';
        html += `<div style="padding:3px 8px; font-size:12px;"><a href="${url}" target="_blank" style="color:var(--primary); text-decoration:none;">${title}</a></div>`;
      }
    }

    // Review history in final review step
    if (review.history && review.history.length > 0) {
      html += `<div style="margin-top:16px; border-top:1px solid var(--border-color); padding-top:12px;">`;
      html += `<div style="font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin-bottom:8px; cursor:pointer;" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'; this.querySelector('.toggle-arrow').textContent=this.nextElementSibling.style.display==='none'?'▶':'▼';">Previous Reviews (${review.history.length}) <span class="toggle-arrow">▶</span></div>`;
      html += `<div style="display:none;">`;
      for (let i = review.history.length - 1; i >= 0; i--) {
        const h = review.history[i];
        const hScore = h.overall_score || 0;
        const hColor = hScore >= 80 ? 'var(--success)' : hScore >= 60 ? 'var(--warning)' : 'var(--danger)';
        const hDate = h.timestamp ? new Date(h.timestamp * 1000).toLocaleString() : `#${i+1}`;
        html += `<div style="padding:8px 10px; margin:4px 0; background:var(--bg-light); border:1px solid var(--border-color); border-radius:6px; font-size:12px; display:flex; justify-content:space-between; align-items:center;">`;
        html += `<span style="color:var(--text-secondary);">${escHtml(hDate)}</span>`;
        html += `<span style="font-weight:700; color:${hColor};">${hScore}/100</span>`;
        html += `</div>`;
      }
      html += `</div></div>`;
    }

    // Action buttons
    html += `
    <div style="display:flex; gap:10px; margin-top:24px; padding-top:16px; border-top:1px solid var(--border-color);">
      <button class="btn btn-primary btn-sm btn-with-icon" onclick="runProposalReview()" ${proposalState.generating ? 'disabled' : ''}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        <span>Re-analyze</span>
      </button>
      ${canEdit && sectionContent ? `
      <button class="btn btn-green btn-sm btn-with-icon" onclick="wizardSelectStep('cover')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
        <span>Approve & Export</span>
      </button>` : ''}
    </div>`;

  } else {
    // No review yet — show Analyze button
    html += `
    <div style="text-align:center; padding:50px 20px;">
      <div style="font-size:48px; margin-bottom:16px;">📋</div>
      <h3 style="font-size:18px; font-weight:700; color:var(--text-primary); margin-bottom:8px;">Ready for Review</h3>
      <p style="font-size:14px; color:var(--text-muted); margin-bottom:24px; max-width:400px; margin-left:auto; margin-right:auto;">
        ${filledSections > 0 ? `You've completed <strong>${filledSections}</strong> of <strong>${totalSections}</strong> sections. Run an AI analysis to get scores, priorities, and suggested improvements.` : 'Start by creating some sections, then run an AI analysis to get feedback.'}
      </p>
      ${canEdit ? `
      <button class="btn btn-primary btn-with-icon" onclick="runProposalReview()" ${proposalState.generating ? 'disabled' : ''} style="font-size:15px; padding:12px 28px;">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Analyze Proposal
      </button>` : '<p style="font-size:12px; color:var(--text-muted);">Upgrade to premium to analyze proposals.</p>'}
    </div>`;
  }

  html += `</div>`;
  contentEl.innerHTML = html;
}

function renderSectionMarkdown(content, step) {
  if (!content) return '';
  if (typeof content === 'object') return renderJsonSection(content, step);
  if (typeof content === 'string' && (content.startsWith('{') || content.startsWith('['))) {
    try { return renderJsonSection(JSON.parse(content), step); } catch (e) { return renderMarkdown(content); }
  }
  return renderMarkdown(content);
}

function formatLabel(key) {
  let label = key.replace(/_/g, ' ');
  label = label.replace(/([a-z])([A-Z])/g, '$1 $2');
  label = label.trim();
  return label.split(/\s+/).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
}

function renderTocSvg(nodes, canEdit) {
  const levels = ['impact', 'outcome', 'output', 'activity'];
  let html = `<div class="toc-svg-mapper" style="display:flex; justify-content:space-between; position:relative; overflow-x:auto; padding: 20px; background:var(--bg-light); border-radius:12px; gap: 24px; user-select:none;">`;

  levels.forEach((lvl, colIdx) => {
    const colNodes = nodes.map((n, i) => ({ ...n, origIdx: i })).filter(n => n.level === lvl);

    html += `<div class="toc-column" style="flex: 1; min-width: 200px; display:flex; flex-direction:column; gap:16px; position:relative;">
      <div style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted); letter-spacing:1px; margin-bottom:8px; border-bottom:1px solid var(--border-color); padding-bottom:4px;">${lvl}</div>`;

    if (colNodes.length === 0) {
      html += `<div style="opacity:0.4; font-size:12px; font-style:italic;">No nodes</div>`;
    }

    colNodes.forEach(node => {
      html += `<div class="toc-node-card" data-index="${node.origIdx}" style="background:#fff; border:1px solid #d1d5db; padding:12px; border-radius:8px; box-shadow:0 2px 6px rgba(0,0,0,0.03); position:relative; transition:all 0.2s ease;">`;
      if (canEdit) {
        html += `<textarea class="table-textarea toc-node-input" data-field="text" rows="2" style="width:100%; border:none; resize:none; font-size:13px; outline:none; font-family:var(--font-sans);" placeholder="Enter ${lvl}...">${escHtml(node.text || '')}</textarea>`;
        html += `<button type="button" class="btn-delete-row" data-action="delete-toc-node" data-index="${node.origIdx}" style="position:absolute; top:-8px; right:-8px; background:var(--danger); color:white; border-radius:50%; width:20px; height:20px; font-size:12px; display:flex; align-items:center; justify-content:center; border:none; cursor:pointer; box-shadow:0 1px 3px rgba(0,0,0,0.2);">×</button>`;
      } else {
        html += `<div style="font-size:13px; color:var(--text-main); font-weight:500;">${escHtml(node.text || '')}</div>`;
      }
      html += `</div>`;
    });

    html += `</div>`;
    if (colIdx < levels.length - 1) {
      html += `<div style="display:flex; align-items:center; color:#9ca3af;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
      </div>`;
    }
  });
  html += `</div>`;
  if (canEdit) {
    html += `<div class="table-actions-row" style="margin-top:16px;">
      <select id="toc-new-level" class="table-select" style="width:auto; display:inline-block; margin-right:8px; border-radius:6px;">
        <option value="impact">Impact</option>
        <option value="outcome" selected>Outcome</option>
        <option value="output">Output</option>
        <option value="activity">Activity</option>
      </select>
      <button type="button" class="btn btn-xs btn-secondary" data-action="add-toc-node-svg">+ Add Node</button>
    </div>`;
  }
  return html;
}

function renderRiskHeatmap(risks, canEdit) {
  const levels = ['High', 'Medium', 'Low'];
  let html = `<div class="risk-heatmap-container" style="display:flex; gap:32px; align-items:flex-start; flex-wrap:wrap;">`;

  html += `<div class="heatmap-grid" style="display:grid; grid-template-columns: 24px 1fr 1fr 1fr; grid-template-rows: 1fr 1fr 1fr 24px; gap:8px; width:400px; height:400px; flex-shrink:0;">`;
  html += `<div style="grid-row: 1 / 4; grid-column: 1; writing-mode: vertical-rl; transform: rotate(180deg); text-align:center; font-weight:700; font-size:11px; color:var(--text-muted); letter-spacing:1px;">PROBABILITY</div>`;

  levels.forEach((prob, rIdx) => {
    levels.toReversed().forEach((imp, cIdx) => {
      const cellRisks = risks.map((r, i) => ({ ...r, origIdx: i })).filter(r => r.probability === prob && r.impact === imp);
      let bg = '#f8f9fa';
      if (prob === 'High' && imp === 'High') bg = '#fee2e2'; // Light Red
      else if (prob === 'High' && imp === 'Low') bg = '#fef3c7'; // Light Yellow
      else if (prob === 'Low' && imp === 'High') bg = '#fef3c7'; // Light Yellow
      else if (prob === 'Medium' && imp === 'Medium') bg = '#fef3c7'; // Light Yellow
      else if (prob === 'Low' && imp === 'Low') bg = '#dcfce7'; // Light Green

      html += `<div class="heatmap-cell" data-prob="${prob}" data-imp="${imp}" style="background:${bg}; border:1px solid rgba(0,0,0,0.05); border-radius:8px; padding:8px; display:flex; flex-direction:column; gap:6px; overflow-y:auto;" ${canEdit ? 'ondragover="event.preventDefault()" ondrop="window.handleRiskDrop(event)"' : ''}>`;
      html += `<div style="font-size:10px; color:rgba(0,0,0,0.4); text-transform:uppercase; text-align:right; font-weight:600;">${prob} / ${imp}</div>`;

      cellRisks.forEach(r => {
        html += `<div class="risk-card-mini" draggable="${canEdit}" ondragstart="event.dataTransfer.setData('text/plain', ${r.origIdx})" data-index="${r.origIdx}" style="background:white; border:1px solid #d1d5db; border-radius:4px; padding:6px 8px; font-size:11px; cursor:${canEdit ? 'grab' : 'default'}; box-shadow:0 1px 2px rgba(0,0,0,0.05); color:var(--text-main); font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">`;
        html += `${escHtml(r.risk)}`;
        html += `</div>`;
      });

      html += `</div>`;
    });
  });
  html += `<div style="grid-row: 4; grid-column: 2 / 5; text-align:center; font-weight:700; font-size:11px; color:var(--text-muted); align-self:end; letter-spacing:1px;">IMPACT</div>`;
  html += `</div>`;

  html += `<div class="risk-details-list" style="flex:1; min-width:300px; display:flex; flex-direction:column; gap:12px;">`;
  html += `<h4 style="margin:0; font-size:13px; text-transform:uppercase; color:var(--text-muted); letter-spacing:1px; border-bottom:1px solid var(--border-color); padding-bottom:6px;">Risk Actions</h4>`;

  if (risks.length === 0) {
    html += `<div style="font-size:13px; color:var(--text-muted); font-style:italic;">No risks identified.</div>`;
  }

  risks.forEach((r, idx) => {
    html += `<div class="risk-detail-card" data-index="${idx}" style="background:white; border:1px solid var(--border-color); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:8px;">`;
    if (canEdit) {
      html += `<div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">`;
      html += `<input type="text" class="table-input risk-item-input" data-field="risk" value="${escHtml(r.risk || '')}" placeholder="Risk Event" style="flex:1; font-weight:600; font-size:14px; padding:4px 0; border:none; border-bottom:1px solid transparent; border-radius:0;">`;
      html += `<button type="button" class="btn-delete-row" data-action="delete-risk" data-index="${idx}" style="width:24px; height:24px; border-radius:4px;">×</button>`;
      html += `</div>`;
      // Probability & Impact dropdowns (works on mobile too)
      html += `<div style="display:flex; gap:8px; align-items:center;">`;
      html += `<label style="font-size:11px; color:var(--text-muted); font-weight:600;">P:</label>`;
      html += `<select class="table-input risk-item-input" data-field="probability" style="flex:1; padding:4px 6px; font-size:12px; background:var(--bg-light); border:1px solid var(--border-color); border-radius:4px;">`;
      for (const lv of levels) { html += `<option value="${lv}" ${r.probability === lv ? 'selected' : ''}>${lv}</option>`; }
      html += `</select>`;
      html += `<label style="font-size:11px; color:var(--text-muted); font-weight:600;">I:</label>`;
      html += `<select class="table-input risk-item-input" data-field="impact" style="flex:1; padding:4px 6px; font-size:12px; background:var(--bg-light); border:1px solid var(--border-color); border-radius:4px;">`;
      for (const lv of levels) { html += `<option value="${lv}" ${r.impact === lv ? 'selected' : ''}>${lv}</option>`; }
      html += `</select>`;
      html += `</div>`;
      html += `<input type="text" class="table-input risk-item-input" data-field="mitigation" value="${escHtml(r.mitigation || '')}" placeholder="Mitigation Strategy" style="padding:6px 8px; font-size:13px; background:var(--bg-light); border:1px solid var(--border-color); border-radius:6px;">`;
    } else {
      html += `<strong style="font-size:14px;">${escHtml(r.risk || '')}</strong>`;
      html += `<div style="font-size:12px; color:var(--text-muted);">P: ${escHtml(r.probability || '')} · I: ${escHtml(r.impact || '')}</div>`;
      html += `<div style="font-size:13px; color:var(--text-muted);">Mitigation: ${escHtml(r.mitigation || '')}</div>`;
    }
    html += `</div>`;
  });

  if (canEdit) {
    html += `<div style="margin-top:8px;"><button type="button" class="btn btn-xs btn-secondary" data-action="add-risk">+ Add New Risk</button></div>`;
  }

  html += `</div></div>`;
  return html;
}

window.handleRiskDrop = function (e) {
  e.preventDefault();
  const idx = parseInt(e.dataTransfer.getData('text/plain'));
  const cell = e.target.closest('.heatmap-cell');
  if (!cell || isNaN(idx)) return;

  const prob = cell.dataset.prob;
  const imp = cell.dataset.imp;

  if (proposalState.activeProposal && Array.isArray(proposalState.activeProposal.risk_matrix)) {
    proposalState.activeProposal.risk_matrix[idx].probability = prob;
    proposalState.activeProposal.risk_matrix[idx].impact = imp;
    debouncedSaveProposal();
    renderSectionContent('risk_matrix');
  }
}

function renderJsonSection(obj, step) {
  const canEdit = proposalState.activeProposal && proposalState.activeProposal.can_edit !== false;
  const disabledAttr = canEdit ? '' : 'disabled';
  if (!obj || typeof obj !== 'object') return `<pre>${escHtml(String(obj))}</pre>`;

  if (step === 'cover') {
    const title = obj.project_title || obj.title || (proposalState.activeProposal ? proposalState.activeProposal.title : '') || '';
    const country = obj.country || (proposalState.activeProposal ? proposalState.activeProposal.country : '') || '';
    const event = obj.crisis_event || obj.event || (proposalState.activeProposal ? proposalState.activeProposal.event : '') || '';
    const donor = obj.donor || (proposalState.activeProposal ? proposalState.activeProposal.donor : '') || '';
    const budget = obj.budget_summary || obj.budget || '';
    const duration = obj.duration_months || obj.duration || '';
    const partner = obj.implementing_partner || obj.partner || '';
    const beneficiaries = obj.target_beneficiaries || obj.beneficiaries || '';
    const sectors = obj.sectors || (proposalState.activeProposal && Array.isArray(proposalState.activeProposal.themes) ? proposalState.activeProposal.themes.join(', ') : '');
    const summary = obj.summary || '';

    return `
      <div class="proposal-cover-card">
        <div class="cover-card-header">
          <div class="cover-card-badges">
            ${donor ? `<span class="cover-badge donor-badge"><svg class="icon-svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px; margin-right:4px;"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>${escHtml(donor)}</span>` : ''}
            ${country ? `<span class="cover-badge country-badge"><svg class="icon-svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px; margin-right:4px;"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>${escHtml(country)}</span>` : ''}
            ${event ? `<span class="cover-badge event-badge">${escHtml(event)}</span>` : ''}
          </div>
          <div class="cover-card-title-wrap">
            <label class="field-label">Official Project Title</label>
            ${canEdit ? `
              <input type="text" class="cover-input cover-title-input" data-field="project_title" value="${escHtml(title)}" placeholder="Enter project title...">
            ` : `<h2 class="cover-title-display">${escHtml(title)}</h2>`}
          </div>
        </div>

        <div class="cover-card-stats-grid">
          <div class="cover-stat-box">
            <div class="stat-label">Estimated Budget</div>
            ${canEdit ? `<input type="text" class="cover-input stat-input" data-field="budget_summary" value="${escHtml(budget)}" placeholder="e.g. $500,000">` : `<div class="stat-val">${escHtml(budget || 'TBD')}</div>`}
          </div>
          <div class="cover-stat-box">
            <div class="stat-label">Project Duration</div>
            ${canEdit ? `<input type="text" class="cover-input stat-input" data-field="duration_months" value="${escHtml(duration)}" placeholder="e.g. 12 months">` : `<div class="stat-val">${escHtml(duration || 'TBD')}</div>`}
          </div>
          <div class="cover-stat-box">
            <div class="stat-label">Target Beneficiaries</div>
            ${canEdit ? `<input type="text" class="cover-input stat-input" data-field="target_beneficiaries" value="${escHtml(beneficiaries)}" placeholder="Targeted population">` : `<div class="stat-val">${escHtml(beneficiaries || 'TBD')}</div>`}
          </div>
          <div class="cover-stat-box">
            <div class="stat-label">Sectors / Themes</div>
            ${canEdit ? `<input type="text" class="cover-input stat-input" data-field="sectors" value="${escHtml(sectors)}" placeholder="WASH, Protection...">` : `<div class="stat-val">${escHtml(sectors || 'TBD')}</div>`}
          </div>
        </div>

        <div class="cover-card-summary-wrap">
          <label class="field-label">Executive Project Summary</label>
          ${canEdit ? `
            <textarea class="cover-input summary-textarea" data-field="summary" rows="3" placeholder="2-3 sentence executive project summary...">${escHtml(summary)}</textarea>
          ` : `<div class="summary-display">${escHtml(summary)}</div>`}
        </div>

        <div class="cover-card-footer-grid">
          <div class="footer-field">
            <label class="field-label">Implementing Partner</label>
            ${canEdit ? `<input type="text" class="cover-input footer-input" data-field="implementing_partner" value="${escHtml(partner)}" placeholder="Partner Organization Name">` : `<div class="footer-val">${escHtml(partner || 'TBD')}</div>`}
          </div>
          <div class="footer-field">
            <label class="field-label">Donor Agency</label>
            ${canEdit ? `<input type="text" class="cover-input footer-input" data-field="donor" value="${escHtml(donor)}" placeholder="Donor Agency">` : `<div class="footer-val">${escHtml(donor || 'TBD')}</div>`}
          </div>
          <div class="footer-field">
            <label class="field-label">Crisis Event</label>
            ${canEdit ? `<input type="text" class="cover-input footer-input" data-field="crisis_event" value="${escHtml(event)}" placeholder="Crisis Event Description">` : `<div class="footer-val">${escHtml(event || 'TBD')}</div>`}
          </div>
        </div>
      </div>`;
  }

  if (step === 'budget') {
    let total = '';
    let currency = 'USD';
    let duration = '';
    let lines = [];

    for (const [k, v] of Object.entries(obj)) {
      const normK = k.toLowerCase().replace(/_/g, '').replace(/\s/g, '');
      if (normK === 'total' || normK === 'estimatedbudget' || normK === 'budget') total = v;
      else if (normK === 'currency') currency = v;
      else if (normK === 'durationmonths' || normK === 'projectduration' || normK === 'duration') duration = v;
      else if (normK === 'lines' && Array.isArray(v)) lines = v;
    }

    if (canEdit) {
      let html = '<div class="budget-editor-view">';
      html += `
        <div class="budget-meta-grid">
          <div class="budget-meta-card-editor">
            <label>Total Budget</label>
            <input type="text" class="budget-meta-input" data-meta="total" value="${escHtml(total)}" placeholder="e.g. $500,000">
          </div>
          <div class="budget-meta-card-editor">
            <label>Currency</label>
            <input type="text" class="budget-meta-input" data-meta="currency" value="${escHtml(currency)}" placeholder="e.g. USD">
          </div>
          <div class="budget-meta-card-editor">
            <label>Duration</label>
            <input type="text" class="budget-meta-input" data-meta="duration_months" value="${escHtml(duration)}" placeholder="e.g. 12 months">
          </div>
        </div>`;

      html += `
        <table class="budget-table editable-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Amount</th>
              <th>Percentage</th>
              <th style="width: 50px;">Action</th>
            </tr>
          </thead>
          <tbody id="budget-lines-body">
            ${lines.map((line, idx) => `
              <tr data-index="${idx}">
                <td><input type="text" class="table-input budget-line-input" data-field="category" value="${escHtml(line.category || '')}" placeholder="Category Name"></td>
                <td><input type="text" class="table-input budget-line-input" data-field="amount" value="${escHtml(line.amount || '')}" placeholder="Amount"></td>
                <td><input type="text" class="table-input budget-line-input" data-field="percentage" value="${escHtml(line.percentage || '')}" placeholder="Percentage"></td>
                <td><button type="button" class="btn-delete-row" data-action="delete-budget-line" data-index="${idx}">×</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>`;

      html += `
        <div class="table-actions-row">
          <button type="button" class="btn btn-xs btn-secondary" data-action="add-budget-line">+ Add Line Category</button>
        </div>`;
      return html + '</div>';
    } else {
      let html = '<div class="budget-view">';
      html += '<div class="budget-meta-grid">';
      if (total) html += `<div class="budget-meta-card"><strong>Total Budget</strong><span>${escHtml(total)}</span></div>`;
      if (currency) html += `<div class="budget-meta-card"><strong>Currency</strong><span>${escHtml(currency)}</span></div>`;
      if (duration) html += `<div class="budget-meta-card"><strong>Duration</strong><span>${escHtml(duration)}</span></div>`;
      html += '</div>';

      if (lines.length > 0) {
        html += `
          <table class="budget-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Amount</th>
                <th>Percentage</th>
              </tr>
            </thead>
            <tbody>
              ${lines.map(line => `
                <tr>
                  <td><strong>${escHtml(line.category || '')}</strong></td>
                  <td>${escHtml(line.amount || '')}</td>
                  <td><span class="budget-pct-badge">${escHtml(line.percentage || '')}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>`;
      }
      return html + '</div>';
    }
  }

  if (step === 'mne_framework') {
    let approach = '';
    let indicators = [];

    for (const [k, v] of Object.entries(obj)) {
      const normK = k.toLowerCase().replace(/_/g, '').replace(/\s/g, '');
      if (normK === 'frameworkapproach' || normK === 'approach') approach = v;
      else if (normK === 'indicators' && Array.isArray(v)) indicators = v;
    }

    if (canEdit) {
      let html = '<div class="mne-editor-view">';
      html += `
        <div class="mne-approach-editor">
          <label class="field-label">Framework Approach</label>
          <input type="text" class="field-input mne-approach-input" value="${escHtml(approach)}" placeholder="e.g. Results-based, Logframe-driven">
        </div>`;

      html += `
        <table class="mne-table editable-table">
          <thead>
            <tr>
              <th>Indicator Name</th>
              <th style="width: 110px;">Type</th>
              <th>Baseline</th>
              <th>Target</th>
              <th>Source</th>
              <th style="width: 50px;">Action</th>
            </tr>
          </thead>
          <tbody id="mne-indicators-body">
            ${indicators.map((ind, idx) => `
              <tr data-index="${idx}">
                <td><textarea class="table-textarea mne-indicator-input" data-field="name" rows="2" placeholder="Indicator text...">${escHtml(ind.name || '')}</textarea></td>
                <td>
                  <select class="table-select mne-indicator-input" data-field="type">
                    <option value="output" ${String(ind.type).toLowerCase() === 'output' ? 'selected' : ''}>Output</option>
                    <option value="outcome" ${String(ind.type).toLowerCase() === 'outcome' ? 'selected' : ''}>Outcome</option>
                    <option value="impact" ${String(ind.type).toLowerCase() === 'impact' ? 'selected' : ''}>Impact</option>
                  </select>
                </td>
                <td><input type="text" class="table-input mne-indicator-input" data-field="baseline" value="${escHtml(ind.baseline || '')}" placeholder="Baseline"></td>
                <td><input type="text" class="table-input mne-indicator-input" data-field="target" value="${escHtml(ind.target || '')}" placeholder="Target"></td>
                <td><input type="text" class="table-input mne-indicator-input" data-field="source" value="${escHtml(ind.source || '')}" placeholder="Source"></td>
                <td><button type="button" class="btn-delete-row" data-action="delete-mne-indicator" data-index="${idx}">×</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>`;

      html += `
        <div class="table-actions-row">
          <button type="button" class="btn btn-xs btn-secondary" data-action="add-mne-indicator">+ Add Indicator</button>
        </div>`;
      return html + '</div>';
    } else {
      let html = '<div class="mne-view">';
      if (approach) {
        html += `<div class="mne-approach-card"><strong>Approach</strong><span>${escHtml(approach)}</span></div>`;
      }
      if (indicators.length > 0) {
        html += `
          <table class="mne-table">
            <thead>
              <tr>
                <th>Indicator Name</th>
                <th>Type</th>
                <th>Baseline</th>
                <th>Target</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              ${indicators.map(ind => `
                <tr>
                  <td><strong>${escHtml(ind.name || '')}</strong></td>
                  <td><span class="mne-type-badge type-${escHtml(ind.type || '').toLowerCase()}">${escHtml(ind.type || '')}</span></td>
                  <td>${escHtml(ind.baseline || '')}</td>
                  <td>${escHtml(ind.target || '')}</td>
                  <td><span class="mne-source-tag">${escHtml(ind.source || '')}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>`;
      }
      return html + '</div>';
    }
  }

  if (step === 'risk_matrix') {
    const risks = Array.isArray(obj) ? obj : [];
    return renderRiskHeatmap(risks, canEdit);
  }

  if (step === 'toc') {
    const nodes = Array.isArray(obj) ? obj : [];
    return renderTocSvg(nodes, canEdit);
  }

  if (step === 'logframe') {
    const rows = [
      {
        level: 'Impact / Goal',
        badge: 'impact',
        color: 'var(--primary)',
        stmtKey: 'goal',
        indKey: 'goal_indicator',
        assumpKey: 'goal_assumptions',
        assumpLabel: 'Assumptions'
      },
      {
        level: 'Outcomes',
        badge: 'outcome',
        color: 'var(--blue)',
        stmtKey: 'outcomes',
        indKey: 'outcomes_indicator',
        assumpKey: 'outcomes_assumptions',
        assumpLabel: 'Assumptions'
      },
      {
        level: 'Outputs',
        badge: 'output',
        color: 'var(--purple)',
        stmtKey: 'outputs',
        indKey: 'outputs_indicator',
        assumpKey: 'outputs_sources',
        assumpLabel: 'Sources & Means'
      },
      {
        level: 'Activities',
        badge: 'activity',
        color: 'var(--green)',
        stmtKey: 'activities',
        indKey: 'activities_inputs',
        assumpKey: 'activities_budget',
        assumpLabel: 'Inputs & Budget'
      }
    ];

    let html = `
      <div class="logframe-matrix-container">
        <table class="logframe-matrix-table">
          <thead>
            <tr>
              <th style="width: 140px;">Results Level</th>
              <th>Intervention Logic</th>
              <th>SMART Indicators</th>
              <th>Means of Verification &amp; Assumptions</th>
            </tr>
          </thead>
          <tbody>
    `;

    rows.forEach(r => {
      const stmtVal = obj[r.stmtKey] || '';
      const indVal = obj[r.indKey] || '';
      const assumpVal = obj[r.assumpKey] || '';

      html += `
        <tr class="logframe-matrix-row row-${r.badge}">
          <td class="cell-level">
            <span class="logframe-level-badge badge-${r.badge}">${escHtml(r.level)}</span>
          </td>
          <td class="cell-stmt">
            ${canEdit ? `
              <textarea class="logframe-input table-textarea" data-field="${r.stmtKey}" rows="3" placeholder="Intervention logic statement...">${escHtml(stmtVal)}</textarea>
            ` : `<div class="cell-display">${escHtml(stmtVal)}</div>`}
          </td>
          <td class="cell-ind">
            ${canEdit ? `
              <textarea class="logframe-input table-textarea" data-field="${r.indKey}" rows="3" placeholder="Indicator statement...">${escHtml(indVal)}</textarea>
            ` : `<div class="cell-display">${escHtml(indVal)}</div>`}
          </td>
          <td class="cell-assump">
            <div class="cell-label-tag">${r.assumpLabel}</div>
            ${canEdit ? `
              <textarea class="logframe-input table-textarea" data-field="${r.assumpKey}" rows="3" placeholder="${r.assumpLabel}...">${escHtml(assumpVal)}</textarea>
            ` : `<div class="cell-display">${escHtml(assumpVal)}</div>`}
          </td>
        </tr>
      `;
    });

    html += `
          </tbody>
        </table>
      </div>
    `;

    return html;
  }
  return `<pre>${escHtml(JSON.stringify(obj, null, 2))}</pre>`;
}

function renderMarkdown(text) {
  if (typeof text !== 'string') return '';
  let html = escHtml(text);
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/\n\n/g, '</p><p>');
  html = `<p>${html}</p>`;
  return html;
}

async function generateSection(step) {
  if (!proposalState.activeProposalId || proposalState.generating) return;
  proposalState.generating = true;

  const instrEl = document.getElementById(`wizard-instructions-${step}`);
  const instructions = instrEl ? instrEl.value.trim() : '';

  const editorEl = document.getElementById(`wizard-editor-${step}`);
  const manualDraft = editorEl ? editorEl.value.trim() : '';

  // Show generating state in review panel
  const reviewContent = document.getElementById('review-content');
  const statusEl = document.getElementById('advisor-status');
  if (statusEl) statusEl.textContent = 'Generating...';
  if (reviewContent) {
    const stepLabel = step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    reviewContent.innerHTML = `
      <div style="text-align:center; padding:40px 20px;">
        <div class="typing-dots" style="justify-content:center;"><span></span><span></span><span></span></div>
        <p style="font-size:14px; font-weight:600; color:var(--primary); margin-top:16px;">Generating ${escHtml(stepLabel)}...</p>
        <p style="font-size:12px; color:var(--text-muted); margin-top:8px;">The AI is researching data sources and writing your section.</p>
        <p style="font-size:11px; color:var(--text-muted); margin-top:4px;">This may take 10-30 seconds</p>
      </div>`;
  }

  renderSectionContent(step);
  try {
    const body = {};
    if (instructions) body.instructions = instructions;
    if (manualDraft) body.manual_draft = manualDraft;

    const res = await api(`/api/proposals/${proposalState.activeProposalId}/sections/${step}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    proposalState.generating = false;
    renderWizardSteps();
    renderSectionContent(step);

    // Show result in review panel
    if (statusEl) statusEl.textContent = 'Ready';
    if (reviewContent) {
      const stepLabel2 = step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
      let resultHtml = `<div style="text-align:center; padding:30px 20px;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" style="margin-bottom:8px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        <p style="font-size:14px; font-weight:600; color:var(--success);">${escHtml(stepLabel2)} Generated</p>`;

      if (data.overall_score !== undefined) {
        const scoreColor = data.overall_score >= 80 ? 'var(--success)' : data.overall_score >= 60 ? 'var(--warning)' : 'var(--danger)';
        resultHtml += `<p style="font-size:24px; font-weight:700; color:${scoreColor}; margin-top:8px;">${data.overall_score}/100</p>`;
      }

      if (data.suggestions && data.suggestions.length > 0) {
        resultHtml += `<div style="text-align:left; margin-top:16px; padding:12px; background:var(--bg-light); border-radius:6px; border:1px solid var(--border-color);">
          <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--primary); margin-bottom:8px;">💡 Suggestions</div>`;
        for (const s of data.suggestions.slice(0, 5)) {
          resultHtml += `<div style="font-size:12px; color:var(--text-secondary); padding:2px 0;">• ${escHtml(s)}</div>`;
        }
        resultHtml += `</div>`;
      }

      if (data.sources && data.sources.length > 0) {
        resultHtml += `<div style="text-align:left; margin-top:12px; padding:12px; background:var(--bg-light); border-radius:6px; border:1px solid var(--border-color);">
          <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">📎 Sources Used</div>`;
        for (const src of data.sources.slice(0, 8)) {
          const title = escHtml(src.title || src.url || 'Source');
          const url = src.url || '#';
          resultHtml += `<div style="font-size:11px; padding:2px 0;"><a href="${url}" target="_blank" style="color:var(--primary); text-decoration:none;">${title}</a></div>`;
        }
        resultHtml += `</div>`;
      }

      resultHtml += `
        <div style="margin-top:16px;">
          <button class="btn btn-sm btn-primary" onclick="runProposalReview()" style="width:100%;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:4px;"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Run Full Review
          </button>
        </div>
      </div>`;
      reviewContent.innerHTML = resultHtml;

      // Auto-run review after final_review compile
      if (step === 'final_review') {
        setTimeout(() => runProposalReview(), 500);
      }
    }
  } catch (err) {
    proposalState.generating = false;
    renderSectionContent(step);
    if (statusEl) statusEl.textContent = 'Error';
    if (reviewContent) {
      reviewContent.innerHTML = `
        <div style="text-align:center; padding:30px 20px; color:var(--danger);">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-bottom:8px"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          <p>Generation failed: ${escHtml(err.message)}</p>
          <button class="btn btn-sm btn-secondary" onclick="generateSection('${escHtml(step)}')" style="margin-top:12px;">Try Again</button>
        </div>`;
    }
  }
}

async function saveSectionManual(step) {
  if (!proposalState.activeProposalId) return;
  const editorEl = document.getElementById(`wizard-editor-${step}`);
  if (!editorEl) return;
  const content = editorEl.value.trim();
  if (!content) { alert('Nothing to save'); return; }
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/sections/${step}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    showAdvisorMessage('System', 'Draft saved.');
  } catch (err) {
    alert('Save failed: ' + err.message);
  }
}

async function uploadReference() {
  if (!proposalState.activeProposalId) return;
  const input = document.getElementById('reference-file-input');
  if (!input || !input.files.length) return;
  const formData = new FormData();
  for (const file of input.files) {
    formData.append('file', file);
  }
  input.value = '';
  try {
    const token = localStorage.getItem('id_token') || '';
    const res = await fetch(`/api/proposals/${proposalState.activeProposalId}/upload-reference`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` },
      body: formData,
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    renderProposalWorkspace();
    const fileCount = data.files ? data.files.length : 1;
    showAdvisorMessage('System', `${fileCount} file(s) uploaded: ${data.filename || ''} (${data.chars} chars total)${data.errors && data.errors.length ? ' | Errors: ' + data.errors.join('; ') : ''}`);
  } catch (err) {
    alert('Upload failed: ' + err.message);
  }
}

async function deleteReference() {
  if (!proposalState.activeProposalId) return;
  if (!confirm('Remove reference document?')) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/reference`, {
      method: 'DELETE',
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    renderProposalWorkspace();
    showAdvisorMessage('System', 'Reference document removed.');
  } catch (err) {
    alert('Remove failed: ' + err.message);
  }
}

async function skipSection(step) {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/sections/${step}/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skip: true }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    proposalState.currentStep = data.next_step || 'cover';
    renderWizardSteps();
    renderSectionContent(proposalState.currentStep);
    showAdvisorMessage('System', `${step} skipped. Next: ${data.next_step}`);
  } catch (err) { alert("Skip failed: " + err.message); }
}

async function approveSection(step) {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/sections/${step}/approve`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    proposalState.currentStep = data.next_step || 'cover';
    renderWizardSteps();
    renderSectionContent(proposalState.currentStep);
    showAdvisorMessage('Sightline Advisor', `\u2713 ${step} approved! Next: ${data.next_step}`);

    if (data.validation && data.validation.warnings && data.validation.warnings.length > 0) {
      const v = data.validation;
      let msg = `Cross-section check: ${v.summary}\n`;
      for (const w of v.warnings.slice(0, 5)) {
        const icon = w.severity === 'high' ? '\uD83D\uDD34' : w.severity === 'medium' ? '\uD83D\uDFE1' : '\u26AA';
        msg += `${icon} ${w.check}: ${w.message}\n`;
      }
      showAdvisorMessage('M&e Validator', msg);
    }
  } catch (err) { alert("Approve failed: " + err.message); }
}

function wizardSelectStep(step) {
  if (!proposalState.activeProposal) return;
  proposalState.currentStep = step;
  renderWizardSteps();
  renderSectionContent(step);
}

function showAdvisorMessage(sender, text) {
  // Show message in the review panel
  const reviewContent = document.getElementById('review-content');
  if (!reviewContent) return;

  const statusColors = {
    'System': 'var(--text-muted)',
    'Sightline Advisor': 'var(--primary)',
    'M&E Review': 'var(--primary)',
    'M&e Validator': 'var(--primary)',
    'Error': 'var(--danger)',
  };

  const msgEl = document.createElement('div');
  msgEl.style.cssText = `padding:8px 12px; margin:4px 0; border-radius:6px; background:var(--bg-light); border:1px solid var(--border-color); font-size:13px;`;
  msgEl.innerHTML = `<strong style="color:${statusColors[sender] || 'var(--primary)'}">${escHtml(sender)}</strong><p style="margin:4px 0 0 0; color:var(--text-secondary)">${escHtml(text)}</p>`;
  reviewContent.appendChild(msgEl);
  reviewContent.scrollTop = reviewContent.scrollHeight;
}

async function runProposalReview() {
  const reviewContent = document.getElementById('review-content');
  const statusEl = document.getElementById('advisor-status');
  const btnReview = document.getElementById('btn-run-review');

  if (!proposalState.activeProposalId) {
    showAdvisorMessage('System', 'Please select or create a proposal first.');
    return;
  }

  // Disable all analyze buttons and show loading in the step content too
  proposalState.generating = true;
  const analyzeBtns = document.querySelectorAll('[onclick*="runProposalReview"]');
  analyzeBtns.forEach(btn => { btn.disabled = true; btn.dataset.originalHtml = btn.innerHTML; btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:4px; animation:spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Analyzing...'; });
  if (statusEl) statusEl.textContent = 'Analyzing...';

  // Show loading state
  reviewContent.innerHTML = `
    <div style="text-align:center; padding:40px 20px;">
      <div class="typing-dots" style="justify-content:center;"><span></span><span></span><span></span></div>
      <p style="font-size:13px; color:var(--text-muted); margin-top:12px;">Analyzing your proposal...</p>
      <p style="font-size:11px; color:var(--text-muted);">This may take 10-30 seconds</p>
    </div>`;

  try {
    const resp = await api(`/api/proposals/${proposalState.activeProposalId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    const data = await resp.json();

    if (data.error) {
      reviewContent.innerHTML = `
        <div style="text-align:center; padding:40px 20px; color:var(--danger);">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-bottom:8px"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
          <p>${escHtml(data.error)}</p>
          <button class="btn btn-sm btn-secondary" onclick="runProposalReview()" style="margin-top:12px;">Try Again</button>
        </div>`;
      if (statusEl) statusEl.textContent = 'Error';
      return;
    }

    renderReviewPanel(data);

    // Also refresh proposal state and re-render final review step if active
    try {
      const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
      const prop = await refreshed.json();
      if (!prop.error) {
        proposalState.activeProposal = prop;
        // Re-render final review step if currently showing
        if (proposalState.currentStep === 'final_review') {
          renderSectionContent('final_review');
        }
      }
    } catch(e) {}

  } catch (err) {
    reviewContent.innerHTML = `
      <div style="text-align:center; padding:40px 20px; color:var(--danger);">
        <p>Review failed: ${escHtml(err.message)}</p>
        <button class="btn btn-sm btn-secondary" onclick="runProposalReview()" style="margin-top:12px;">Try Again</button>
      </div>`;
    if (statusEl) statusEl.textContent = 'Error';
  } finally {
    proposalState.generating = false;
    if (btnReview) btnReview.disabled = false;
    // Restore all analyze buttons
    const analyzeBtns = document.querySelectorAll('[onclick*="runProposalReview"]');
    analyzeBtns.forEach(btn => { btn.disabled = false; if (btn.dataset.originalHtml) { btn.innerHTML = btn.dataset.originalHtml; delete btn.dataset.originalHtml; } });
  }
}

function renderReviewPanel(review) {
  const reviewContent = document.getElementById('review-content');
  const statusEl = document.getElementById('advisor-status');
  if (!reviewContent) return;

  const score = review.overall_score || 0;
  const scoreColor = score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--warning)' : 'var(--danger)';
  const scoreLabel = score >= 80 ? 'Strong' : score >= 60 ? 'Needs Work' : score >= 40 ? 'Weak' : 'Incomplete';

  let html = '';

  // Overall score
  html += `
    <div style="text-align:center; padding:20px 0 16px; border-bottom:1px solid var(--border-color); margin-bottom:12px;">
      <div style="font-size:48px; font-weight:700; color:${scoreColor}; line-height:1;">${score}</div>
      <div style="font-size:14px; font-weight:600; color:${scoreColor}; margin-top:4px;">${escHtml(scoreLabel)}</div>
      <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">Overall Proposal Score</div>
    </div>`;

  // Overall feedback
  if (review.overall_feedback) {
    html += `<div style="padding:8px 12px; margin-bottom:12px; background:var(--bg-light); border-radius:6px; font-size:13px; color:var(--text-secondary);">${escHtml(review.overall_feedback)}</div>`;
  }

  // Section scores
  if (review.sections && review.sections.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin-bottom:8px;">Section Scores</div>`;
    for (const sec of review.sections) {
      const sScore = sec.score || 0;
      const sColor = sScore >= 80 ? 'var(--success)' : sScore >= 60 ? 'var(--warning)' : 'var(--danger)';
      const statusIcon = sec.status === 'complete' ? '✅' : sec.status === 'needs_improvement' ? '⚠️' : sec.status === 'incomplete' ? '❌' : sec.status === 'skipped' ? '⏭️' : '⬜';
      html += `
        <div style="display:flex; align-items:center; padding:6px 8px; border-bottom:1px solid var(--border-color); cursor:pointer;" onclick="wizardSelectStep('${escHtml(sec.step)}')">
          <span style="margin-right:8px;">${statusIcon}</span>
          <span style="flex:1; font-size:13px; font-weight:500;">${escHtml(sec.step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()))}</span>
          <span style="font-size:14px; font-weight:700; color:${sColor};">${sScore}</span>
        </div>`;
    }
  }

  // High priority issues
  if (review.high_priority && review.high_priority.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--danger); margin:16px 0 8px;">🔴 High Priority</div>`;
    for (const issue of review.high_priority) {
      html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary);">• ${escHtml(issue)}</div>`;
    }
  }

  // Medium priority
  if (review.medium_priority && review.medium_priority.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--warning); margin:12px 0 8px;">🟡 Medium Priority</div>`;
    for (const issue of review.medium_priority) {
      html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary);">• ${escHtml(issue)}</div>`;
    }
  }

  // Strengths
  if (review.strengths && review.strengths.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--success); margin:12px 0 8px;">🟢 Strengths</div>`;
    for (const s of review.strengths) {
      html += `<div style="padding:4px 8px 4px 20px; font-size:13px; color:var(--text-secondary);">• ${escHtml(s)}</div>`;
    }
  }

  // Suggested actions
  if (review.suggested_actions && review.suggested_actions.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--primary); margin:16px 0 8px;">💡 Suggested Actions</div>`;
    for (const action of review.suggested_actions) {
      html += `<div style="padding:6px 8px; margin:4px 0; background:var(--bg-light); border:1px solid var(--border-color); border-radius:6px; font-size:13px; display:flex; justify-content:space-between; align-items:center; gap:8px;">
        <div style="flex:1;">
          <strong style="color:var(--primary);">${escHtml(action.step.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()))}</strong>
          <p style="margin:2px 0 0 0; color:var(--text-secondary);">${escHtml(action.action)}</p>
        </div>
        <button class="btn btn-xs btn-secondary" onclick="reviseFromReview('${escHtml(action.step)}', '${escHtml(action.action).replace(/'/g, "\\'")}')" style="white-space:nowrap; font-size:11px; padding:3px 8px;">✏️ Revise</button>
      </div>`;
    }
  }

  // Sources used
  if (review.sources && review.sources.length > 0) {
    html += `<div style="font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin:16px 0 8px;">📎 Sources Used</div>`;
    for (const src of review.sources.slice(0, 10)) {
      const title = escHtml(src.title || src.url || 'Source');
      const url = src.url || '#';
      html += `<div style="padding:4px 8px; font-size:12px;">
        <a href="${url}" target="_blank" style="color:var(--primary); text-decoration:none;">${title}</a>
      </div>`;
    }
  }

  // Review history (previous reviews)
  if (review.history && review.history.length > 0) {
    html += `<div style="margin-top:16px; border-top:1px solid var(--border-color); padding-top:12px;">`;
    html += `<div style="font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted); margin-bottom:8px; cursor:pointer;" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'; this.querySelector('.toggle-arrow').textContent=this.nextElementSibling.style.display==='none'?'▶':'▼';">Previous Reviews (${review.history.length}) <span class="toggle-arrow">▶</span></div>`;
    html += `<div style="display:none;">`;
    for (let i = review.history.length - 1; i >= 0; i--) {
      const h = review.history[i];
      const hScore = h.overall_score || 0;
      const hColor = hScore >= 80 ? 'var(--success)' : hScore >= 60 ? 'var(--warning)' : 'var(--danger)';
      const hDate = h.timestamp ? new Date(h.timestamp * 1000).toLocaleString() : `#${i+1}`;
      html += `<div style="padding:8px 10px; margin:4px 0; background:var(--bg-light); border:1px solid var(--border-color); border-radius:6px; font-size:12px; display:flex; justify-content:space-between; align-items:center;">`;
      html += `<span style="color:var(--text-secondary);">${escHtml(hDate)}</span>`;
      html += `<span style="font-weight:700; color:${hColor};">${hScore}/100</span>`;
      html += `</div>`;
    }
    html += `</div></div>`;
  }

  // Re-analyze button
  html += `
    <div style="text-align:center; padding:16px 0 8px; margin-top:16px; border-top:1px solid var(--border-color);">
      <button class="btn btn-sm btn-primary" onclick="runProposalReview()" style="width:100%;">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:4px;"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Re-analyze
      </button>
    </div>`;

  reviewContent.innerHTML = html;
  reviewContent.scrollTop = 0;
  if (statusEl) statusEl.textContent = `${score}/100`;
}

// Make runProposalReview globally accessible
window.runProposalReview = runProposalReview;

// Revise a section from review feedback — navigates to section and starts revise
window.reviseFromReview = function reviseFromReview(step, feedback) {
  if (!step) return;
  // Navigate to the section
  wizardSelectStep(step);
  // Start a revision with the feedback
  reviseSectionWithFeedback(step, feedback);
};

async function reviseSectionWithFeedback(step, feedback) {
  if (!proposalState.activeProposalId || proposalState.generating) return;
  proposalState.generating = true;

  const reviewContent = document.getElementById('review-content');
  const statusEl = document.getElementById('advisor-status');
  if (statusEl) statusEl.textContent = 'Revising...';
  if (reviewContent) {
    reviewContent.innerHTML = `
      <div style="text-align:center; padding:40px 20px;">
        <div class="typing-dots" style="justify-content:center;"><span></span><span></span><span></span></div>
        <p style="font-size:14px; font-weight:600; color:var(--primary); margin-top:16px;">Revising ${escHtml(step.replace(/_/g, ' '))}...</p>
        <p style="font-size:12px; color:var(--text-muted); margin-top:8px;">Applying feedback: "${escHtml(feedback.substring(0, 80))}${feedback.length > 80 ? '...' : ''}"</p>
      </div>`;
  }

  renderSectionContent(step);

  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/sections/${step}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || 'Revision failed');
    }

    // Read the SSE stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }
        if (evt.type === 'token') {
          fullText += evt.text || '';
        } else if (evt.type === 'done') {
          // Revision complete
        }
      }
    }

    // Refresh proposal state
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) proposalState.activeProposal = prop;
    proposalState.generating = false;
    renderWizardSteps();
    renderSectionContent(step);

    if (statusEl) statusEl.textContent = 'Revised';
    if (reviewContent) {
      reviewContent.innerHTML = `
        <div style="text-align:center; padding:30px 20px;">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2" style="margin-bottom:8px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
          <p style="font-size:14px; font-weight:600; color:var(--success);">${escHtml(step.replace(/_/g, ' '))} Revised</p>
          <p style="font-size:12px; color:var(--text-muted); margin-top:4px;">Section updated with feedback.</p>
          <button class="btn btn-sm btn-primary" onclick="runProposalReview()" style="margin-top:16px; width:100%;">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:middle; margin-right:4px;"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            Re-analyze
          </button>
        </div>`;
    }
  } catch (err) {
    proposalState.generating = false;
    renderSectionContent(step);
    if (statusEl) statusEl.textContent = 'Error';
    if (reviewContent) {
      reviewContent.innerHTML = `
        <div style="text-align:center; padding:30px 20px; color:var(--danger);">
          <p>Revision failed: ${escHtml(err.message)}</p>
          <button class="btn btn-sm btn-secondary" onclick="reviseFromReview('${escHtml(step)}', '${escHtml(feedback).replace(/'/g, "\\'")}')" style="margin-top:12px;">Try Again</button>
        </div>`;
    }
  }
}

window.reviseSectionWithFeedback = reviseSectionWithFeedback;

window.pinSource = async function (url, title) {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/pin-source`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, snippet: '' })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    showAdvisorMessage('System', `✓ Pinned: ${title}`);

    // Refresh proposal to get pinned_sources
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) {
      proposalState.activeProposal = prop;
      renderPinnedSourcesList();
    }
  } catch (err) {
    showAdvisorMessage('System', `Failed to pin source: ${err.message}`);
  }
}

window.renderPinnedSourcesList = function () {
  const panel = document.getElementById('proposal-advisor-panel');
  if (!panel) return;
  let listEl = document.getElementById('pinned-sources-list');
  if (!listEl) {
    listEl = document.createElement('div');
    listEl.id = 'pinned-sources-list';
    listEl.style.cssText = 'padding: 16px; border-bottom: 1px solid var(--border-color); background: var(--bg-main); max-height: 250px; overflow-y: auto;';
    const header = panel.querySelector('.critique-header');
    if (header) header.insertAdjacentElement('afterend', listEl);
  }

  const sources = proposalState.activeProposal?.pinned_sources;
  let parsed = [];
  try {
    if (typeof sources === 'string') parsed = JSON.parse(sources);
    else if (Array.isArray(sources)) parsed = sources;
  } catch (e) { }

  if (!parsed || parsed.length === 0) {
    listEl.innerHTML = `<div style="font-size:12px; color:var(--text-muted); font-style:italic;">No pinned sources yet.</div>`;
    return;
  }

  let html = `<div style="font-weight:700; font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:12px; letter-spacing:1px;">Pinned Sources (${parsed.length})</div>`;
  html += `<div style="display:flex; flex-direction:column; gap:8px;">`;
  parsed.forEach((s, idx) => {
    html += `<div style="background:#fff; border:1px solid var(--border-color); border-radius:6px; padding:10px; font-size:12px; box-shadow:0 1px 2px rgba(0,0,0,0.02); position:relative; padding-right:32px;">
      <div style="font-weight:600; color:var(--text-main); margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escHtml(s.title)}">
        <a href="${escHtml(s.url)}" target="_blank" style="color:inherit; text-decoration:none;">${escHtml(s.title || 'Source')}</a>
      </div>
      <div style="font-size:11px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escHtml(s.url)}">${escHtml(s.url)}</div>
      <button onclick="window.unpinSource(${idx})" style="position:absolute; right:8px; top:12px; background:none; border:none; color:var(--danger); cursor:pointer; font-size:14px; padding:0; line-height:1;" title="Remove Pin">×</button>
    </div>`;
  });
  html += `</div>`;
  listEl.innerHTML = html;
}

window.unpinSource = async function (index) {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/pin-source/${index}`, { method: 'DELETE' });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    // Refresh proposal to get pinned_sources
    const refreshed = await api(`/api/proposals/${proposalState.activeProposalId}`);
    const prop = await refreshed.json();
    if (!prop.error) {
      proposalState.activeProposal = prop;
      renderPinnedSourcesList();
    }
  } catch (err) {
    showAdvisorMessage('System', `Failed to unpin source: ${err.message}`);
  }
}

async function exportProposalMarkdown() {
  if (!proposalState.activeProposalId) return;
  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const blob = new Blob([data.markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = data.filename || 'proposal.md'; a.click();
    URL.revokeObjectURL(url);
  } catch (err) { alert("Export failed: " + err.message); }
}

function renderProposalToHtml(markdown) {
  if (!markdown) return '';
  let parsed = '';
  try {
    parsed = typeof marked !== 'undefined' ? marked.parse(markdown, { breaks: true, gfm: true }) : markdown;
  } catch (e) {
    parsed = esc(markdown).replace(/\n/g, '<br>');
  }

  const container = document.createElement('div');
  container.innerHTML = parsed;

  // 1. Wrap all tables with a container and enhance structure
  // Collect tables first (static array) since DOM changes during iteration
  const tables = Array.from(container.querySelectorAll('table'));
  tables.forEach(table => {
    // Skip tables already processed
    if (table.classList.contains('pdf-table')) return;
    table.classList.add('pdf-table');

    // Ensure thead/tbody: move first row to thead if needed
    const firstRow = table.querySelector('tr');
    if (firstRow && !table.querySelector('thead')) {
      // Convert first row cells to th if they're td
      Array.from(firstRow.children).forEach(cell => {
        if (cell.tagName === 'TD') {
          const th = document.createElement('th');
          th.innerHTML = cell.innerHTML;
          if (cell.className) th.className = cell.className;
          firstRow.replaceChild(th, cell);
        }
      });
      const thead = document.createElement('thead');
      thead.appendChild(firstRow);  // removes firstRow from table body
      table.prepend(thead);  // safe: prepends to table
    }

    // Wrap remaining rows in tbody
    if (!table.querySelector('tbody')) {
      const tbody = document.createElement('tbody');
      const rows = Array.from(table.querySelectorAll('tr'));
      rows.forEach(r => tbody.appendChild(r));
      table.appendChild(tbody);
    }

    // Wrap table in div for overflow control
    const wrapper = document.createElement('div');
    wrapper.className = 'pdf-table-wrapper';
    if (table.parentNode) {
      table.parentNode.replaceChild(wrapper, table);
    }
    wrapper.appendChild(table);

    // Post-process: total rows, risk badges, numeric alignment
    const allRows = Array.from(table.querySelectorAll('tr'));
    allRows.forEach(tr => {
      const cells = Array.from(tr.children);
      cells.forEach(cell => {
        const txt = cell.textContent.trim();
        if (/total|grand total|toplam/i.test(txt)) {
          tr.classList.add('total-row');
        }
        if (/^(high|yüksek)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-high">${escHtml(txt)}</span>`;
        } else if (/^(medium|orta)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-medium">${escHtml(txt)}</span>`;
        } else if (/^(low|düşük)$/i.test(txt)) {
          cell.innerHTML = `<span class="pdf-badge pdf-badge-low">${escHtml(txt)}</span>`;
        }
        if (/^\$?\d{1,3}(,\d{3})*(\.\d{2})?%?$/.test(txt)) {
          cell.classList.add('col-num');
        }
      });
    });
  });

  // 2. Add Section Numbers to H2 elements
  let sectionIndex = 0;
  const h2s = container.querySelectorAll('h2');
  h2s.forEach(h2 => {
    const text = h2.textContent.toLowerCase();
    if (text.includes('cover page') || text.includes('overview')) return;
    sectionIndex++;
    const num = sectionIndex < 10 ? `0${sectionIndex}` : `${sectionIndex}`;
    h2.setAttribute('data-section-num', num);
  });

  // 3. Wrap narrative paragraphs in a content div for better spacing
  container.querySelectorAll('p').forEach(p => {
    if (p.parentNode === container) {
      p.classList.add('pdf-paragraph');
    }
  });

  return container.innerHTML;
}

async function exportProposalPDF() {
  if (!proposalState.activeProposalId) return;

  // Open window synchronously to bypass browser popup blockers
  const printWindow = window.open('', '_blank');
  if (printWindow) {
    printWindow.document.write(`
      <!DOCTYPE html>
      <html>
      <head><title>Generating Proposal PDF...</title></head>
      <body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; text-align:center; padding:60px; color:#334155;">
        <h2 style="font-size:20px; color:#0f172a;">Preparing Document for Print...</h2>
        <p style="font-size:14px; color:#64748b;">Compiling structured proposal sections, logframe matrix, and financial summary.</p>
      </body>
      </html>
    `);
    printWindow.document.close();
  }

  try {
    const res = await api(`/api/proposals/${proposalState.activeProposalId}/export`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    if (!printWindow) {
      alert("Please allow popups to export PDF.");
      return;
    }

    const prop = proposalState.activeProposal || {};
    const compiledHtml = renderProposalToHtml(data.markdown);

    // Extract KPI summary values if available
    let bData = {};
    try { bData = typeof prop.beneficiary_data === 'string' ? JSON.parse(prop.beneficiary_data) : (prop.beneficiary_data || {}); } catch(e){}
    let totalDirectReach = "N/A";
    if (bData.total_direct) totalDirectReach = bData.total_direct;
    else if (bData.direct && typeof bData.direct === 'object') {
      const sum = (parseInt(bData.direct.women)||0) + (parseInt(bData.direct.men)||0) + (parseInt(bData.direct.children)||0);
      if (sum > 0) totalDirectReach = sum.toLocaleString();
    }

    let budgetVal = "N/A";
    try {
      const bObj = typeof prop.budget === 'string' ? JSON.parse(prop.budget) : (prop.budget || {});
      if (bObj.total) budgetVal = bObj.total;
    } catch(e){}

    const currentDateStr = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });

    printWindow.document.open();
    printWindow.document.write(`
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <title>${escHtml(data.title || 'Proposal Document')}</title>
        <meta charset="utf-8">
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;0,800;1,600&display=swap');
          
          @page {
            size: A4 portrait;
            margin: 18mm 14mm 18mm 14mm;
            @top-right {
              content: "Sightline Project Proposal";
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              font-weight: 500;
              color: #94a3b8;
            }
            @bottom-left {
              content: "Sightline Advisor Studio • Confidential Operational Proposal";
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              color: #94a3b8;
            }
            @bottom-right {
              content: "Page " counter(page);
              font-family: 'Inter', sans-serif;
              font-size: 7pt;
              font-weight: 600;
              color: #64748b;
            }
          }
          
          *, *::before, *::after { box-sizing: border-box; }

          body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #1e293b;
            line-height: 1.6;
            font-size: 10.5pt;
            margin: 0;
            padding: 0;
            background: #fff;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
          
          /* ── Cover Page ── */
          .print-cover-page {
            min-height: 93vh;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            page-break-after: always;
            padding: 20px 5px;
            position: relative;
          }

          .cover-watermark {
            position: absolute;
            top: 45%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-35deg);
            font-size: 120px;
            color: rgba(226, 232, 240, 0.4);
            font-weight: 800;
            font-family: 'Inter', sans-serif;
            z-index: 0;
            pointer-events: none;
            letter-spacing: 16px;
          }
          
          .cover-header {
            border-top: 5px solid #e8364e;
            padding-top: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
          }
          
          .cover-logo {
            font-weight: 800;
            font-size: 24px;
            color: #e8364e;
            letter-spacing: -0.5px;
            font-family: 'Inter', sans-serif;
          }
          
          .cover-logo span {
            color: #0f172a;
          }

          .cover-badge {
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            color: #0f172a;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 9pt;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
          }
          
          .cover-body {
            margin-top: 50px;
            flex-grow: 1;
            position: relative;
            z-index: 1;
          }
          
          .cover-tagline {
            font-size: 10pt;
            text-transform: uppercase;
            letter-spacing: 3px;
            color: #e8364e;
            font-weight: 700;
            margin-bottom: 16px;
            display: block;
          }
          
          .cover-title {
            font-family: 'Playfair Display', serif;
            font-size: 34pt;
            font-weight: 800;
            line-height: 1.15;
            color: #0f172a;
            margin: 0 0 30px 0;
            max-width: 95%;
            letter-spacing: -0.5px;
          }
          
          .cover-metadata-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px 28px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-left: 4px solid #0f172a;
            border-radius: 6px;
            padding: 20px;
            margin-top: 32px;
          }
          
          .cover-meta-item {
            display: flex;
            flex-direction: column;
            gap: 3px;
          }
          
          .cover-meta-item strong {
            font-size: 8pt;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
            font-weight: 700;
          }
          
          .cover-meta-item span {
            font-size: 11pt;
            color: #0f172a;
            font-weight: 600;
          }
          
          .cover-footer {
            font-size: 9pt;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
            padding-top: 16px;
            display: flex;
            justify-content: space-between;
            font-weight: 500;
          }

          .cover-footer .confidential {
            color: #e8364e;
            font-weight: 700;
            letter-spacing: 1px;
            text-transform: uppercase;
          }
          
          /* ── Executive KPI Grid ── */
          .pdf-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 0 0 24px 0;
            page-break-inside: avoid;
            page-break-after: avoid;
          }

          .pdf-kpi-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-top: 3px solid #e8364e;
            border-radius: 5px;
            padding: 10px 10px;
            display: flex;
            flex-direction: column;
            gap: 3px;
          }

          .pdf-kpi-card .kpi-label {
            font-size: 7.5pt;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: #64748b;
            font-weight: 700;
          }

          .pdf-kpi-card .kpi-val {
            font-size: 12pt;
            font-weight: 800;
            color: #0f172a;
          }

          /* ── Document Content & Headings ── */
          .proposal-content {
            padding-top: 0;
          }

          h1 {
            font-family: 'Playfair Display', serif;
            font-size: 22pt;
            font-weight: 700;
            margin-bottom: 16px;
            color: #0f172a;
            border-bottom: 2px solid #0f172a;
            padding-bottom: 8px;
            page-break-after: avoid;
          }

          h2 {
            font-family: 'Inter', sans-serif;
            font-size: 13pt;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 1.5px solid #e2e8f0;
            padding-bottom: 5px;
            margin-top: 28px;
            margin-bottom: 12px;
            position: relative;
            padding-left: 10px;
            border-left: 4px solid #e8364e;
            page-break-after: avoid;
            page-break-inside: avoid;
          }

          h2[data-section-num]::before {
            content: attr(data-section-num) ". ";
            color: #e8364e;
            font-weight: 800;
          }
          
          /* Only force page break before major new sections, not every h2 */
          .proposal-content > h2:nth-of-type(n+3) {
            page-break-before: auto;
          }

          h3 {
            font-family: 'Inter', sans-serif;
            font-size: 11pt;
            font-weight: 700;
            margin-top: 16px;
            margin-bottom: 8px;
            color: #1e293b;
            page-break-after: avoid;
          }
          
          p, .pdf-paragraph {
            margin: 0 0 10px 0;
            text-align: justify;
            color: #334155;
            orphans: 3;
            widows: 3;
          }
          
          /* ── Table Styles ── */
          .pdf-table-wrapper {
            page-break-inside: avoid;
            margin: 14px 0 20px 0;
            overflow: hidden;
          }

          table, .pdf-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 8.5pt;
            page-break-inside: auto;
            border: 1px solid #d1d5db;
            border-radius: 0;
            box-shadow: none;
          }

          thead {
            display: table-header-group;
          }

          tbody {
            display: table-row-group;
          }

          tr {
            page-break-inside: avoid;
            page-break-after: auto;
          }

          th {
            background-color: #0f172a;
            color: #f8fafc;
            font-weight: 700;
            font-size: 7.5pt;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            text-align: left;
            padding: 7px 8px;
            border-bottom: 2px solid #e8364e;
            white-space: nowrap;
          }
          
          td {
            padding: 6px 8px;
            border-bottom: 1px solid #e5e7eb;
            color: #334155;
            vertical-align: top;
            line-height: 1.45;
            word-wrap: break-word;
            overflow-wrap: break-word;
            hyphens: auto;
          }
          
          tr:nth-child(even) td {
            background-color: #f9fafb;
          }

          tr.total-row td {
            background-color: #f1f5f9 !important;
            font-weight: 800;
            color: #0f172a;
            border-top: 2px solid #0f172a;
            border-bottom: 2px double #0f172a;
          }

          td.col-num, th.col-num {
            text-align: right;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
          }

          /* Badges */
          .pdf-badge {
            display: inline-block;
            padding: 1px 6px;
            border-radius: 10px;
            font-size: 7.5pt;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            line-height: 1.6;
          }

          .pdf-badge-high {
            background-color: #fee2e2;
            color: #991b1b;
            border: 1px solid #fca5a5;
          }

          .pdf-badge-medium {
            background-color: #fef3c7;
            color: #92400e;
            border: 1px solid #fcd34d;
          }

          .pdf-badge-low {
            background-color: #dcfce7;
            color: #166534;
            border: 1px solid #86efac;
          }

          /* Callouts & Quotes */
          blockquote {
            margin: 12px 0;
            padding: 10px 14px;
            background: #fff5f5;
            border-left: 4px solid #e8364e;
            border-radius: 0 4px 4px 0;
            color: #1e293b;
            font-style: italic;
            page-break-inside: avoid;
          }
          
          ul, ol {
            margin: 8px 0;
            padding-left: 18px;
            color: #334155;
          }
          
          li {
            margin-bottom: 4px;
          }
          
          li::marker {
            color: #e8364e;
            font-weight: bold;
          }

          strong {
            color: #0f172a;
            font-weight: 600;
          }

          /* Ensure content blocks stay together */
          .proposal-content > *:first-child {
            margin-top: 0;
          }

          /* Metadata items at top (country, donor, etc.) */
          .proposal-content > p:first-of-type {
            margin-bottom: 8px;
            line-height: 1.8;
          }

          @media print {
            .no-print { display: none; }
            body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
          }
        </style>
      </head>
      <body>
        <div class="print-cover-page">
          <div class="cover-watermark">DRAFT</div>
          <div class="cover-header">
            <div class="cover-logo">Sight<span>line</span></div>
            <div class="cover-badge">Project Design Document</div>
          </div>
          <div class="cover-body">
            <span class="cover-tagline">Humanitarian Action Proposal</span>
            <h1 class="cover-title">${escHtml(prop.title || 'Untitled Proposal')}</h1>
            
            <div class="cover-metadata-grid">
              <div class="cover-meta-item">
                <strong>Country of Operation</strong>
                <span>${escHtml(prop.country || 'N/A')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Target Donor</strong>
                <span>${escHtml(prop.donor || 'N/A')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Sector & Focus</strong>
                <span>${escHtml(prop.event || 'Emergency Response')}</span>
              </div>
              <div class="cover-meta-item">
                <strong>Date Generated</strong>
                <span>${currentDateStr}</span>
              </div>
            </div>
          </div>
          <div class="cover-footer">
            <span>Prepared by Sightline Advisor Studio</span>
            <span class="confidential">Confidential Draft</span>
          </div>
        </div>

        <!-- Executive Dashboard Banner -->
        <div class="pdf-kpi-grid">
          <div class="pdf-kpi-card">
            <span class="kpi-label">Target Country</span>
            <span class="kpi-val">${escHtml(prop.country || 'N/A')}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Target Donor</span>
            <span class="kpi-val">${escHtml(prop.donor || 'N/A')}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Direct Reach</span>
            <span class="kpi-val">${escHtml(totalDirectReach)}</span>
          </div>
          <div class="pdf-kpi-card">
            <span class="kpi-label">Proposed Budget</span>
            <span class="kpi-val">${escHtml(budgetVal)}</span>
          </div>
        </div>
        
        <div class="proposal-content">
          ${compiledHtml}
        </div>
        
        <script>
          window.onload = function() {
            setTimeout(function() {
              window.print();
            }, 600);
          };
        </script>
      </body>
      </html>
    `);
    printWindow.document.close();
  } catch (err) {
    if (printWindow) printWindow.close();
    alert("PDF Export failed: " + err.message);
  }
}

function addAdvisorMessage(sender, text) { showAdvisorMessage(sender, text); }

async function loadAndRenderAdvisorHistory(propId, propTitle) {
  const msgs = document.getElementById('critique-messages');
  if (!msgs) return;
  msgs.innerHTML = `<div class="critique-msg system"><strong>Sightline Advisor</strong><p>Select a section and click "Generate" to start. Ask me for revisions anytime.</p></div>`;
}

async function saveActiveProposal() {
  if (!proposalState.activeProposalId || !proposalState.activeProposal) return;
  try {
    await api(`/api/proposals/${proposalState.activeProposalId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(proposalState.activeProposal) });
    // Show subtle notification in review panel after manual edits
    const statusEl = document.getElementById('advisor-status');
    if (statusEl && statusEl.textContent !== 'Analyzing...' && statusEl.textContent !== 'Generating...') {
      statusEl.textContent = 'Edited · Analyze for feedback';
    }
  }
  catch (err) { console.warn("Save proposal failed:", err); }
}


/* ── Guided Proposal workspace ────────────────────────────────────────────
 * The legacy proposal editor is no longer mounted. Guided Proposal is the
 * single user-facing proposal workspace and talks to /api/proposals/setups.
 */
let guidedProposalState = { setups: [], active: null, step: 1, busy: false, countries: [], viewMode: 'edit' };
function guidedJson(value, fallback) { try { return JSON.parse(value); } catch (_) { return fallback; } }
async function guidedRequest(path, options = {}) { const response = await api(path, options); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`); return data; }
function guidedEsc(value) { return escHtml(value == null ? '' : String(value)); }
function guidedSetAlert(message, kind = '') { const el = document.getElementById('guided-alert'); if (el) { el.textContent = message || ''; el.className = `guided-alert ${kind}`; } }
function guidedShell() {
  const panel = document.getElementById('panel-proposal'); if (!panel) return null;
  panel.innerHTML = `<div class="guided-proposal-shell" id="guided-proposal-shell"><aside class="guided-proposal-list"><div class="guided-list-head"><div><span class="eyebrow">Proposal studio</span><h2>Guided proposals</h2></div><button class="guided-icon-btn" data-guided-action="new" title="New proposal">+</button></div><div class="guided-list-items" id="guided-list-items"><div class="guided-empty">Loading proposals…</div></div></aside><main class="guided-proposal-main"><header class="guided-main-head"><div><span class="eyebrow">Forward-only workflow</span><h1 id="guided-title">Start a donor-ready proposal</h1><p id="guided-subtitle">Draft with the agent, review the evidence, then lock each stage.</p></div><div class="guided-head-actions"><button class="guided-btn secondary" data-guided-action="call-brief" id="guided-call-brief" hidden>Call brief</button><button class="guided-btn secondary" data-guided-action="delete" id="guided-delete" hidden>Delete</button></div></header><nav class="guided-stepper" id="guided-stepper"></nav><div class="guided-alert" id="guided-alert" aria-live="polite"></div><section class="guided-content" id="guided-content"><div class="guided-empty">Create a proposal to begin.</div></section></main><aside class="guided-review" id="guided-review"><div class="guided-review-head"><span class="eyebrow">Live review</span><h3>Agent feedback</h3></div><div id="guided-review-body"><p class="guided-muted">Analysis and donor rule feedback will appear here.</p></div></aside></div>`;
  return panel;
}
function guidedRenderList() { const el = document.getElementById('guided-list-items'); if (!el) return; if (!guidedProposalState.setups.length) { el.innerHTML = '<div class="guided-empty">No proposals yet.</div>'; return; } el.innerHTML = guidedProposalState.setups.map(item => { const active = item.id === guidedProposalState.active?.id ? ' active' : ''; const states = [item.state, item.step2_state, item.step3_state, item.step4_state].map(x => x === 'locked' ? '✓' : '○').join(' '); return `<button class="guided-list-item${active}" data-guided-action="select" data-id="${guidedEsc(item.id)}"><strong>${guidedEsc(item.project_title || 'Untitled proposal')}</strong><span>${guidedEsc(item.country || 'Country pending')} · ${states}</span></button>`; }).join(''); }
function guidedRenderStepper() { const el = document.getElementById('guided-stepper'); if (!el) return; const labels = ['Project setup','Context & needs','Technical matrix','Budget & risks','Final review']; el.innerHTML = labels.map((label, i) => { const num = i + 1; const locked = guidedProposalState.active && (num === 1 ? guidedProposalState.active.state : guidedProposalState.active[`step${num}_state`]) === 'locked'; const current = num === guidedProposalState.step ? ' current' : ''; return `<button class="guided-step${current}${locked ? ' locked' : ''}" data-guided-action="step" data-step="${num}" ${num > guidedProposalState.step ? 'disabled' : ''}><span>${locked ? '✓' : num}</span>${label}</button>`; }).join(''); }
function guidedField(label, field, value, type = 'text', extra = '') { if (type === 'select') { const options = field === 'donor' ? '<option value="">Choose donor</option><option value="ocha_cbpf">OCHA CBPF</option><option value="usaid_bha">USAID / BHA</option><option value="europeaid_prag">EuropeAid (PRAG)</option><option value="generic">Generic donor</option>' : field === 'budget_currency' ? '<option value="USD">USD</option><option value="EUR">EUR</option><option value="TRY">TRY</option>' : '<option value="">Choose country</option>' + guidedProposalState.countries.map(c => `<option value="${guidedEsc(c)}">${guidedEsc(c)}</option>`).join(''); return `<label class="guided-field"><span>${label}</span><select class="guided-input" data-guided-field="${field}" ${extra}>${options}</select></label>`; } return `<label class="guided-field ${type === 'textarea' ? 'full' : ''}"><span>${label}</span><${type === 'textarea' ? 'textarea' : 'input'} class="guided-input" data-guided-field="${field}" ${type !== 'textarea' ? `type="${type}"` : ''} ${extra}>${type === 'textarea' ? guidedEsc(value) : ''}</${type === 'textarea' ? 'textarea' : 'input'}>`; }
function guidedAnalysisCard(analysis) { if (!analysis) return '<p class="guided-muted">Run analysis to receive donor-specific feedback.</p>'; const score = Number(analysis.donor_compliance_score || 0); const notes = [...(analysis.critique_notes || []), ...(analysis.suggested_improvements || [])]; const violations = (analysis.violations || []).map(v => typeof v === 'string' ? v : v.message).filter(Boolean); const warnings = (analysis.warnings || []).map(v => typeof v === 'string' ? v : v.message).filter(Boolean); return `<div class="guided-score"><strong>${score}</strong><span>/ 100 compliance</span></div><div class="guided-analysis-status ${analysis.is_valid ? 'ok' : 'bad'}">${analysis.is_valid ? 'Ready to lock' : 'Needs attention'}</div>${violations.length ? `<ul class="guided-violations">${violations.map(v => `<li>${guidedEsc(v)}</li>`).join('')}</ul>` : ''}${notes.length ? `<ul class="guided-notes">${notes.map(v => `<li>${guidedEsc(v)}</li>`).join('')}</ul>` : ''}${warnings.length ? `<ul class="guided-warnings">${warnings.map(v => `<li>${guidedEsc(v)}</li>`).join('')}</ul>` : ''}`; }
function guidedActionBar(step, locked = false) { if (locked) return `<div class="guided-locked-banner">Step ${step} is locked and immutable.</div>`; return `<div class="guided-action-bar"><button class="guided-btn secondary" data-guided-action="generate" data-step="${step}">Generate draft</button><button class="guided-btn secondary" data-guided-action="analyze" data-step="${step}">Analyze with AI</button><button class="guided-btn primary" data-guided-action="lock" data-step="${step}">Confirm & lock Step ${step}</button></div>`; }
function guidedTechnicalMatrixHtml(active, locked) {
  const data = active?.technical_data || {};
  const rows = Array.isArray(data.logframe) ? data.logframe : [];
  const levels = [['impact','Impact',''],['outcome','Outcome','impact'],['output','Output','outcome'],['activity','Activity','output']];
  return `<div class="guided-logframe-builder"><div class="guided-logframe-builder-head"><strong>Impact → Outcome → Output → Activity</strong><span>${rows.length} rows</span></div>${levels.map(([level,label,parentLevel]) => { const items = rows.filter(row => row.level === level); const add = locked ? '' : `<button class="btn btn-secondary btn-sm" data-guided-logframe-action="add" data-level="${level}">+ Add ${label}</button>`; const cards = items.map(row => { const parents = rows.filter(parent => parent.level === parentLevel); const parent = level === 'impact' ? '<span class="guided-logframe-root">Top level</span>' : `<select class="guided-input guided-logframe-parent" data-guided-logframe-action="parent" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}><option value="">Select parent</option>${parents.map(p => `<option value="${guidedEsc(p.id)}" ${p.id === row.parent_id ? 'selected' : ''}>${guidedEsc(p.id)}</option>`).join('')}</select>`; return `<article class="guided-logframe-card guided-logframe-${level}"><div class="guided-logframe-card-head"><strong>${guidedEsc(row.id || level)}</strong>${parent}${locked ? '' : `<button class="guided-icon-btn danger" data-guided-logframe-action="remove" data-id="${guidedEsc(row.id)}">×</button>`}</div><div class="guided-logframe-fields"><label>Intervention logic<textarea class="guided-input" data-guided-logframe-action="text" data-field="intervention_logic" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.intervention_logic || '')}</textarea></label><label>Means of verification<textarea class="guided-input" data-guided-logframe-action="text" data-field="means_of_verification" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.means_of_verification || '')}</textarea></label><label>Assumptions<textarea class="guided-input" data-guided-logframe-action="text" data-field="assumptions" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.assumptions || '')}</textarea></label><label>SMART indicator<input class="guided-input" data-guided-logframe-action="indicator" data-id="${guidedEsc(row.id)}" value="${guidedEsc(row.indicators?.[0]?.indicator_title || row.indicators?.[0] || '')}" ${locked ? 'disabled' : ''}></label></div></article>`; }).join(''); return `<section class="guided-logframe-tier"><header><div><strong>${label}s</strong><small>${items.length} row${items.length === 1 ? '' : 's'}</small></div>${add}</header>${cards || `<div class="guided-logframe-empty">No ${label.toLowerCase()} added yet.</div>`}</section>`; }).join('')}</div>`;
}
function guidedScheduleHtml(active, locked) {
  const data = active?.technical_data || {};
  const activities = (Array.isArray(data.logframe) ? data.logframe : []).filter(row => row.level === 'activity');
  const schedule = Array.isArray(data.gantt) ? data.gantt : [];
  const months = Array.from({length: 12}, (_, i) => i + 1);
  return `<div class="guided-schedule-builder"><div class="guided-schedule-head"><div><span class="proposal-v2-kicker">Activity schedule</span><strong>Project timeline · 12 months</strong></div><span>${activities.length} activities</span></div>${activities.length ? `<div class="guided-schedule-table-wrap"><table class="guided-schedule-table"><thead><tr><th>Activity</th>${months.map(m => `<th>M${m}</th>`).join('')}</tr></thead><tbody>${activities.map(activity => { const item = schedule.find(entry => entry.activity_id === activity.id) || {}; const activeMonths = new Set(item.months || []); return `<tr><th>${guidedEsc(activity.id)}</th>${months.map(m => `<td><input type="checkbox" data-guided-schedule-month="${m}" data-activity-id="${guidedEsc(activity.id)}" ${activeMonths.has(m) ? 'checked' : ''} ${locked ? 'disabled' : ''} aria-label="${guidedEsc(activity.id)} month ${m}"></td>`).join('')}</tr>`; }).join('')}</tbody></table></div>` : '<div class="guided-schedule-empty">Add an Activity above to place it on the schedule.</div>'}</div>`;
}
function guidedRender() {
  const active = guidedProposalState.active; const content = document.getElementById('guided-content'); if (!content) return; guidedRenderList(); guidedRenderStepper(); if (!active) { content.innerHTML = '<div class="guided-empty large">Select a proposal or create a new one.</div>'; return; }
  document.getElementById('guided-title').textContent = active.project_title || 'Untitled proposal'; document.getElementById('guided-subtitle').textContent = `${active.country || 'Country pending'} · ${active.donor || 'Donor pending'} · ${active.reference_filename || 'No call document attached'}`; document.getElementById('guided-delete').hidden = !active.can_delete; document.getElementById('guided-call-brief').hidden = !active.reference_text;
  const step = guidedProposalState.step; const locked = step === 1 ? active.state === 'locked' : active[`step${step}_state`] === 'locked'; const analysis = step === 1 ? active.analysis : active[`step${step}_analysis`]; let html = `<div class="guided-step-heading"><div><span class="eyebrow">Step ${step} of 5</span><h2>${['Project setup','Context & needs','Technical matrix','Budget & risks','Final review'][step - 1]}</h2></div>${locked ? '<span class="guided-lock-pill">Locked</span>' : ''}</div>`;
  if (step === 1) { html += `<div class="guided-form-grid">${guidedField('Project title','project_title',active.project_title,'text','required minlength="10" maxlength="150" placeholder="A clear, geographically specific title"')}${guidedField('Target country','country',active.country,'select','required')}${guidedField('Region / location','region',active.region)}${guidedField('Primary donor','donor',active.donor,'select','required')}${guidedField('Estimated budget','budget_amount',active.budget_amount,'number','min="0.01" step="0.01" required')}${guidedField('Currency','budget_currency',active.budget_currency,'select')}</div>${guidedField('Executive intent (100–500 characters)','executive_intent',active.executive_intent,'textarea','minlength="100" maxlength="500" rows="6" placeholder="Describe the humanitarian problem, target group and intended change."')}<label class="guided-field full"><span>Sectors</span><input class="guided-input" data-guided-field="sectors" value="${guidedEsc((active.sectors || []).join(', '))}" placeholder="Protection, Health, WASH"></label><div class="guided-upload"><span>Grant call</span><input id="guided-reference" type="file" accept=".docx,.txt,.md"><small>${guidedEsc(active.reference_filename || 'Attach a call document to ground the agent in the actual requirements.')}</small></div>${guidedActionBar(1, locked)}`; }
  else if (step === 2) { const d = active.context_data || {}; html += `<p class="guided-help">The agent can draft this stage from your locked setup and attached call. Edit the text, then analyze and lock it.</p>${guidedField('Humanitarian context','humanitarian_context',d.humanitarian_context || '','textarea','rows="8"')}${guidedField('Needs assessment','needs_assessment',d.needs_assessment || '','textarea','rows="8"')}${guidedField('Strategic justification','strategic_justification',d.strategic_justification || '','textarea','rows="8"')}<label class="guided-field full"><span>Beneficiary matrix (JSON)</span><textarea class="guided-input" data-guided-field="beneficiaries" rows="7">${guidedEsc(JSON.stringify(d.beneficiaries || {host_communities:{},idps:{},refugees_returnees:{}}, null, 2))}</textarea></label>${guidedActionBar(2, locked)}`; }
  else if (step === 3) { const d = active.technical_data || {}; html += `<p class="guided-help">Build the result chain visually and link each level to its parent.</p>${guidedField('Theory of change narrative','toc_narrative',d.toc_narrative || '','textarea','rows="5"')}${guidedTechnicalMatrixHtml(active, locked)}<label class="guided-field full"><span>Activity schedule (JSON)</span><textarea class="guided-input" data-guided-field="gantt" rows="5">${guidedEsc(JSON.stringify(d.gantt || [], null, 2))}</textarea></label>${guidedActionBar(3, locked)}`; }
  else if (step === 4) { const d = active.financial_data || {}; html += `<p class="guided-help">Every budget line is calculated and checked against the donor overhead ceiling.</p><label class="guided-field full"><span>Budget items (JSON)</span><textarea class="guided-input" data-guided-field="budget_items" rows="12">${guidedEsc(JSON.stringify(d.budget_items || [], null, 2))}</textarea></label><label class="guided-field full"><span>Risk matrix (JSON)</span><textarea class="guided-input" data-guided-field="risks" rows="9">${guidedEsc(JSON.stringify(d.risks || [], null, 2))}</textarea></label><label class="guided-check"><input type="checkbox" data-guided-field="psea_signoff" ${d.psea_signoff ? 'checked' : ''}> I confirm the PSEA / six IASC core principles commitment.</label>${guidedField('Sphere standards narrative','sphere_standards_narrative',d.sphere_standards_narrative || '','textarea','rows="4"')}${guidedActionBar(4, locked)}`; }
  else { html += `<p class="guided-help">All four stages must be locked before the final review can be generated.</p><div class="guided-final-actions"><button class="guided-btn secondary" data-guided-action="summary">Refresh locked summary</button><button class="guided-btn secondary" data-guided-action="evaluate">Run PRAG evaluation</button><button class="guided-btn primary" data-guided-action="pdf">Compile donor-ready PDF</button></div><pre id="guided-final-output" class="guided-final-output"></pre>`; }
  content.innerHTML = html;
  if (step === 1) { ['project_title','country','region','donor','budget_amount','budget_currency','executive_intent','sectors'].forEach(field => { const el = content.querySelector(`[data-guided-field="${field}"]`); if (el && active[field] != null) el.value = field === 'sectors' ? (active.sectors || []).join(', ') : active[field]; }); }
  document.getElementById('guided-review-body').innerHTML = guidedAnalysisCard(analysis);
}
function guidedPayload(step) { const fields = {}; document.querySelectorAll('#guided-content [data-guided-field]').forEach(el => { const key = el.dataset.guidedField; if (el.type === 'checkbox') fields[key] = el.checked; else fields[key] = el.value; }); if (step === 1) { fields.sectors = fields.sectors.split(',').map(x => x.trim()).filter(Boolean); } if (step === 2) fields.beneficiaries = guidedJson(fields.beneficiaries, {}); for (const key of ['logframe','gantt','budget_items','risks']) if (key in fields) fields[key] = guidedJson(fields[key], []); return fields; }
async function guidedRefresh() { guidedProposalState.setups = await guidedRequest('/api/proposals/setups'); guidedRenderList(); if (!guidedProposalState.active && guidedProposalState.setups[0]) { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.setups[0].id}`); guidedRender(); } }
async function guidedCreate() { const data = await guidedRequest('/api/proposals/setups', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ project_title:'New guided proposal', donor:'generic', budget_currency:'USD', sectors:[] }) }); guidedProposalState.active = data; guidedProposalState.step = 1; await guidedRefresh(); guidedRender(); }
async function guidedSaveStep1() { const data = guidedPayload(1); const updated = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); guidedProposalState.active = updated; }
async function guidedHandle(action, target) {
  const active = guidedProposalState.active; if (action === 'new') return guidedCreate(); if (action === 'select') { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${target.dataset.id}`); guidedProposalState.step = guidedProposalState.active.state === 'locked' ? 2 : 1; return guidedRender(); } if (!active) return;
  if (action === 'delete') { if (!confirm('Delete this guided proposal permanently?')) return; await guidedRequest(`/api/proposals/setups/${active.id}`, {method:'DELETE'}); guidedProposalState.active = null; guidedProposalState.step = 1; return guidedRefresh(); }
  if (action === 'step') { const n = Number(target.dataset.step); if (n <= guidedProposalState.step) { guidedProposalState.step = n; guidedRender(); } return; }
  if (action === 'call-brief') { const result = await guidedRequest(`/api/proposals/setups/${active.id}/call-brief`, {method:'POST'}); document.getElementById('guided-review-body').innerHTML = `<h4>Call brief</h4><p>${guidedEsc(result.brief?.overview || '')}</p><pre class="guided-final-output">${guidedEsc(JSON.stringify(result.brief, null, 2))}</pre>`; return; }
  const step = Number(target.dataset.step || guidedProposalState.step); const base = step === 1 ? `/api/proposals/setups/${active.id}` : `/api/proposals/steps/${step}`; let payload = step === 1 ? guidedPayload(1) : guidedPayload(step); if (step > 1) payload.setup_id = active.id;
  if (action === 'generate') { const path = step === 1 ? `/api/proposals/setups/${active.id}/generate-draft` : `/api/proposals/setups/${active.id}/generate-step2-draft`; const result = await guidedRequest(path,{method:'POST'}); if (step === 1 && result.draft) Object.assign(active, result.draft); if (step === 2 && result.draft) active.context_data = result.draft; guidedRender(); return; }
  if (action === 'analyze') { if (step === 1) await guidedSaveStep1(); const result = await guidedRequest(`${base}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); if (step === 1) active.analysis = result; else active[`step${step}_analysis`] = result; guidedSetAlert(result.is_valid ? 'Analysis complete. Review the feedback before locking.' : 'Analysis found issues to address.', result.is_valid ? 'success' : 'error'); guidedRender(); return; }
  if (action === 'lock') { const result = await guidedRequest(`${base}/lock`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); guidedProposalState.active = result; guidedProposalState.step = Math.min(5, step + 1); guidedSetAlert(`Step ${step} locked.`, 'success'); await guidedRefresh(); guidedRender(); return; }
  if (action === 'summary' || action === 'evaluate' || action === 'pdf') { const path = action === 'summary' ? `/api/proposals/setups/${active.id}/summary` : action === 'evaluate' ? `/api/proposals/setups/${active.id}/evaluate` : `/api/proposals/setups/${active.id}/compile-pdf`; if (action === 'pdf') { const response = await api(path, {method:'POST'}); if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || `PDF compilation failed (${response.status})`); } const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${active.project_title || 'proposal'}.pdf`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); guidedSetAlert('PDF compiled and downloaded.', 'success'); return; } const result = await guidedRequest(path,{method:'POST'}); const out = document.getElementById('guided-final-output'); if (out) out.textContent = JSON.stringify(result, null, 2); }
}
function initGuidedProposalPipelineReference() { const panel = guidedShell(); if (!panel) return; panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action]'); if (!target || guidedProposalState.busy) return; guidedProposalState.busy = true; guidedSetAlert('Working…'); try { await guidedHandle(target.dataset.guidedAction, target); } catch (err) { guidedSetAlert(err.message, 'error'); } finally { guidedProposalState.busy = false; } }); panel.addEventListener('change', async e => { if (e.target.id !== 'guided-reference' || !guidedProposalState.active) return; const fd = new FormData(); fd.append('file', e.target.files[0]); try { await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`, {method:'POST', body:fd}); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); guidedRender(); guidedSetAlert('Call document attached.', 'success'); } catch (err) { guidedSetAlert(err.message, 'error'); } }); (async () => { try { const countries = await guidedRequest('/api/db/countries'); guidedProposalState.countries = Array.isArray(countries) ? countries : []; await guidedRefresh(); guidedRender(); } catch (err) { guidedSetAlert(err.message, 'error'); } })(); }

// V2 adapter: keep the established Proposal page layout and replace only its
// data/step behaviour with the five-stage Guided Proposal contract.
function initGuidedProposalPipelineActive() {
  const panel = document.getElementById('panel-proposal');
  if (!panel) return;
  if (panel.dataset.guidedMounted === 'true') return;
  panel.dataset.guidedMounted = 'true';
  // The earlier experimental renderer is retained only as source reference;
  // prevent any late async callback from repainting the V2 workspace.
  window.guidedRender = () => {};
  const reviewPanel = document.getElementById('proposal-advisor-panel');
  const reviewToggle = document.getElementById('btn-toggle-proposal-chat');
  const reviewCollapsedBar = document.getElementById('proposal-chat-collapsed-bar');
  const toggleReviewPanel = event => { event?.preventDefault(); event?.stopImmediatePropagation(); if (!reviewPanel) return; const collapsed = reviewPanel.classList.toggle('collapsed'); document.getElementById('proposal-workspace')?.classList.toggle('chat-open', !collapsed); reviewToggle?.setAttribute('aria-expanded', String(!collapsed)); if (reviewToggle) reviewToggle.title = collapsed ? 'Expand Review Panel' : 'Collapse Review Panel'; };
  if (reviewToggle && reviewToggle.dataset.guidedToggleBound !== 'true') { reviewToggle.dataset.guidedToggleBound = 'true'; reviewToggle.addEventListener('click', toggleReviewPanel, true); }
  if (reviewCollapsedBar && reviewCollapsedBar.dataset.guidedToggleBound !== 'true') { reviewCollapsedBar.dataset.guidedToggleBound = 'true'; reviewCollapsedBar.addEventListener('click', toggleReviewPanel, true); }
  const list = document.getElementById('proposal-list');
  const steps = document.getElementById('wizard-steps-list');
  const content = document.getElementById('wizard-section-content');
  const title = document.getElementById('proposal-project-title');
  const context = document.getElementById('proposal-project-context');
  if (!list || !steps || !content) return;
  let donors = [];
  let callBriefBusy = false;
  const donorFor = id => donors.find(d => d.id === id) || donors.find(d => d.id === 'generic') || {};
  const setNotice = (message, error = false) => { const review = document.getElementById('review-content'); if (review) review.innerHTML = `<div class="proposal-review-message ${error ? 'error' : ''}">${guidedEsc(message)}</div>`; };
  const statusFor = (n) => { const p = guidedProposalState.active; if (!p) return 'empty'; return (n === 1 ? p.state : n === 2 ? p.step2_state : n === 3 ? p.step3_state : n === 4 ? p.step4_state : 'draft') || 'draft'; };
  const maxReachableStep = () => { for (let n = 1; n <= 4; n += 1) if (statusFor(n) !== 'locked') return n; return 5; };
  const syncStepNavigation = () => { const max = maxReachableStep(); steps.querySelectorAll('[data-guided-action="step"]').forEach(el => { const n = Number(el.dataset.step); if (n <= max) el.removeAttribute('aria-disabled'); else el.setAttribute('aria-disabled','true'); }); };
  const renderList = () => { list.innerHTML = guidedProposalState.setups.length ? guidedProposalState.setups.map(p => `<div class="report-item ${p.id === guidedProposalState.active?.id ? 'active' : ''}" data-guided-action="select" data-id="${guidedEsc(p.id)}" style="cursor:pointer;padding:10px;border-bottom:1px solid var(--border-light);"><div class="report-item-title" style="font-weight:600;font-size:13px">${guidedEsc(p.project_title || 'Untitled proposal')}</div><div class="report-item-meta" style="font-size:11px;color:var(--text-muted)">${guidedEsc(p.country || 'Country pending')} · ${guidedEsc(donorFor(p.donor).label || p.donor || 'Donor pending')}</div></div>`).join('') : '<div class="empty-state">No guided proposals yet</div>'; };
  const renderSteps = () => { if (!guidedProposalState.active) { steps.innerHTML = ''; return; } const current = guidedProposalState.step; steps.innerHTML = PROPOSAL_STEPS.map((s, i) => { const locked = statusFor(i + 1) === 'locked'; const active = i + 1 === current; return `<div class="wizard-step ${active ? 'active' : ''} ${locked ? 'complete' : ''}" data-guided-action="step" data-step="${i + 1}" ${i + 1 > current ? 'aria-disabled="true"' : ''}><span class="wizard-step-num">${locked ? '✓' : s.num}</span><span class="wizard-step-label">${s.label}</span><span class="wizard-step-icon">${locked ? '✓' : '○'}</span></div>`; }).join(''); const fill = document.getElementById('wizard-progress-fill'); if (fill) fill.style.width = `${((guidedProposalState.step - 1) / 4) * 100}%`; };
  const field = (label, key, value, type = 'text', extra = '') => `<label class="form-group" style="display:block;margin-bottom:14px"><span style="display:block;font-size:11px;font-weight:700;color:var(--text-muted);margin-bottom:5px">${label}</span>${type === 'textarea' ? `<textarea class="fi" data-guided-field="${key}" ${extra} style="width:100%;resize:vertical">${guidedEsc(value)}</textarea>` : `<input class="fi" data-guided-field="${key}" type="${type}" value="${guidedEsc(value)}" ${extra} style="width:100%">`}</label>`;
  const selectField = (label, key, value, options) => `<label class="form-group" style="display:block;margin-bottom:14px"><span style="display:block;font-size:11px;font-weight:700;color:var(--text-muted);margin-bottom:5px">${label}</span><select class="fi" data-guided-field="${key}" style="width:100%">${options.map(option => `<option value="${guidedEsc(option.value)}" ${option.value === value ? 'selected' : ''}>${guidedEsc(option.label)}</option>`).join('')}</select></label>`;
  const donorCard = proposal => { const donor = donorFor(proposal.donor); return `<div class="proposal-v2-donor-card"><div><span class="proposal-v2-kicker">Active donor framework</span><h4>${guidedEsc(donor.full_name || 'Choose a donor')}</h4><p>${guidedEsc(donor.framework_standard || 'Select a donor to load its rules.')}</p></div><div class="proposal-v2-rule-stats"><span><b>${guidedEsc((donor.currency_options || []).join(' / ') || '—')}</b>Currency</span><span><b>${donor.max_duration_months || '—'} mo</b>Max duration</span><span><b>${donor.overhead_ceiling_percent ?? '—'}%</b>Overhead ceiling</span></div>${donor.special_requirements?.length ? `<details><summary>Key donor requirements</summary><ul>${donor.special_requirements.slice(0,6).map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></details>` : ''}</div>`; };
  if (!document.getElementById('proposal-v2-matrix-style')) { const style = document.createElement('style'); style.id = 'proposal-v2-matrix-style'; style.textContent = '.proposal-v2-matrix-wrap{margin:8px 0 18px;overflow:auto;border:1px solid var(--border-light);border-radius:10px}.proposal-v2-editor-caption{display:flex;justify-content:space-between;gap:12px;padding:12px 14px;background:var(--bg-subtle);font-size:12px}.proposal-v2-editor-caption span{color:var(--text-muted);font-size:11px}.proposal-v2-matrix{width:100%;border-collapse:collapse;min-width:760px}.proposal-v2-matrix th,.proposal-v2-matrix td{padding:9px 8px;border-top:1px solid var(--border-light);font-size:11px;text-align:right}.proposal-v2-matrix th:first-child{text-align:left}.proposal-v2-matrix thead th{background:var(--bg-subtle);font-weight:700;color:var(--text-muted);white-space:nowrap}.proposal-v2-matrix input{width:72px;padding:6px;border:1px solid var(--border-light);border-radius:6px;text-align:right;background:var(--bg-card);color:var(--text-primary)}.proposal-v2-matrix .matrix-total{font-weight:800;color:var(--primary)}'; document.head.appendChild(style); }
  const showProposalInfoModal = (heading, contentHtml) => { document.getElementById('proposal-info-modal')?.remove(); document.body.insertAdjacentHTML('beforeend', `<div id="proposal-info-modal" class="proposal-preflight-backdrop"><div class="proposal-preflight-card call-brief-modal" role="dialog" aria-modal="true" aria-labelledby="proposal-info-title"><div class="proposal-preflight-head"><div><span class="proposal-v2-kicker">Proposal guidance</span><h3 id="proposal-info-title">${guidedEsc(heading)}</h3></div><button class="btn-icon-ghost" data-v2-action="close-info" aria-label="Close">×</button></div><div>${contentHtml}</div></div></div>`); };
  if (!document.getElementById('proposal-review-compact-style')) { const style = document.createElement('style'); style.id = 'proposal-review-compact-style'; style.textContent = '.proposal-review-compact{display:flex;flex-direction:column;gap:10px;padding:16px}.proposal-review-compact strong{font-size:38px;letter-spacing:-.06em}.proposal-review-compact-status{font-size:12px;font-weight:700}.proposal-review-compact-status.ok{color:#167b61}.proposal-review-compact-status.warn{color:#c0394b}'; document.head.appendChild(style); }
  if (!document.getElementById('proposal-document-style')) { const style = document.createElement('style'); style.id = 'proposal-document-style'; style.textContent = '.proposal-view-toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0 16px;border-bottom:1px solid var(--border-light);margin-bottom:18px;font-size:11px;font-weight:700;color:var(--text-muted)}.proposal-view-toolbar div{display:flex;gap:6px}.proposal-document-view{max-width:900px;margin:auto;background:var(--bg-card);padding:28px 34px;border:1px solid var(--border-light);border-radius:12px}.proposal-document-cover{padding-bottom:22px;border-bottom:2px solid var(--text-primary);margin-bottom:20px}.proposal-document-cover h3{font-size:26px;line-height:1.2;margin:8px 0}.proposal-document-cover p{margin:4px 0;color:var(--text-muted);font-size:12px}.proposal-document-section{margin:22px 0}.proposal-document-section h4{font-size:13px;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px}.proposal-document-section p{white-space:pre-wrap;line-height:1.7;color:var(--text-secondary);font-size:13px}.proposal-document-section pre{white-space:pre-wrap;background:var(--bg-subtle);padding:12px;border-radius:8px;font-size:11px;overflow:auto}.proposal-document-table{width:100%;border-collapse:collapse;font-size:11px}.proposal-document-table th,.proposal-document-table td{padding:9px;border:1px solid var(--border-light);vertical-align:top;text-align:left}.proposal-document-table th{background:var(--bg-subtle)}'; document.head.appendChild(style); }
  const notifyProposal = (message, type = 'success') => { let toast = document.getElementById('proposal-live-toast'); if (!toast) { toast = document.createElement('div'); toast.id = 'proposal-live-toast'; toast.setAttribute('aria-live','polite'); toast.style.cssText = 'position:fixed;right:24px;top:82px;z-index:3500;max-width:360px;padding:12px 16px;border-radius:10px;background:var(--bg-card);border:1px solid var(--border-light);box-shadow:0 12px 35px rgba(15,23,42,.18);font-size:12px;font-weight:700;'; document.body.appendChild(toast); } toast.textContent = message; toast.style.color = type === 'error' ? '#c0394b' : '#167b61'; clearTimeout(toast._timer); toast._timer = setTimeout(() => toast.remove(), 5000); };
  const enhanceBeneficiaryEditor = () => { if (guidedProposalState.step !== 2) return; const area = content.querySelector('[data-guided-field="beneficiaries"]'); if (!area || area.dataset.enhanced) return; area.dataset.enhanced = 'true'; let value = guidedJson(area.value, {}); const groups = [['host_communities','Host communities'],['idps','IDPs'],['refugees_returnees','Refugees / returnees']]; const fields = [['girls_0_17','Girls 0–17'],['boys_0_17','Boys 0–17'],['women_18_59','Women 18–59'],['men_18_59','Men 18–59'],['elderly_60_plus','Older people 60+'],['persons_with_disabilities','Persons with disabilities']]; const table = document.createElement('div'); table.className = 'proposal-v2-matrix-wrap'; table.innerHTML = `<div class="proposal-v2-editor-caption"><strong>Beneficiary matrix</strong><span>Disaggregate targets by population group and vulnerability.</span></div><table class="proposal-v2-matrix"><thead><tr><th>Population group</th>${fields.map(([,label]) => `<th>${label}</th>`).join('')}<th>Total</th></tr></thead><tbody>${groups.map(([group,label]) => `<tr><th>${label}</th>${fields.map(([key]) => `<td><input type="number" min="0" step="1" data-beneficiary-group="${group}" data-beneficiary-key="${key}" value="${Number(value[group]?.[key] || 0)}"></td>`).join('')}<td class="matrix-total" data-total-group="${group}">0</td></tr>`).join('')}</tbody></table>`; area.hidden = true; area.parentElement.insertBefore(table, area); const sync = () => { groups.forEach(([group]) => { value[group] = value[group] || {}; let total = 0; fields.forEach(([key]) => { const input = table.querySelector(`[data-beneficiary-group="${group}"][data-beneficiary-key="${key}"]`); value[group][key] = Number(input.value || 0); total += value[group][key]; }); table.querySelector(`[data-total-group="${group}"]`).textContent = total; }); area.value = JSON.stringify(value); }; table.addEventListener('input', sync); sync(); };
  const payload = (step) => { if (step === 3) syncTechnicalPayloadFields(); const out = {}; content.querySelectorAll('[data-guided-field]').forEach(el => { out[el.dataset.guidedField] = el.type === 'checkbox' ? el.checked : el.value; }); if (step === 1) out.sectors = String(out.sectors || '').split(',').map(x => x.trim()).filter(Boolean); if (step === 2) out.beneficiaries = guidedJson(out.beneficiaries, {}); ['logframe','gantt','budget_items','risks'].forEach(k => { if (k in out) out[k] = guidedJson(out[k], []); }); return out; };
  const actionBar = (step, locked) => locked ? `<div class="wizard-section-actions"><span class="wizard-status-badge wizard-status-complete">Locked — immutable</span></div>` : `<div class="wizard-section-actions" style="display:flex;gap:8px;flex-wrap:wrap;padding:12px 0;border-top:1px solid var(--border-light)"><button class="btn btn-secondary btn-sm" data-guided-action="generate" data-step="${step}">Generate draft</button><button class="btn btn-primary btn-sm" data-guided-action="analyze" data-step="${step}">Analyze with AI</button><button class="btn btn-green btn-sm" data-guided-action="lock" data-step="${step}">Confirm &amp; Lock Step ${step}</button></div>`;
    const render = () => { const p = guidedProposalState.active; renderList(); renderSteps(); if (!p) { title.textContent = 'Select or Create a Proposal'; context.textContent = 'Five-stage AI-assisted donor proposal workspace'; content.innerHTML = '<div class="proposal-welcome-placeholder"><div class="welcome-icon">📋</div><h3>Guided Proposal Workspace</h3><p>Build a complete donor-ready proposal through five locked stages. Your existing document view and review panel stay in place.</p><button class="btn btn-primary" data-guided-action="new">Create Guided Proposal</button></div>'; return; } title.textContent = p.project_title || 'Untitled proposal'; context.textContent = `${p.country || 'Country pending'} · ${p.donor || 'Donor pending'}${p.reference_filename ? ` · ${p.reference_filename}` : ''}`; const n = guidedProposalState.step; const locked = statusFor(n) === 'locked'; const analysis = n === 1 ? p.analysis : p[`step${n}_analysis`]; let body = `<div class="wizard-section-inner"><div class="wizard-section-header-row"><div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap"><h3>${PROPOSAL_STEPS[n - 1].num}. ${PROPOSAL_STEPS[n - 1].label}</h3><span class="wizard-status-badge wizard-status-${locked ? 'complete' : (analysis ? 'reviewing' : 'draft')}">${locked ? 'locked' : (analysis ? 'analyzed' : 'draft')}</span></div></div>`; if (n === 1) body += `<div class="up-grid">${field('Project title','project_title',p.project_title,'text','required minlength="10" maxlength="150"')}${field('Target country','country',p.country)}${field('Region / location','region',p.region)}${field('Primary donor','donor',p.donor)}${field('Estimated budget','budget_amount',p.budget_amount,'number','min="0.01" step="0.01"')}${field('Currency','budget_currency',p.budget_currency)}</div>${field('Executive intent','executive_intent',p.executive_intent,'textarea','minlength="100" maxlength="500" rows="6"')}${field('Sectors (comma separated)','sectors',(p.sectors || []).join(', '))}<div class="form-group"><label>Grant call document</label><input id="guided-reference-existing" type="file" accept=".docx,.txt,.md"><small>${guidedEsc(p.reference_filename || 'No document attached')}</small></div>`; else if (n === 2) { const d = p.context_data || {}; body += `${field('Humanitarian context','humanitarian_context',d.humanitarian_context || '','textarea','rows="9"')}${field('Needs assessment','needs_assessment',d.needs_assessment || '','textarea','rows="9"')}${field('Strategic justification','strategic_justification',d.strategic_justification || '','textarea','rows="9"')}${field('Beneficiary matrix (JSON)','beneficiaries',JSON.stringify(d.beneficiaries || {}, null, 2),'textarea','rows="8"')}`; } else if (n === 3) { const d = p.technical_data || {}; body += `${field('Theory of Change narrative','toc_narrative',d.toc_narrative || '','textarea','rows="6"')}${field('Logframe matrix (JSON)','logframe',JSON.stringify(d.logframe || [], null, 2),'textarea','rows="16"')}${field('Activity schedule (JSON)','gantt',JSON.stringify(d.gantt || [], null, 2),'textarea','rows="6"')}`; } else if (n === 4) { const d = p.financial_data || {}; body += `${field('Budget items (JSON)','budget_items',JSON.stringify(d.budget_items || [], null, 2),'textarea','rows="14"')}${field('Risk matrix (JSON)','risks',JSON.stringify(d.risks || [], null, 2),'textarea','rows="10"')}<label style="display:flex;gap:8px;align-items:center;margin:12px 0"><input type="checkbox" data-guided-field="psea_signoff" ${d.psea_signoff ? 'checked' : ''}> PSEA / IASC core principles sign-off</label>${field('Sphere standards narrative','sphere_standards_narrative',d.sphere_standards_narrative || '','textarea','rows="5"')}`; } else body += `<div class="proposal-narrative-card"><p>All four stages must be locked before final review.</p><button class="btn btn-primary" data-guided-action="summary">Refresh locked summary</button> <button class="btn btn-secondary" data-guided-action="evaluate">Run PRAG evaluation</button> <button class="btn btn-primary" data-guided-action="pdf">Compile PDF</button><pre id="guided-final-output" style="white-space:pre-wrap;margin-top:16px"></pre></div>`; body += actionBar(n, locked) + '</div>'; content.innerHTML = body; document.getElementById('review-content').innerHTML = guidedAnalysisCard(analysis); };
  const refresh = async () => { guidedProposalState.setups = await guidedRequest('/api/proposals/setups'); if (!guidedProposalState.active && guidedProposalState.setups[0]) guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.setups[0].id}`); render(); };
  const openPreflight = () => { if (document.getElementById('proposal-preflight-modal')) return; panel.insertAdjacentHTML('beforeend', `<div id="proposal-preflight-modal" class="proposal-preflight-backdrop"><div class="proposal-preflight-card" role="dialog" aria-modal="true" aria-labelledby="proposal-preflight-title"><div class="proposal-preflight-head"><div><span class="proposal-v2-kicker">Proposal intake</span><h3 id="proposal-preflight-title">Start a new proposal</h3><p>Upload the donor call and add only the basics. The detailed Project Setup comes next.</p></div><button class="btn-icon-ghost" data-v2-preflight="cancel" aria-label="Close">×</button></div><div class="up-grid"><label class="form-group"><span>Project title</span><input class="fi" data-preflight-field="project_title" minlength="10" maxlength="150" placeholder="e.g. Preventing CEFM in Eastern Türkiye" required></label><label class="form-group"><span>Target country</span><input class="fi" data-preflight-field="country" list="proposal-preflight-countries" placeholder="Select or type a country" required><datalist id="proposal-preflight-countries">${(guidedProposalState.countries || []).slice(0,200).map(c => `<option value="${guidedEsc(typeof c === 'string' ? c : c.name || c.country || '')}">`).join('')}</datalist></label></div><label class="form-group"><span>Initial executive intent <em style="font-style:normal;font-weight:400">optional · 100–500 characters</em></span><textarea class="fi" data-preflight-field="executive_intent" rows="4" minlength="100" maxlength="500" placeholder="You can leave this empty and shape it in Project Setup."></textarea></label><label class="proposal-preflight-upload"><strong>Grant call document</strong><span>Required · DOCX, TXT or Markdown</span><input type="file" data-preflight-field="reference" accept=".docx,.txt,.md" required></label><div class="proposal-preflight-actions"><button class="btn btn-secondary" data-v2-preflight="cancel">Cancel</button><button class="btn btn-primary" data-v2-preflight="submit">Open Project Setup</button></div></div></div>`); };
  const create = async () => openPreflight();
  panel.addEventListener('click', async e => { const submit = e.target.closest('[data-v2-preflight="submit"]'); if (!submit) return; e.preventDefault(); e.stopImmediatePropagation(); const modal = document.getElementById('proposal-preflight-modal'); const value = key => modal?.querySelector(`[data-preflight-field="${key}"]`)?.value?.trim() || ''; const file = modal?.querySelector('[data-preflight-field="reference"]')?.files?.[0]; if (!modal || !file || !value('project_title') || !value('country')) { setNotice('Project title, target country and a grant call document are required.', true); return; } try { const data = {project_title:value('project_title'),country:value('country'),region:'',donor:'generic',budget_amount:null,budget_currency:'USD',executive_intent:value('executive_intent'),sectors:[]}; guidedProposalState.active = await guidedRequest('/api/proposals/setups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); const fd = new FormData(); fd.append('file',file); await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`,{method:'POST',body:fd}); guidedProposalState.step = 1; modal.remove(); await refresh(); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); render(); setNotice('Project Setup opened. Complete donor, budget and the remaining Step 1 rules.'); } catch (err) { setNotice(err.message, true); } }, true);
  if (!document.getElementById('proposal-preflight-style')) { const style = document.createElement('style'); style.id = 'proposal-preflight-style'; style.textContent = '.proposal-preflight-backdrop{position:fixed;inset:0;z-index:3000;display:grid;place-items:center;padding:24px;background:rgba(15,23,42,.42)}.proposal-preflight-card{width:min(760px,100%);max-height:90vh;overflow:auto;background:var(--bg-card);border:1px solid var(--border-light);border-radius:16px;box-shadow:0 24px 80px rgba(15,23,42,.24);padding:24px}.proposal-preflight-head{display:flex;justify-content:space-between;gap:20px;margin-bottom:20px}.proposal-preflight-head h3{margin:5px 0;font-size:20px}.proposal-preflight-head p{margin:0;color:var(--text-muted);font-size:12px;line-height:1.5}.proposal-preflight-upload{display:flex;flex-direction:column;gap:5px;padding:15px;border:1px dashed var(--border);border-radius:10px;margin-top:8px;font-size:12px}.proposal-preflight-upload span{color:var(--text-muted);font-size:11px}.proposal-preflight-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:22px;padding-top:16px;border-top:1px solid var(--border-light)}.proposal-list-delete{margin-left:auto;border:0;background:transparent;color:var(--text-muted);cursor:pointer;padding:2px 5px;border-radius:5px}.proposal-list-delete:hover{background:#fff0f0;color:#c0394b}'; document.head.appendChild(style); }
  const syncDeleteControls = () => { list.querySelectorAll('[data-guided-action="select"]').forEach(row => { if (row.querySelector('[data-v2-action="delete"]')) return; const id = row.dataset.id; const button = document.createElement('button'); button.className = 'proposal-list-delete'; button.dataset.v2Action = 'delete'; button.dataset.id = id; button.title = 'Delete proposal'; button.setAttribute('aria-label','Delete proposal'); button.textContent = '×'; row.appendChild(button); }); };
  panel.addEventListener('click', async e => { const preflight = e.target.closest('[data-v2-preflight]'); const action = preflight?.dataset.v2Preflight; const deleteButton = e.target.closest('[data-v2-action="delete"]'); if (action === 'cancel') { document.getElementById('proposal-preflight-modal')?.remove(); return; } if (action === 'submit') { const modal = document.getElementById('proposal-preflight-modal'); if (!modal) return; const value = key => modal.querySelector(`[data-preflight-field="${key}"]`)?.value?.trim() || ''; const file = modal.querySelector('[data-preflight-field="reference"]')?.files?.[0]; const required = ['project_title','country','donor','budget_amount','executive_intent']; if (!file || required.some(key => !value(key))) { setNotice('Please complete the title, country, donor, budget, intent and call document before creating the setup.', true); return; } e.preventDefault(); try { const data = {project_title:value('project_title'),country:value('country'),region:value('region'),donor:value('donor'),budget_amount:Number(value('budget_amount')),budget_currency:modal.querySelector('[data-preflight-field="budget_currency"]')?.value || 'USD',executive_intent:value('executive_intent'),sectors:[]}; guidedProposalState.active = await guidedRequest('/api/proposals/setups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); const fd = new FormData(); fd.append('file',file); await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`,{method:'POST',body:fd}); guidedProposalState.step = 1; modal.remove(); await refresh(); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); render(); setNotice('Project Setup created. Donor rules and call brief are ready for review.'); } catch (err) { setNotice(err.message, true); } return; } if (deleteButton) { e.preventDefault(); e.stopImmediatePropagation(); const id = deleteButton.dataset.id; if (!id || !confirm('Delete this proposal permanently?')) return; try { await guidedRequest(`/api/proposals/setups/${id}`,{method:'DELETE'}); if (guidedProposalState.active?.id === id) guidedProposalState.active = null; await refresh(); if (!guidedProposalState.active && guidedProposalState.setups[0]) guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.setups[0].id}`); guidedProposalState.step = guidedProposalState.active?.state === 'locked' ? 2 : 1; render(); } catch (err) { setNotice(err.message, true); } } });
  panel.addEventListener('change', async e => { const input = e.target.closest('#guided-reference-existing'); if (!input || !input.files?.[0] || !guidedProposalState.active) return; e.preventDefault(); e.stopImmediatePropagation(); try { const fd = new FormData(); fd.append('file', input.files[0]); await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`,{method:'POST',body:fd}); await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/call-brief`,{method:'POST'}); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); render(); setNotice('Call brief generated and saved for this document.'); } catch (err) { setNotice(err.message, true); } }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action="analyze"], [data-guided-action="lock"]'); if (!target || !guidedProposalState.active || Number(target.dataset.step || guidedProposalState.step) !== 1) return; e.preventDefault(); e.stopImmediatePropagation(); const p = guidedProposalState.active; const data = payload(1); const base = `/api/proposals/setups/${p.id}`; try { await guidedRequest(base,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); if (target.dataset.guidedAction === 'analyze') { const result = await guidedRequest(`${base}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); p.analysis = result; render(); notifyProposal(result.is_valid ? `AI review complete: ${result.donor_compliance_score || 0}/100. Review feedback is ready.` : 'AI review found issues. Open View AI review for details.', result.is_valid ? 'success' : 'error'); return; } notifyProposal('Rechecking the current Step 1 fields before locking…'); const result = await guidedRequest(`${base}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); p.analysis = result; if (!result.is_valid || Number(result.donor_compliance_score || 0) < 70) { render(); notifyProposal('Step 1 still has validation issues. Open View AI review and fix them before locking.', 'error'); return; } const locked = await guidedRequest(`${base}/lock`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); guidedProposalState.active = locked; guidedProposalState.step = 2; await refresh(); render(); notifyProposal('Step 1 locked successfully. Context & Needs is now unlocked.'); } catch (err) { notifyProposal(err.message || 'Step 1 could not be locked.', 'error'); setNotice(err.message, true); } }, true);
  panel.addEventListener('click', e => { const target = e.target.closest('[data-v2-action="view-edit"], [data-v2-action="view-document"]'); if (!target) return; e.preventDefault(); e.stopImmediatePropagation(); guidedProposalState.viewMode = target.dataset.v2Action === 'view-document' ? 'document' : 'edit'; if (guidedProposalState.viewMode === 'document') { content.innerHTML = `<div class="proposal-view-toolbar"><span>Workspace view</span><div><button class="btn btn-secondary btn-sm" data-v2-action="view-edit">Edit</button><button class="btn btn-secondary btn-sm" data-v2-action="view-document">Document view</button></div></div>${documentViewHtml()}`; formatBeneficiaryDocument(); } else render(); }, true);
  panel.addEventListener('click', e => { const target = e.target.closest('[data-guided-action="step"]'); if (!target || !guidedProposalState.active) return; const n = Number(target.dataset.step); if (n > maxReachableStep()) return; e.preventDefault(); e.stopImmediatePropagation(); guidedProposalState.step = n; render(); }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action="generate"]'); if (!target || Number(target.dataset.step || guidedProposalState.step) !== 3 || !guidedProposalState.active) return; e.preventDefault(); e.stopImmediatePropagation(); try { notifyProposal('Generating Technical Design draft…'); const result = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/generate-step3-draft`,{method:'POST'}); guidedProposalState.active.technical_data = result.draft || {}; render(); notifyProposal('Technical Design draft is ready. Review and edit it before analysis.'); } catch (err) { notifyProposal(err.message || 'Technical Design draft could not be generated.', 'error'); } }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action]'); if (!target) return; e.preventDefault(); e.stopImmediatePropagation(); try { const a = target.dataset.guidedAction; if (a === 'new') return create(); if (a === 'select') { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${target.dataset.id}`); guidedProposalState.step = guidedProposalState.active.state === 'locked' ? 2 : 1; return render(); } if (a === 'step') { const n = Number(target.dataset.step); if (n <= guidedProposalState.step) { guidedProposalState.step = n; render(); } return; } const p = guidedProposalState.active; if (!p) return; const step = Number(target.dataset.step || guidedProposalState.step); const base = step === 1 ? `/api/proposals/setups/${p.id}` : `/api/proposals/steps/${step}`; const data = payload(step); if (a === 'generate') { const result = await guidedRequest(step === 1 ? `/api/proposals/setups/${p.id}/generate-draft` : `/api/proposals/setups/${p.id}/generate-step2-draft`,{method:'POST'}); if (step === 1 && result.draft) Object.assign(p,result.draft); if (step === 2 && result.draft) p.context_data = result.draft; return render(); } if (step === 1 && (a === 'analyze' || a === 'lock')) { await guidedRequest(`/api/proposals/setups/${p.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); } if (a === 'analyze') { const result = await guidedRequest(`${base}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data, ...(step > 1 ? {setup_id:p.id} : {})})}); if (step === 1) p.analysis = result; else p[`step${step}_analysis`] = result; setNotice(result.is_valid ? 'Analysis complete. Review the feedback before locking.' : 'Analysis found issues to address.', !result.is_valid); return render(); } if (a === 'lock') { const result = await guidedRequest(`${base}/lock`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data, ...(step > 1 ? {setup_id:p.id} : {})})}); guidedProposalState.active = result; guidedProposalState.step = Math.min(5, step + 1); await refresh(); return render(); } if (a === 'summary' || a === 'evaluate') { const result = await guidedRequest(`/api/proposals/setups/${p.id}/${a === 'summary' ? 'summary' : 'evaluate'}`,{method:a === 'summary' ? 'GET' : 'POST'}); const out = document.getElementById('guided-final-output'); if (out) out.textContent = JSON.stringify(result,null,2); } if (a === 'pdf') { const response = await api(`/api/proposals/setups/${p.id}/compile-pdf`,{method:'POST'}); if (!response.ok) throw new Error('PDF compilation failed'); const link = document.createElement('a'); link.href = URL.createObjectURL(await response.blob()); link.download = `${p.project_title || 'proposal'}.pdf`; link.click(); } } catch (err) { setNotice(err.message, true); } });
  panel.addEventListener('change', async e => { if (e.target.id !== 'guided-reference-existing' || !guidedProposalState.active || !e.target.files[0]) return; const fd = new FormData(); fd.append('file',e.target.files[0]); try { await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`,{method:'POST',body:fd}); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); render(); } catch (err) { setNotice(err.message,true); } });
  document.getElementById('btn-new-proposal')?.addEventListener('click', e => { e.preventDefault(); e.stopImmediatePropagation(); create(); }, true);
  const syncDonorContext = () => {};
  const syncReviewPanel = () => { const review = document.getElementById('review-content'); const p = guidedProposalState.active; if (!review || !p) return; const analysis = guidedProposalState.step === 1 ? p.analysis : p[`step${guidedProposalState.step}_analysis`]; if (!analysis || review.querySelector('[data-v2-action="ai-review"]')) return; const score = Number(analysis.donor_compliance_score || 0); const valid = analysis.is_valid === true; review.innerHTML = `<div class="proposal-review-compact"><span class="proposal-v2-kicker">Assistant review</span><strong>${score}/100</strong><span class="proposal-review-compact-status ${valid ? 'ok' : 'warn'}">${valid ? 'Ready to continue' : 'Needs attention'}</span><button class="btn btn-secondary btn-sm" data-v2-action="ai-review">View AI review</button></div>`; };
  const documentViewHtml = () => { const p = guidedProposalState.active || {}; const n = guidedProposalState.step; const d = n === 2 ? (p.context_data || {}) : n === 3 ? (p.technical_data || {}) : n === 4 ? (p.financial_data || {}) : {}; const block = (label, value) => value ? `<section class="proposal-document-section"><h4>${label}</h4><p>${guidedEsc(value)}</p></section>` : ''; const rows = Array.isArray(d.logframe) ? d.logframe.map(row => `<tr><td>${guidedEsc(row.id || row.level || '')}</td><td>${guidedEsc(row.intervention_logic || '')}</td><td>${guidedEsc(row.parent_id || '—')}</td><td>${guidedEsc((row.indicators || []).map(i => i.indicator_title || i.title || '').filter(Boolean).join('; '))}</td></tr>`).join('') : ''; return `<div class="proposal-document-view"><div class="proposal-document-cover"><span class="proposal-v2-kicker">Document view · Step ${n}</span><h3>${guidedEsc(p.project_title || 'Untitled proposal')}</h3><p>${guidedEsc([p.country,p.region].filter(Boolean).join(' · '))}</p><p>${guidedEsc(donorFor(p.donor).full_name || p.donor || '')}</p></div>${n === 1 ? `${block('Executive intent',p.executive_intent)}${block('Sectors',(p.sectors || []).join(', '))}` : ''}${n === 2 ? `${block('Humanitarian context',d.humanitarian_context)}${block('Needs assessment',d.needs_assessment)}${block('Strategic justification',d.strategic_justification)}${d.beneficiaries ? `<section class="proposal-document-section"><h4>Beneficiaries</h4><pre>${guidedEsc(JSON.stringify(d.beneficiaries,null,2))}</pre></section>` : ''}` : ''}${n === 3 ? `${block('Theory of Change',d.toc_narrative)}${rows ? `<section class="proposal-document-section"><h4>Logical framework</h4><table class="proposal-document-table"><thead><tr><th>ID</th><th>Intervention logic</th><th>Parent</th><th>Indicators</th></tr></thead><tbody>${rows}</tbody></table></section>` : ''}` : ''}${n === 4 ? `${d.budget_items?.length ? `<section class="proposal-document-section"><h4>Budget</h4><pre>${guidedEsc(JSON.stringify(d.budget_items,null,2))}</pre></section>` : ''}${d.risks?.length ? `<section class="proposal-document-section"><h4>Risk matrix</h4><pre>${guidedEsc(JSON.stringify(d.risks,null,2))}</pre></section>` : ''}` : ''}</div>`; };
  const formatBeneficiaryDocument = () => { const section = [...content.querySelectorAll('.proposal-document-section')].find(el => el.querySelector('h4')?.textContent === 'Beneficiaries'); const beneficiaries = guidedProposalState.active?.context_data?.beneficiaries; if (!section || !beneficiaries) return; const cols = [['girls_0_17','Girls 0–17'],['boys_0_17','Boys 0–17'],['women_18_59','Women 18–59'],['men_18_59','Men 18–59'],['elderly_60_plus','Older people 60+'],['persons_with_disabilities','Persons with disabilities']]; const groups = [['host_communities','Host communities'],['idps','IDPs'],['refugees_returnees','Refugees / returnees']]; section.innerHTML = `<h4>Beneficiaries</h4><div class="proposal-document-table-wrap"><table class="proposal-document-table beneficiary-document-table"><thead><tr><th>Population group</th>${cols.map(([,label]) => `<th>${label}</th>`).join('')}<th>Total</th></tr></thead><tbody>${groups.map(([key,label]) => { const row = beneficiaries[key] || {}; const total = cols.reduce((sum,[field]) => sum + Number(row[field] || 0), 0); return `<tr><th>${label}</th>${cols.map(([field]) => `<td>${Number(row[field] || 0)}</td>`).join('')}<td><strong>${total}</strong></td></tr>`; }).join('')}</tbody></table></div>`; };
  if (!document.getElementById('proposal-beneficiary-document-style')) { const style = document.createElement('style'); style.id = 'proposal-beneficiary-document-style'; style.textContent = '.proposal-document-table-wrap{overflow:auto}.beneficiary-document-table{min-width:760px}.beneficiary-document-table th,.beneficiary-document-table td{white-space:nowrap}'; document.head.appendChild(style); }
  const syncViewToolbar = () => { if (!content.querySelector('.proposal-view-toolbar')) content.insertAdjacentHTML('afterbegin', '<div class="proposal-view-toolbar"><span>Workspace view</span><div><button class="btn btn-secondary btn-sm" data-v2-action="view-edit">Edit</button><button class="btn btn-secondary btn-sm" data-v2-action="view-document">Document view</button></div></div>'); };
  const syncCallBrief = () => { const p = guidedProposalState.active; if (!p?.reference_text || guidedProposalState.step !== 1 || content.querySelector('[data-v2-action="call-brief"]')) return; const file = content.querySelector('#guided-reference-existing'); if (file?.parentElement) file.parentElement.insertAdjacentHTML('beforeend', ' <button class="btn btn-secondary btn-sm" data-v2-action="call-brief">Open call brief</button>'); };
  const ensureCallBrief = async () => { const p = guidedProposalState.active; if (!p?.reference_text || p.call_brief && Object.keys(p.call_brief).length || guidedProposalState.step !== 1 || callBriefBusy) return; callBriefBusy = true; try { const result = await guidedRequest(`/api/proposals/setups/${p.id}/call-brief`,{method:'POST'}); p.call_brief = result.brief || {}; } catch (err) { setNotice('Call brief could not be generated yet. You can retry from the document action.', true); } finally { callBriefBusy = false; } };
  const enhanceDonorField = () => { if (guidedProposalState.step !== 1) return; const input = content.querySelector('[data-guided-field="donor"]'); if (!input || input.tagName === 'SELECT' || !donors.length) return; const select = document.createElement('select'); select.className = input.className; select.style.cssText = input.style.cssText; select.dataset.guidedField = 'donor'; donors.forEach(d => { const option = document.createElement('option'); option.value = d.id; option.textContent = d.label || d.full_name || d.id; option.selected = d.id === input.value; select.appendChild(option); }); select.addEventListener('change', () => { if (guidedProposalState.active) guidedProposalState.active.donor = select.value; const card = document.getElementById('review-content')?.querySelector('.proposal-v2-donor-card'); if (card && guidedProposalState.active) card.outerHTML = donorCard(guidedProposalState.active); }); input.replaceWith(select); if (!select.parentElement.querySelector('[data-v2-action="donor-rules"]')) select.parentElement.insertAdjacentHTML('beforeend', '<button class="btn btn-secondary btn-sm" data-v2-action="donor-rules" style="margin-top:4px">Donor requirements</button>'); };
  const enforceLock = () => { if (statusFor(guidedProposalState.step) !== 'locked') return; content.querySelectorAll('[data-guided-field], .proposal-v2-matrix input').forEach(el => { el.disabled = true; el.setAttribute('aria-readonly','true'); }); };
  new MutationObserver(() => { syncDonorContext(); syncCallBrief(); enhanceDonorField(); enhanceBeneficiaryEditor(); enforceLock(); syncDeleteControls(); ensureCallBrief(); syncReviewPanel(); syncViewToolbar(); }).observe(content, {childList:true});
  new MutationObserver(syncStepNavigation).observe(steps, {childList:true});
  new MutationObserver(syncDeleteControls).observe(list, {childList:true});
  panel.addEventListener('click', e => { const button = e.target.closest('[data-v2-action="ai-review"]'); if (!button) return; e.preventDefault(); e.stopImmediatePropagation(); const p = guidedProposalState.active; const analysis = guidedProposalState.step === 1 ? p?.analysis : p?.[`step${guidedProposalState.step}_analysis`]; if (!analysis) return; const list = key => (analysis[key] || []).map(item => `<li>${guidedEsc(typeof item === 'string' ? item : item.message || JSON.stringify(item))}</li>`).join(''); showProposalInfoModal('Assistant review', `<div class="guided-score"><strong>${Number(analysis.donor_compliance_score || 0)}</strong><span>/ 100 compliance</span></div><p class="proposal-review-compact-status ${analysis.is_valid ? 'ok' : 'warn'}">${analysis.is_valid ? 'Ready to continue' : 'Needs attention'}</p>${analysis.critique_notes?.length ? `<section><h4>Feedback</h4><ul>${list('critique_notes')}</ul></section>` : ''}${analysis.violations?.length ? `<section><h4>Violations</h4><ul class="guided-violations">${list('violations')}</ul></section>` : ''}${analysis.suggested_improvements?.length ? `<section><h4>Suggested improvements</h4><ul>${list('suggested_improvements')}</ul></section>` : ''}${analysis.warnings?.length ? `<section><h4>Warnings</h4><ul>${list('warnings')}</ul></section>` : ''}`); }, true);
  panel.addEventListener('click', async e => { const button = e.target.closest('[data-v2-action="call-brief"]'); if (!button || !guidedProposalState.active) return; e.preventDefault(); e.stopImmediatePropagation(); try { const result = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/call-brief`, {method:'POST'}); const brief = result.brief || {}; const sections = ['eligible_applicants','priority_outcomes','required_deliverables','financial_and_timing','evaluation_criteria','open_questions']; showProposalInfoModal('Grant call brief', `<p>${guidedEsc(brief.overview || 'No overview available.')}</p>${sections.map(key => `<section><h4>${guidedEsc(key.replaceAll('_',' '))}</h4><ul>${(brief[key] || []).map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></section>`).join('')}`); } catch (err) { setNotice(err.message, true); } }, true);
  panel.addEventListener('click', e => { const button = e.target.closest('[data-v2-action="donor-rules"]'); if (!button) return; e.preventDefault(); e.stopImmediatePropagation(); const donor = donorFor(guidedProposalState.active?.donor); const rules = donor.special_requirements || []; showProposalInfoModal(`${donor.label || donor.full_name || 'Donor'} rules`, `<p>${guidedEsc(donor.framework_standard || '')}</p><section><h4>Core constraints</h4><ul><li>Currency: ${guidedEsc((donor.currency_options || []).join(' / ') || 'Not specified')}</li><li>Maximum duration: ${guidedEsc(String(donor.max_duration_months || 'Not specified'))} months</li><li>Overhead ceiling: ${guidedEsc(String(donor.overhead_ceiling_percent ?? 'Not specified'))}%</li></ul></section><section><h4>Special requirements</h4><ul>${rules.map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></section>`); }, true);
  document.addEventListener('click', e => { if (e.target.closest('[data-v2-action="close-info"]') || e.target.id === 'proposal-info-modal') document.getElementById('proposal-info-modal')?.remove(); });
  panel.addEventListener('click', async e => { const button = e.target.closest('[data-v2-action="call-brief"]'); if (!button || !guidedProposalState.active) return; e.preventDefault(); try { const result = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/call-brief`, {method:'POST'}); const review = document.getElementById('review-content'); if (review) review.innerHTML = `<div class="call-brief-modal"><span class="proposal-v2-kicker">Grant call brief</span><p>${guidedEsc(result.brief?.overview || 'No overview available.')}</p>${['eligible_applicants','priority_outcomes','required_deliverables','financial_and_timing','evaluation_criteria','open_questions'].map(key => `<section><h4>${guidedEsc(key.replaceAll('_',' '))}</h4><ul>${(result.brief?.[key] || []).map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></section>`).join('')}</div>`; } catch (err) { setNotice(err.message, true); } });
  (async () => { try { const [countries, donorData] = await Promise.all([guidedRequest('/api/db/countries'), guidedRequest('/api/proposals/donors')]); guidedProposalState.countries = Array.isArray(countries) ? countries : []; donors = Array.isArray(donorData) ? donorData : []; await refresh(); } catch (err) { setNotice(err.message,true); } })();
}

// Retained reference mount for the earlier Step-1-only experiment. The active
// Guided Proposal mount is defined immediately above and includes all five
// stages; keep this implementation named so it cannot shadow the active one.
function initGuidedProposalPipelineStep1Reference() {
  const panel = document.getElementById('panel-proposal');
  const list = document.getElementById('proposal-list');
  const steps = document.getElementById('wizard-steps-list');
  const content = document.getElementById('wizard-section-content');
  const title = document.getElementById('proposal-project-title');
  const context = document.getElementById('proposal-project-context');
  const review = document.getElementById('review-content');
  if (!panel || !list || !steps || !content || !title || !context || !review) return;

  let donors = [];
  const stepState = (proposal, step) => step === 1 ? proposal.state : proposal[`step${step}_state`];
  const unlockedStep = proposal => {
    if (!proposal || proposal.state !== 'locked') return 1;
    if (proposal.step2_state !== 'locked') return 2;
    if (proposal.step3_state !== 'locked') return 3;
    if (proposal.step4_state !== 'locked') return 4;
    return 5;
  };
  const donorFor = id => donors.find(d => d.id === id) || donors.find(d => d.id === 'generic') || {};
  const options = (items, selected) => items.map(item => `<option value="${guidedEsc(item.value)}" ${item.value === selected ? 'selected' : ''}>${guidedEsc(item.label)}</option>`).join('');
  const showReview = analysis => {
    if (!analysis) { review.innerHTML = '<div style="text-align:center;padding:34px 12px;color:var(--text-muted);font-size:13px">Choose a donor and run <strong>Analyze setup</strong> to see compliance feedback here.</div>'; return; }
    review.innerHTML = guidedAnalysisCard(analysis);
  };
  const showCallBrief = brief => {
    const modal = document.getElementById('proposal-diff-modal');
    const body = document.getElementById('proposal-diff-content');
    if (!modal || !body) return;
    body.innerHTML = `<div class="call-brief-modal"><p>${guidedEsc(brief.overview || '')}</p>${['eligible_applicants','priority_outcomes','required_deliverables','financial_and_timing','evaluation_criteria','open_questions'].map(key => `<section><h4>${guidedEsc(key.replaceAll('_',' '))}</h4><ul>${(brief[key] || []).map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></section>`).join('')}</div>`;
    modal.querySelector('.modal-hdr .modal-title').textContent = 'Call Brief';
    modal.classList.add('open');
  };
  const readStep1 = () => {
    const values = {};
    content.querySelectorAll('[data-v2-field]').forEach(el => { values[el.dataset.v2Field] = el.value; });
    values.sectors = String(values.sectors || '').split(',').map(x => x.trim()).filter(Boolean);
    values.budget_amount = values.budget_amount || null;
    return values;
  };
  const renderList = () => {
    list.innerHTML = guidedProposalState.setups.length
      ? guidedProposalState.setups.map(p => `<div class="report-item ${p.id === guidedProposalState.active?.id ? 'active' : ''}" data-v2-action="select" data-id="${guidedEsc(p.id)}" style="cursor:pointer;padding:10px;border-bottom:1px solid var(--border-light);position:relative"><div class="report-item-title" style="font-weight:600;font-size:13px">${guidedEsc(p.project_title || 'Untitled proposal')}</div><div class="report-item-meta" style="font-size:11px;color:var(--text-muted)">${guidedEsc(p.country || 'Country pending')} · Step ${unlockedStep(p)} of 5</div></div>`).join('')
      : '<div class="empty-state">No guided proposals yet</div>';
  };
  const renderSteps = () => {
    const active = guidedProposalState.active;
    if (!active) { steps.innerHTML = ''; return; }
    steps.innerHTML = PROPOSAL_STEPS.map(step => {
      const state = stepState(active, step.num) || 'draft';
      const locked = state === 'locked';
      const current = guidedProposalState.step === step.num;
      const reachable = step.num <= unlockedStep(active);
      return `<div class="wizard-step ${current ? 'active' : ''} ${locked ? 'complete' : ''}" ${reachable ? `data-v2-action="step" data-step="${step.num}"` : 'aria-disabled="true"'}><span class="wizard-step-num">${locked ? '✓' : step.num}</span><span class="wizard-step-label">${step.label}</span><span class="wizard-step-icon">${locked ? '✓' : '○'}</span></div>`;
    }).join('');
    const fill = document.getElementById('wizard-progress-fill');
    if (fill) fill.style.width = `${((unlockedStep(active) - 1) / 4) * 100}%`;
  };
  const actionBar = (step, isLocked) => isLocked
    ? '<div class="wizard-section-actions"><span class="wizard-status-badge wizard-status-complete">Locked — this stage is now immutable</span></div>'
    : `<div class="wizard-section-actions" style="display:flex;gap:8px;flex-wrap:wrap;padding-top:16px;border-top:1px solid var(--border-light)"><button class="btn btn-secondary btn-sm" data-v2-action="generate" data-step="${step}">Generate draft</button><button class="btn btn-primary btn-sm" data-v2-action="analyze" data-step="${step}">Analyze setup</button><button class="btn btn-green btn-sm" data-v2-action="lock" data-step="${step}">Confirm &amp; Lock Step ${step}</button></div>`;
  const renderSetup = (proposal, locked) => {
    const donor = donorFor(proposal.donor);
    const currencies = donor.currency_options || ['USD', 'EUR'];
    const donorOptions = donors.map(d => ({ value:d.id, label:d.label }));
    const countryOptions = guidedProposalState.countries.map(c => ({ value:c, label:c }));
    return `<div class="wizard-section-inner"><div class="wizard-section-header-row"><div><h3>1. Project Setup</h3><p class="text-muted" style="margin-top:4px;font-size:13px">Set the contract the next stages will follow. After lock, these inputs cannot be changed.</p></div><span class="wizard-status-badge wizard-status-${locked ? 'complete' : proposal.analysis ? 'reviewing' : 'draft'}">${locked ? 'locked' : proposal.analysis ? 'analyzed' : 'draft'}</span></div><div class="proposal-v2-donor-card"><div><span class="proposal-v2-kicker">Active donor framework</span><h4>${guidedEsc(donor.full_name || 'Choose a donor')}</h4><p>${guidedEsc(donor.framework_standard || 'Select a primary donor to load its proposal rules.')}</p></div><div class="proposal-v2-rule-stats"><span><b>${guidedEsc((donor.currency_options || []).join(' / ') || '—')}</b>Currency</span><span><b>${donor.max_duration_months || '—'} mo</b>Max duration</span><span><b>${donor.overhead_ceiling_percent ?? '—'}%</b>Overhead ceiling</span></div>${donor.special_requirements?.length ? `<details open><summary>Key donor requirements</summary><ul>${donor.special_requirements.slice(0,5).map(item => `<li>${guidedEsc(item)}</li>`).join('')}</ul></details>` : ''}</div><div class="up-grid"><label class="form-group"><span>Project title</span><input class="fi" data-v2-field="project_title" value="${guidedEsc(proposal.project_title)}" ${locked ? 'disabled' : ''} minlength="10" maxlength="150"></label><label class="form-group"><span>Target country</span><input class="fi" list="proposal-v2-countries" data-v2-field="country" value="${guidedEsc(proposal.country)}" ${locked ? 'disabled' : ''}></label><label class="form-group"><span>Region / location</span><input class="fi" data-v2-field="region" value="${guidedEsc(proposal.region)}" ${locked ? 'disabled' : ''}></label><label class="form-group"><span>Primary donor</span><select class="fi" data-v2-field="donor" ${locked ? 'disabled' : ''}>${options(donorOptions,proposal.donor)}</select></label><label class="form-group"><span>Estimated budget</span><input class="fi" type="number" min="0.01" step="0.01" data-v2-field="budget_amount" value="${guidedEsc(proposal.budget_amount || '')}" ${locked ? 'disabled' : ''}></label><label class="form-group"><span>Currency</span><select class="fi" data-v2-field="budget_currency" ${locked ? 'disabled' : ''}>${options(currencies.map(value => ({value,label:value})),proposal.budget_currency)}</select></label></div><datalist id="proposal-v2-countries">${countryOptions.map(item => `<option value="${guidedEsc(item.value)}">`).join('')}</datalist><label class="form-group" style="display:block"><span>Executive intent <em style="font-style:normal;font-weight:400">100–500 characters</em></span><textarea class="fi" data-v2-field="executive_intent" rows="6" ${locked ? 'disabled' : ''}>${guidedEsc(proposal.executive_intent)}</textarea></label><label class="form-group" style="display:block"><span>Sectors <em style="font-style:normal;font-weight:400">comma separated</em></span><input class="fi" data-v2-field="sectors" value="${guidedEsc((proposal.sectors || []).join(', '))}" ${locked ? 'disabled' : ''}></label><div class="proposal-v2-call-row"><div><strong>Grant call document</strong><small>${guidedEsc(proposal.reference_filename || 'No call document attached yet')}</small></div>${locked ? '' : '<input type="file" id="proposal-v2-reference" accept=".docx,.txt,.md">'}${proposal.reference_text ? '<button class="btn btn-secondary btn-sm" data-v2-action="call-brief">Open call brief</button>' : ''}</div>${actionBar(1,locked)}</div>`;
  };
  const technicalRows = proposal => Array.isArray(proposal?.technical_data?.logframe) ? proposal.technical_data.logframe : [];
  const rowLabel = row => `${String(row.level || 'row').replace(/^./, c => c.toUpperCase())} ${String(row.id || '').replace(/^[a-z]+-/, '')}`;
  const renderTechnical = (proposal, locked) => {
    const d = proposal.technical_data || {};
    const rows = technicalRows(proposal);
    const levels = [['impact', 'Impact', null], ['outcome', 'Outcome', 'impact'], ['output', 'Output', 'outcome'], ['activity', 'Activity', 'output']];
    const groups = levels.map(([level, label]) => {
      const items = rows.filter(row => row.level === level);
      if (!items.length) return `<section class="logframe-tier empty"><header><span class="logframe-tier-index">${label[0]}</span><div><strong>${label}s</strong><small>No ${label.toLowerCase()} added yet</small></div>${locked ? '' : `<button class="btn btn-secondary btn-sm" data-logframe-action="add" data-logframe-level="${level}">+ Add ${label}</button>`}</header></section>`;
      return `<section class="logframe-tier"><header><span class="logframe-tier-index">${label[0]}</span><div><strong>${label}s</strong><small>${items.length} in the result chain</small></div>${locked ? '' : `<button class="btn btn-secondary btn-sm" data-logframe-action="add" data-logframe-level="${level}">+ Add ${label}</button>`}</header><div class="logframe-tier-list">${items.map(row => { const parents = rows.filter(parent => parent.level === (levels.find(x => x[0] === level)?.[2]) && parent.id); const parentSelect = level === 'impact' ? '<span class="logframe-parent-root">Top level</span>' : `<select class="fi logframe-parent-select" data-logframe-field="parent_id" data-logframe-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}><option value="">Select parent</option>${parents.map(parent => `<option value="${guidedEsc(parent.id)}" ${parent.id === row.parent_id ? 'selected' : ''}>${guidedEsc(rowLabel(parent))}</option>`).join('')}</select>`; return `<article class="logframe-node logframe-node-${level}"><div class="logframe-node-head"><span class="logframe-node-id">${guidedEsc(rowLabel(row))}</span>${parentSelect}${locked ? '' : `<button class="guided-icon-btn danger" title="Remove ${label}" data-logframe-action="remove" data-logframe-id="${guidedEsc(row.id)}">×</button>`}</div><div class="logframe-node-grid"><label><span>Intervention logic</span><textarea class="fi" data-logframe-field="intervention_logic" data-logframe-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''} rows="2">${guidedEsc(row.intervention_logic || '')}</textarea></label><label><span>Means of verification</span><textarea class="fi" data-logframe-field="means_of_verification" data-logframe-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''} rows="2">${guidedEsc(row.means_of_verification || '')}</textarea></label><label><span>Assumptions</span><textarea class="fi" data-logframe-field="assumptions" data-logframe-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''} rows="2">${guidedEsc(row.assumptions || '')}</textarea></label><label><span>SMART indicator</span><input class="fi" data-logframe-field="indicator_title" data-logframe-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''} value="${guidedEsc(row.indicators?.[0]?.indicator_title || '')}" placeholder="Required for outcomes and outputs"></label></div></article>`; }).join('')}</div></section>`;
    }).join('');
    return `<div class="wizard-section-inner"><div class="wizard-section-header-row"><div><h3>3. Technical Design</h3><p class="text-muted" style="margin-top:4px;font-size:13px">Build the result chain visually. Each outcome links to an impact, each output to an outcome, and each activity to an output.</p></div><span class="wizard-status-badge wizard-status-${locked ? 'complete' : proposal.step3_analysis ? 'reviewing' : 'draft'}">${locked ? 'locked' : proposal.step3_analysis ? 'analyzed' : 'draft'}</span></div><label class="form-group" style="display:block"><span>Theory of Change narrative</span><textarea class="fi" data-technical-field="toc_narrative" rows="4" ${locked ? 'disabled' : ''}>${guidedEsc(d.toc_narrative || '')}</textarea></label><div class="logframe-builder-head"><div><span class="proposal-v2-kicker">4-level logframe matrix</span><strong>Impact → Outcome → Output → Activity</strong></div><span class="logframe-builder-count">${rows.length} rows</span></div><div class="logframe-builder">${groups}</div>${actionBar(3, locked)}</div>`;
  };
  const readTechnical = () => {
    const proposal = guidedProposalState.active;
    const current = JSON.parse(JSON.stringify(proposal?.technical_data || {}));
    current.toc_narrative = content.querySelector('[data-technical-field="toc_narrative"]')?.value || current.toc_narrative || '';
    const rows = technicalRows({technical_data: current});
    content.querySelectorAll('[data-logframe-field]').forEach(el => { const row = rows.find(item => item.id === el.dataset.logframeId); if (!row) return; if (el.dataset.logframeField === 'indicator_title') { const existing = Array.isArray(row.indicators) && row.indicators[0]; row.indicators = [{ ...(existing && typeof existing === 'object' ? existing : {}), indicator_title: el.value }]; } else row[el.dataset.logframeField] = el.value; });
    current.logframe = rows;
    return current;
  };
  const addLogframeRow = level => { const p = guidedProposalState.active; p.technical_data = readTechnical(); const d = p.technical_data; const rows = technicalRows(p); const next = rows.filter(row => row.level === level).length + 1; const parentLevel = {outcome:'impact', output:'outcome', activity:'output'}[level]; const parent = rows.find(row => row.level === parentLevel); rows.push({id:`${level}-${next}`,level,parent_id:parent?.id || '',intervention_logic:'',means_of_verification:'',assumptions:'',indicators:[]}); d.logframe = rows; render(); };
  const removeLogframeRow = id => { const p = guidedProposalState.active; p.technical_data = readTechnical(); const rows = technicalRows(p); const removed = new Set([id]); let changed = true; while (changed) { changed = false; rows.forEach(row => { if (removed.has(row.parent_id) && !removed.has(row.id)) { removed.add(row.id); changed = true; } }); } p.technical_data.logframe = rows.filter(row => !removed.has(row.id)); render(); };
  const render = () => {
    const proposal = guidedProposalState.active;
    renderList(); renderSteps();
    if (!proposal) { title.textContent = 'Select or Create a Proposal'; context.textContent = 'Five-stage donor proposal workflow'; content.innerHTML = '<div class="proposal-welcome-placeholder"><div class="welcome-icon">📋</div><h3>Guided Proposal Workspace</h3><p>Start from the call document, co-write with AI, and lock each validated stage.</p><button class="btn btn-primary" data-v2-action="new">Create Guided Proposal</button></div>'; showReview(null); return; }
    title.textContent = proposal.project_title || 'Untitled proposal';
    context.textContent = `${proposal.country || 'Country pending'} · ${donorFor(proposal.donor).label || 'Donor pending'}`;
    const step = guidedProposalState.step;
    const locked = stepState(proposal,step) === 'locked';
    if (step === 1) content.innerHTML = renderSetup(proposal,locked);
    else if (step === 3) content.innerHTML = renderTechnical(proposal,locked);
    else content.innerHTML = `<div class="wizard-section-inner"><div class="wizard-section-header-row"><h3>${step}. ${PROPOSAL_STEPS[step - 1].label}</h3></div><div class="empty-state" style="padding:52px 20px">This stage is available after the preceding stage is locked.</div></div>`;
    showReview(step === 1 ? proposal.analysis : proposal[`step${step}_analysis`]);
  };
  const refresh = async () => { guidedProposalState.setups = await guidedRequest('/api/proposals/setups'); if (!guidedProposalState.active && guidedProposalState.setups[0]) guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.setups[0].id}`); render(); };
  const create = async () => { guidedProposalState.active = await guidedRequest('/api/proposals/setups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_title:'New guided proposal',donor:'generic',budget_currency:'USD',sectors:[]})}); guidedProposalState.step = 1; await refresh(); render(); };
  panel.addEventListener('click', async event => {
    const target = event.target.closest('[data-v2-action], [data-logframe-action]'); if (!target) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      const action = target.dataset.v2Action;
      if (target.dataset.logframeAction === 'add') { addLogframeRow(target.dataset.logframeLevel); return; }
      if (target.dataset.logframeAction === 'remove') { removeLogframeRow(target.dataset.logframeId); return; }
      if (action === 'new') return create();
      if (action === 'select') { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${target.dataset.id}`); guidedProposalState.step = unlockedStep(guidedProposalState.active); return render(); }
      if (action === 'step') { guidedProposalState.step = Number(target.dataset.step); return render(); }
      const proposal = guidedProposalState.active; if (!proposal) return;
      if (action === 'call-brief') { const result = await guidedRequest(`/api/proposals/setups/${proposal.id}/call-brief`,{method:'POST'}); return showCallBrief(result.brief); }
      const step = Number(target.dataset.step || guidedProposalState.step);
      if (step === 3) {
        const technical = readTechnical();
        proposal.technical_data = technical;
        if (action === 'generate') { const result = await guidedRequest(`/api/proposals/setups/${proposal.id}/generate-step3-draft`,{method:'POST'}); proposal.technical_data = result.draft || technical; return render(); }
        const stepPayload = { ...technical, setup_id: proposal.id };
        if (action === 'analyze') { proposal.step3_analysis = await guidedRequest('/api/proposals/steps/3/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(stepPayload)}); return render(); }
        if (action === 'lock') { guidedProposalState.active = await guidedRequest('/api/proposals/steps/3/lock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(stepPayload)}); guidedProposalState.step = 4; await refresh(); return render(); }
        return;
      }
      if (step !== 1) return;
      const data = readStep1();
      if (action === 'generate') { await guidedRequest(`/api/proposals/setups/${proposal.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); const result = await guidedRequest(`/api/proposals/setups/${proposal.id}/generate-draft`,{method:'POST'}); Object.assign(proposal,result.draft || {}); return render(); }
      await guidedRequest(`/api/proposals/setups/${proposal.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      if (action === 'analyze') { proposal.analysis = await guidedRequest(`/api/proposals/setups/${proposal.id}/analyze`,{method:'POST'}); return render(); }
      if (action === 'lock') { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${proposal.id}/lock`,{method:'POST'}); guidedProposalState.step = 2; await refresh(); return render(); }
    } catch (error) { review.innerHTML = `<div class="proposal-review-message error">${guidedEsc(error.message)}</div>`; }
  });
  panel.addEventListener('change', async event => {
    if (event.target.matches('[data-v2-field="donor"]') && guidedProposalState.active) {
      Object.assign(guidedProposalState.active,readStep1());
      const selected = donorFor(guidedProposalState.active.donor);
      if (!(selected.currency_options || []).includes(guidedProposalState.active.budget_currency)) guidedProposalState.active.budget_currency = selected.currency_options?.[0] || 'USD';
      render();
    }
    if (event.target.id === 'proposal-v2-reference' && guidedProposalState.active && event.target.files[0]) {
      const form = new FormData(); form.append('file',event.target.files[0]);
      try { await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/upload-reference`,{method:'POST',body:form}); guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}`); render(); } catch (error) { review.innerHTML = `<div class="proposal-review-message error">${guidedEsc(error.message)}</div>`; }
    }
  });
  document.getElementById('btn-new-proposal')?.addEventListener('click', event => { event.preventDefault(); event.stopImmediatePropagation(); create(); },true);
  // The active renderer owns this panel. A broad MutationObserver here used
  // to repaint the whole wizard after every input/click, which reset scroll
  // positions and made controls appear unresponsive.
  (async () => { try { const [countryData,donorData] = await Promise.all([guidedRequest('/api/db/countries'),guidedRequest('/api/proposals/donors')]); guidedProposalState.countries = Array.isArray(countryData) ? countryData : []; donors = Array.isArray(donorData) ? donorData : []; await refresh(); } catch (error) { review.innerHTML = `<div class="proposal-review-message error">${guidedEsc(error.message)}</div>`; } })();
}

// Proposal is mounted independently as a safety net. Other dashboard widgets
// may fail during boot (network/API widgets are intentionally optional), but
// that must never prevent the proposal workspace from initializing.
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    try { initGuidedProposalPipelineActive(); }
    catch (error) { console.error('Guided Proposal mount failed', error); }
  }, 50);
});

document.addEventListener('click', event => {
  const button = event.target.closest('[data-guided-logframe-action]');
  if (!button || !guidedProposalState.active) return;
  const proposal = guidedProposalState.active;
  const data = proposal.technical_data || (proposal.technical_data = {});
  const rows = Array.isArray(data.logframe) ? data.logframe : (data.logframe = []);
  if (button.dataset.guidedLogframeAction === 'add') {
    const level = button.dataset.level; const n = rows.filter(row => row.level === level).length + 1;
    const parentLevel = {outcome:'impact', output:'outcome', activity:'output'}[level]; const parent = rows.find(row => row.level === parentLevel);
    rows.push({id:`${level}-${n}`, level, parent_id:parent?.id || '', intervention_logic:'', means_of_verification:'', assumptions:'', indicators:[]});
  } else if (button.dataset.guidedLogframeAction === 'remove') {
    const id = button.dataset.id; const removed = new Set([id]); let changed = true; while (changed) { changed = false; rows.forEach(row => { if (removed.has(row.parent_id) && !removed.has(row.id)) { removed.add(row.id); changed = true; } }); } data.logframe = rows.filter(row => !removed.has(row.id));
  } else return;
  event.preventDefault(); event.stopPropagation(); const host = document.querySelector('.guided-logframe-upgraded'); if (host) host.innerHTML = guidedTechnicalMatrixHtml(proposal, proposal.step3_state === 'locked'); const scheduleHost = document.querySelector('.guided-schedule-upgraded'); if (scheduleHost) scheduleHost.innerHTML = guidedScheduleHtml(proposal, proposal.step3_state === 'locked'); syncTechnicalPayloadFields();
}, true);
document.addEventListener('input', event => {
  const el = event.target.closest('[data-guided-logframe-action]'); if (!el || !guidedProposalState.active) return;
  const row = (guidedProposalState.active.technical_data?.logframe || []).find(item => item.id === el.dataset.id); if (!row) return;
  if (el.dataset.guidedLogframeAction === 'indicator') { row.indicators = [{ ...(row.indicators?.[0] && typeof row.indicators[0] === 'object' ? row.indicators[0] : {}), indicator_title: el.value }]; }
  else if (el.dataset.guidedLogframeAction === 'text') row[el.dataset.field] = el.value;
  syncTechnicalPayloadFields();
}, true);
document.addEventListener('change', event => {
  const checkbox = event.target.closest('[data-guided-schedule-month]'); if (!checkbox || !guidedProposalState.active) return;
  const data = guidedProposalState.active.technical_data || (guidedProposalState.active.technical_data = {}); const schedule = Array.isArray(data.gantt) ? data.gantt : (data.gantt = []); const id = checkbox.dataset.activityId; let item = schedule.find(entry => entry.activity_id === id); if (!item) { item = {activity_id:id, months:[]}; schedule.push(item); } const month = Number(checkbox.dataset.guidedScheduleMonth); const months = new Set(item.months || []); checkbox.checked ? months.add(month) : months.delete(month); item.months = [...months].sort((a,b) => a - b); syncTechnicalPayloadFields();
}, true);
document.addEventListener('change', event => {
  const el = event.target.closest('[data-guided-logframe-action="parent"]'); if (!el || !guidedProposalState.active) return;
  const row = (guidedProposalState.active.technical_data?.logframe || []).find(item => item.id === el.dataset.id); if (row) row.parent_id = el.value; syncTechnicalPayloadFields();
}, true);
function upgradeVisibleTechnicalMatrix() {
  const content = document.getElementById('wizard-section-content');
  if (!content || guidedProposalState.step !== 3) return;
  const locked = guidedProposalState.active?.step3_state === 'locked';
  const area = content.querySelector('[data-guided-field="logframe"]:not([hidden])');
  if (area && area.dataset.matrixUpgraded !== 'true') { const wrapper = area.closest('.guided-field, .form-group, label') || area.parentElement; if (wrapper) { const host = document.createElement('div'); host.className = 'guided-logframe-upgraded'; host.innerHTML = guidedTechnicalMatrixHtml(guidedProposalState.active, locked); area.dataset.matrixUpgraded = 'true'; wrapper.replaceWith(host); } }
  const scheduleArea = content.querySelector('[data-guided-field="gantt"]:not([hidden])');
  if (scheduleArea && scheduleArea.dataset.scheduleUpgraded !== 'true') { const wrapper = scheduleArea.closest('.guided-field, .form-group, label') || scheduleArea.parentElement; if (wrapper) { const host = document.createElement('div'); host.className = 'guided-schedule-upgraded'; host.innerHTML = guidedScheduleHtml(guidedProposalState.active, locked); scheduleArea.dataset.scheduleUpgraded = 'true'; wrapper.replaceWith(host); } }
  syncTechnicalPayloadFields();
}
function syncTechnicalPayloadFields() {
  const content = document.getElementById('wizard-section-content'); const data = guidedProposalState.active?.technical_data || {}; if (!content || guidedProposalState.step !== 3) return;
  [['logframe', data.logframe || []], ['gantt', data.gantt || []]].forEach(([key, value]) => { let field = content.querySelector(`[data-guided-field="${key}"]`); if (!field) { field = document.createElement('textarea'); field.dataset.guidedField = key; field.hidden = true; content.appendChild(field); } field.value = JSON.stringify(value); });
}
setInterval(upgradeVisibleTechnicalMatrix, 250);

/* ── Walkthrough Scroll Reveal ── */
document.addEventListener('DOMContentLoaded', function initWalkthroughObserver() {
  const rows = document.querySelectorAll('.wt-feature-row');
  if (!rows.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('wt-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15 });

  rows.forEach(row => observer.observe(row));

  /* Video error → show placeholder fallback */
  document.querySelectorAll('.wt-video').forEach(video => {
    const showPlaceholder = () => {
      video.style.display = 'none';
      video.setAttribute('error', '');
      const placeholder = video.nextElementSibling;
      if (placeholder && placeholder.classList.contains('wt-video-placeholder')) {
        placeholder.style.display = 'flex';
      }
    };
    video.addEventListener('error', showPlaceholder);
    if (video.readyState === 0 && video.networkState === 3) showPlaceholder();
  });

  /* CTA "go-chat" button → switch to agent tab */
  document.querySelectorAll('[data-action="go-chat"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabBtn = document.querySelector('[data-tab="agent"]');
      if (tabBtn) tabBtn.click();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });
});
