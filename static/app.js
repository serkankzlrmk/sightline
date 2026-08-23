// ═══════════════════════════════════════════════════════════════════════════
// app.js — Merged frontend for Sightline
//
// Tab 1: Database  → /api/db/*
// Tab 2: Agent     → /api/agent/chat
// Tab 3: SITREP    → /api/sitrep/*
// ═══════════════════════════════════════════════════════════════════════════

// ── Constants ──────────────────────────────────────────────────────────────
const ADMIN_EMAIL = document.querySelector('meta[name="contact-email"]')?.content || 'support@sightline.ai';
const TAB_NAMES = ['home', 'crisis-map', 'agent', 'sitrep', 'bulletin', 'db', 'admin'];
const DEFAULT_MODEL = 'flash';
const CHAT_MODELS = {
  flash: { name: 'Flash', desc: 'Fast responses', premium: false },
  deep_think: { name: 'Deep Think', desc: 'Deep analysis — Premium', premium: true },
  vision: { name: 'Vision', desc: 'Image + document analysis — Premium', premium: true, vision: true },
};
// Extra OpenRouter models (premium/admin only) — mirrors config.CUSTOM_MODELS
const CUSTOM_MODELS = {
  'deepseek-v3': { name: 'DeepSeek V3', desc: 'Strong generalist · cheap', premium: true },
  'deepseek-r1': { name: 'DeepSeek R1', desc: 'Reasoning', premium: true },
  'glm-4.6': { name: 'GLM-4.6', desc: 'Strong generalist', premium: true },
  'gemini-flash': { name: 'Gemini 2.5 Flash', desc: 'Fast + multimodal', premium: true },
  'gpt-4o-mini': { name: 'GPT-4o mini', desc: 'Cheap generalist', premium: true },
  'claude-sonnet-4': { name: 'Claude Sonnet 4', desc: 'High quality · pricier', premium: true },
  'gpt-4o': { name: 'GPT-4o', desc: 'High quality', premium: true },
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
  mode: 'analyst',         // analyst | me_reviewer
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

// NOTE: api(), toast(), esc(), escHtml(), sanitizeHtml() live in shared.js
// (loaded before this file).

// ═══════════════════════════════════════════════════════════════════════════
// SHARED HELPERS (toast/esc/sanitizeHtml moved to shared.js — see above)
// ═══════════════════════════════════════════════════════════════════════════

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
  // Freemium preview: gated tabs require auth — Chat and Database stay
  // locked; Bulletin, SITREP, Map, Home, Countries are open to anonymous
  // visitors (public read APIs serve them).
  const tok = window.getIdToken ? window.getIdToken() : '';
  const isAuthed = !!tok;
  const GATED_TABS = ['agent', 'db', 'admin'];
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

  // Freemium: anonymous visitors can BROWSE SITREP reports but the
  // generation form (country/event/themes + Generate button) is premium —
  // hide the control desk so the "create" affordance is not shown at all.
  const sitrepFormBar = document.getElementById('sitrep-form-bar');
  if (sitrepFormBar) {
    sitrepFormBar.style.display = (!isAuthed && name === 'sitrep') ? 'none' : '';
  }
  const sitrepRangeHint = document.getElementById('date-range-hint');
  if (sitrepRangeHint && !isAuthed && name === 'sitrep') sitrepRangeHint.style.display = 'none';

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

  if (name === 'home') loadCommandCenter();
  if (name === 'crisis-map') {
    // Build and measure Leaflet only after its panel is visible.
    initWorldMap();
    loadDashboard();
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
// DOM INIT
// ═════════════════════════════════════════════════════════════════════════

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

// ── Exports ─────────────────────────────────────────────────────────────────
// api/escHtml/toast/sanitizeHtml are in shared.js (loaded first).
// switchTab stays exported from here — it depends on app.js currentTab state.
window.switchTab = switchTab;

