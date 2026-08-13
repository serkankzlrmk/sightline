// ═══════════════════════════════════════════════════════════════════════════
// proposal.js — Proposal Wizard & Guided Proposal Pipeline
// Extracted from app.js for modular development.
//
// Dependencies (provided by app.js via window):
//   window.api, window.escHtml, window.toast, window.sanitizeHtml, window.switchTab
//   window.__userRole, window.__authReady
//   window.chatState, window.proposalState
//   window.getIdToken, window.auth
// ═══════════════════════════════════════════════════════════════════════════

// ── Resolve shared dependencies from app.js ────────────────────────────────
const api = window.api;
const escHtml = window.escHtml;
const toast = window.toast;
const sanitizeHtml = window.sanitizeHtml;
const switchTab = window.switchTab;

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
    parsed = escHtml(markdown).replace(/\n/g, '<br>');
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
function guidedIndicatorFields(row, locked) {
  const indicator = row.indicators?.[0] && typeof row.indicators[0] === 'object' ? row.indicators[0] : {};
  const fields = [['indicator_title','Indicator title'],['baseline_value','Baseline'],['target_value','Target'],['unit_of_measure','Unit'],['disaggregation','Disaggregation'],['data_source_and_frequency','Data source / frequency']];
  return `<details class="guided-indicator-details" ${row.level === 'outcome' || row.level === 'output' ? 'open' : ''}><summary>SMART indicator ${row.level === 'outcome' || row.level === 'output' ? '<em>required</em>' : ''}</summary><div class="guided-indicator-grid">${fields.map(([key,label]) => `<label>${label}<input class="guided-input" data-guided-logframe-action="indicator" data-indicator-field="${key}" data-id="${guidedEsc(row.id)}" value="${guidedEsc(indicator[key] || '')}" ${locked ? 'disabled' : ''}></label>`).join('')}</div></details>`;
}
function guidedTechnicalMatrixHtml(active, locked) {
  const data = active?.technical_data || {};
  const rows = Array.isArray(data.logframe) ? data.logframe : [];
  const levels = [['impact','Impact',''],['outcome','Outcome','impact'],['output','Output','outcome'],['activity','Activity','output']];
  return `<div class="guided-logframe-builder"><div class="guided-logframe-builder-head"><strong>Impact → Outcome → Output → Activity</strong><span>${rows.length} rows</span></div>${levels.map(([level,label,parentLevel]) => { const items = rows.filter(row => row.level === level); const add = locked ? '' : `<button class="btn btn-secondary btn-sm" data-guided-logframe-action="add" data-level="${level}">+ Add ${label}</button>`; const cards = items.map(row => { const parents = rows.filter(parent => parent.level === parentLevel); const parent = level === 'impact' ? '<span class="guided-logframe-root">Top level</span>' : `<select class="guided-input guided-logframe-parent" data-guided-logframe-action="parent" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}><option value="">Select parent</option>${parents.map(p => `<option value="${guidedEsc(p.id)}" ${p.id === row.parent_id ? 'selected' : ''}>${guidedEsc(p.id)}</option>`).join('')}</select>`; return `<article class="guided-logframe-card guided-logframe-${level}"><div class="guided-logframe-card-head"><strong>${guidedEsc(row.id || level)}</strong>${parent}${locked ? '' : `<button class="guided-icon-btn danger" data-guided-logframe-action="remove" data-id="${guidedEsc(row.id)}">×</button>`}</div><div class="guided-logframe-fields"><label>Intervention logic<textarea class="guided-input" data-guided-logframe-action="text" data-field="intervention_logic" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.intervention_logic || '')}</textarea></label><label>Means of verification<textarea class="guided-input" data-guided-logframe-action="text" data-field="means_of_verification" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.means_of_verification || '')}</textarea></label><label>Assumptions<textarea class="guided-input" data-guided-logframe-action="text" data-field="assumptions" data-id="${guidedEsc(row.id)}" ${locked ? 'disabled' : ''}>${guidedEsc(row.assumptions || '')}</textarea></label></div>${guidedIndicatorFields(row, locked)}</article>`; }).join(''); return `<section class="guided-logframe-tier"><header><div><strong>${label}s</strong><small>${items.length} row${items.length === 1 ? '' : 's'}</small></div>${add}</header>${cards || `<div class="guided-logframe-empty">No ${label.toLowerCase()} added yet.</div>`}</section>`; }).join('')}</div>`;
}
function guidedScheduleHtml(active, locked) {
  const data = active?.technical_data || {};
  const activities = (Array.isArray(data.logframe) ? data.logframe : []).filter(row => row.level === 'activity');
  const schedule = Array.isArray(data.gantt) ? data.gantt : [];
  const months = Array.from({length: 12}, (_, i) => i + 1);
  return `<div class="guided-schedule-builder"><div class="guided-schedule-head"><div><span class="proposal-v2-kicker">Activity schedule</span><strong>Project timeline · 12 months</strong></div><span>${activities.length} activities</span></div>${activities.length ? `<div class="guided-schedule-table-wrap"><table class="guided-schedule-table"><thead><tr><th>Activity</th>${months.map(m => `<th>M${m}</th>`).join('')}</tr></thead><tbody>${activities.map(activity => { const item = schedule.find(entry => entry.activity_id === activity.id) || {}; const activeMonths = new Set(item.months || []); return `<tr><th>${guidedEsc(activity.id)}</th>${months.map(m => `<td><input type="checkbox" data-guided-schedule-month="${m}" data-activity-id="${guidedEsc(activity.id)}" ${activeMonths.has(m) ? 'checked' : ''} ${locked ? 'disabled' : ''} aria-label="${guidedEsc(activity.id)} month ${m}"></td>`).join('')}</tr>`; }).join('')}</tbody></table></div>` : '<div class="guided-schedule-empty">Add an Activity above to place it on the schedule.</div>'}</div>`;
}
function guidedFinancialHtml(active, locked) {
  const data = active?.financial_data || {};
  const items = Array.isArray(data.budget_items) ? data.budget_items : [];
  const risks = Array.isArray(data.risks) ? data.risks : [];
  const input = (kind, index, field, value, type = 'text') => `<input class="guided-input" type="${type}" data-guided-financial-kind="${kind}" data-index="${index}" data-field="${field}" value="${guidedEsc(value ?? '')}" ${locked ? 'disabled' : ''}>`;
  return `<div class="guided-financial-builder"><div class="guided-financial-head"><div><span class="proposal-v2-kicker">Commitments & financials</span><strong>Budget, risks and compliance gates</strong></div>${locked ? '<span class="wizard-status-badge wizard-status-complete">locked</span>' : '<button class="btn btn-secondary btn-sm" data-guided-financial-action="add-budget">+ Budget line</button>'}</div><section class="guided-financial-section"><header><strong>Itemized budget</strong><span>${items.length} lines</span></header><div class="guided-financial-table-wrap"><table class="guided-financial-table"><thead><tr><th>Code</th><th>Description</th><th>Unit</th><th>Qty</th><th>Unit cost</th><th>Duration</th><th>Total</th><th></th></tr></thead><tbody>${items.map((item,i) => { const total = Number(item.quantity||0)*Number(item.unit_cost||0)*Number(item.duration_frequency||0); return `<tr><td>${input('budget',i,'item_code',item.item_code)}</td><td>${input('budget',i,'description',item.description)}</td><td>${input('budget',i,'unit_type',item.unit_type)}</td><td>${input('budget',i,'quantity',item.quantity,'number')}</td><td>${input('budget',i,'unit_cost',item.unit_cost,'number')}</td><td>${input('budget',i,'duration_frequency',item.duration_frequency,'number')}</td><td class="guided-financial-total">${total.toFixed(2)}</td><td>${locked ? '' : `<button class="guided-icon-btn danger" data-guided-financial-action="remove-budget" data-index="${i}">×</button>`}</td></tr>`; }).join('') || '<tr><td colspan="8" class="guided-financial-empty">AI draft or add a budget line to begin.</td></tr>'}</tbody></table></div></section><section class="guided-financial-section"><header><strong>Risk matrix</strong><span>${risks.length} risks</span></header>${risks.map((risk,i) => `<article class="guided-risk-row"><div><label>Category${input('risk',i,'category',risk.category)}</label><label>Description${input('risk',i,'risk_description',risk.risk_description)}</label></div><div><label>Likelihood${input('risk',i,'likelihood',risk.likelihood,'number')}</label><label>Impact${input('risk',i,'impact',risk.impact,'number')}</label></div><label>Mitigation${input('risk',i,'mitigation_strategy',risk.mitigation_strategy)}</label>${locked ? '' : `<button class="guided-icon-btn danger" data-guided-financial-action="remove-risk" data-index="${i}">×</button>`}</article>`).join('') || '<div class="guided-financial-empty">No risks added yet.</div>'}${locked ? '' : '<button class="btn btn-secondary btn-sm" data-guided-financial-action="add-risk">+ Risk</button>'}</section><section class="guided-financial-section guided-compliance-section"><header><strong>Compliance commitments</strong></header><label class="guided-check"><input type="checkbox" data-guided-financial-kind="root" data-field="psea_signoff" ${data.psea_signoff ? 'checked' : ''} ${locked ? 'disabled' : ''}> PSEA / six IASC core principles sign-off</label><label>Sphere standards narrative<textarea class="guided-input" data-guided-financial-kind="root" data-field="sphere_standards_narrative" ${locked ? 'disabled' : ''}>${guidedEsc(data.sphere_standards_narrative || '')}</textarea></label></section></div>`;
}
function guidedDocumentViewHtml(active, step) {
  if (!document.getElementById('proposal-doc-enhanced-style')) { const style = document.createElement('style'); style.id = 'proposal-doc-enhanced-style'; style.textContent = '.proposal-doc-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.proposal-doc-summary-grid>div{padding:14px;border:1px solid var(--border-light);border-radius:10px;background:var(--bg-subtle)}.proposal-doc-summary-grid span{display:block;font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em}.proposal-doc-summary-grid strong{display:block;margin-top:5px;font-size:22px}.proposal-doc-tag{display:inline-block;margin-right:6px;padding:3px 6px;border-radius:999px;background:var(--bg-subtle);color:var(--text-muted);font-size:9px;text-transform:uppercase;letter-spacing:.05em}@media(max-width:700px){.proposal-doc-summary-grid{grid-template-columns:1fr}}'; document.head.appendChild(style); }
  const p = active || {}; const d = step === 2 ? (p.context_data || {}) : step === 3 ? (p.technical_data || {}) : step === 4 ? (p.financial_data || {}) : {};
  const block = (label, value) => value ? `<section class="proposal-document-section"><h4>${label}</h4><p>${guidedEsc(value)}</p></section>` : '';
  const budget = Array.isArray(d.budget_items) ? d.budget_items : []; const risks = Array.isArray(d.risks) ? d.risks : [];
  const budgetTotal = budget.reduce((sum, item) => sum + Number(item.quantity || 0) * Number(item.unit_cost || 0) * Number(item.duration_frequency || 0), 0);
  const rows = Array.isArray(d.logframe) ? d.logframe.map(row => `<tr><td><span class="proposal-doc-tag">${guidedEsc(row.level || '')}</span><strong>${guidedEsc(row.id || '')}</strong></td><td>${guidedEsc(row.intervention_logic || '')}</td><td>${guidedEsc(row.parent_id || '—')}</td><td>${guidedEsc((row.indicators || []).map(i => typeof i === 'string' ? i : i.indicator_title || '').filter(Boolean).join('; ') || '—')}</td></tr>`).join('') : '';
  return `<div class="proposal-document-view"><div class="proposal-document-cover"><span class="proposal-v2-kicker">Proposal document · Step ${step}</span><h3>${guidedEsc(p.project_title || 'Untitled proposal')}</h3><p>${guidedEsc([p.country,p.region].filter(Boolean).join(' · '))}</p><p>${guidedEsc(p.donor || '')}</p></div>${step === 1 ? `${block('Executive intent',p.executive_intent)}${block('Sectors',(p.sectors || []).join(', '))}` : ''}${step === 2 ? `${block('Humanitarian context',d.humanitarian_context)}${block('Needs assessment',d.needs_assessment)}${block('Strategic justification',d.strategic_justification)}` : ''}${step === 3 ? `${block('Theory of Change',d.toc_narrative)}${rows ? `<section class="proposal-document-section"><h4>Logical framework</h4><div class="proposal-document-table-wrap"><table class="proposal-document-table"><thead><tr><th>Result</th><th>Logic</th><th>Parent</th><th>Indicator</th></tr></thead><tbody>${rows}</tbody></table></div></section>` : ''}` : ''}${step === 4 ? `<section class="proposal-document-section"><div class="proposal-doc-summary-grid"><div><span>Total budget</span><strong>${budgetTotal.toFixed(2)}</strong></div><div><span>Budget lines</span><strong>${budget.length}</strong></div><div><span>Risks</span><strong>${risks.length}</strong></div></div></section>${budget.length ? `<section class="proposal-document-section"><h4>Itemized budget</h4><div class="proposal-document-table-wrap"><table class="proposal-document-table"><thead><tr><th>Code</th><th>Description</th><th>Unit</th><th>Qty</th><th>Unit cost</th><th>Duration</th><th>Total</th></tr></thead><tbody>${budget.map(item => { const total = Number(item.quantity||0)*Number(item.unit_cost||0)*Number(item.duration_frequency||0); return `<tr><td>${guidedEsc(item.item_code || '—')}</td><td>${guidedEsc(item.description || '')}</td><td>${guidedEsc(item.unit_type || '')}</td><td>${Number(item.quantity || 0)}</td><td>${Number(item.unit_cost || 0).toFixed(2)}</td><td>${Number(item.duration_frequency || 0)}</td><td><strong>${total.toFixed(2)}</strong></td></tr>`; }).join('')}</tbody></table></div></section>` : ''}${risks.length ? `<section class="proposal-document-section"><h4>Risk matrix</h4><div class="proposal-document-table-wrap"><table class="proposal-document-table"><thead><tr><th>Category</th><th>Risk</th><th>Likelihood</th><th>Impact</th><th>Mitigation</th></tr></thead><tbody>${risks.map(risk => `<tr><td>${guidedEsc(risk.category || '')}</td><td>${guidedEsc(risk.risk_description || '')}</td><td>${guidedEsc(risk.likelihood || '')}</td><td>${guidedEsc(risk.impact || '')}</td><td>${guidedEsc(risk.mitigation_strategy || '')}</td></tr>`).join('')}</tbody></table></div></section>` : ''}${block('Sphere standards',d.sphere_standards_narrative)}` : ''}</div>`;
}
function guidedFinalResultHtml(result) {
  if (!document.getElementById('guided-final-review-style')) { const style = document.createElement('style'); style.id = 'guided-final-review-style'; style.textContent = '.guided-final-score{display:flex;align-items:baseline;gap:8px;padding:16px;border:1px solid var(--border-light);border-radius:12px;background:var(--bg-subtle)}.guided-final-score strong{font-size:34px}.guided-final-score span{font-size:11px;color:var(--text-muted)}.guided-final-section{margin-top:14px;padding-top:12px;border-top:1px solid var(--border-light)}.guided-final-section h4{margin:0 0 7px;text-transform:capitalize}.guided-final-section ul{margin:6px 0;padding-left:18px}.guided-final-kv{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.guided-final-kv div{padding:9px;border-radius:8px;background:var(--bg-subtle)}.guided-final-kv span,.guided-final-kv strong{display:block}.guided-final-kv span{font-size:10px;color:var(--text-muted);text-transform:capitalize}.guided-final-kv strong{margin-top:3px;font-size:12px}@media(max-width:700px){.guided-final-kv{grid-template-columns:1fr}}'; document.head.appendChild(style); }
  if (!result || typeof result !== 'object') return '<p class="guided-muted">No final review result yet.</p>';
  const score = result.overall_score ?? result.donor_compliance_score ?? result.technical_score;
  const entries = Object.entries(result).filter(([key]) => !['overall_score','donor_compliance_score','technical_score'].includes(key));
  const renderValue = value => {
    // Summary responses may contain serialized step payloads. Parse them so
    // the final review never exposes raw JSON strings or [object Object].
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if ((trimmed.startsWith('{') || trimmed.startsWith('['))) {
        try { return renderValue(JSON.parse(trimmed)); } catch (_) { /* keep as text */ }
      }
    }
    if (Array.isArray(value)) return `<ul>${value.map(item => `<li>${typeof item === 'object' && item !== null ? renderValue(item) : guidedEsc(String(item ?? '—'))}</li>`).join('')}</ul>`;
    if (typeof value === 'object' && value !== null) return `<div class="guided-final-kv">${Object.entries(value).map(([k,v]) => { const display = typeof v === 'number' && /locked|at|time|date/i.test(k) ? new Date(v * 1000).toLocaleString() : typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—'); return `<div><span>${guidedEsc(k.replaceAll('_',' '))}</span><strong>${guidedEsc(display)}</strong></div>`; }).join('')}</div>`;
    return `<p>${guidedEsc(String(value ?? '—'))}</p>`;
  };
  return `${score != null ? `<div class="guided-final-score"><strong>${guidedEsc(String(score))}</strong><span>/ 100 final review score</span></div>` : ''}${entries.map(([key,value]) => `<section class="guided-final-section"><h4>${guidedEsc(key.replaceAll('_',' '))}</h4>${renderValue(value)}</section>`).join('')}`;
}
function guidedRender() {
  const active = guidedProposalState.active; const content = document.getElementById('guided-content'); if (!content) return; guidedRenderList(); guidedRenderStepper(); if (!active) { content.innerHTML = '<div class="guided-empty large">Select a proposal or create a new one.</div>'; return; }
  document.getElementById('guided-title').textContent = active.project_title || 'Untitled proposal'; document.getElementById('guided-subtitle').textContent = `${active.country || 'Country pending'} · ${active.donor || 'Donor pending'} · ${active.reference_filename || 'No call document attached'}`; document.getElementById('guided-delete').hidden = !active.can_delete; document.getElementById('guided-call-brief').hidden = !active.reference_text;
  const step = guidedProposalState.step; const locked = step === 1 ? active.state === 'locked' : active[`step${step}_state`] === 'locked'; const analysis = step === 1 ? active.analysis : active[`step${step}_analysis`]; let html = `<div class="guided-step-heading"><div><span class="eyebrow">Step ${step} of 5</span><h2>${['Project setup','Context & needs','Technical matrix','Budget & risks','Final review'][step - 1]}</h2></div>${locked ? '<span class="guided-lock-pill">Locked</span>' : ''}</div>`;
  if (step === 1) { html += `<div class="guided-form-grid">${guidedField('Project title','project_title',active.project_title,'text','required minlength="10" maxlength="150" placeholder="A clear, geographically specific title"')}${guidedField('Target country','country',active.country,'select','required')}${guidedField('Region / location','region',active.region)}${guidedField('Primary donor','donor',active.donor,'select','required')}${guidedField('Estimated budget','budget_amount',active.budget_amount,'number','min="0.01" step="0.01" required')}${guidedField('Currency','budget_currency',active.budget_currency,'select')}</div>${guidedField('Executive intent (100–500 characters)','executive_intent',active.executive_intent,'textarea','minlength="100" maxlength="500" rows="6" placeholder="Describe the humanitarian problem, target group and intended change."')}<label class="guided-field full"><span>Sectors</span><input class="guided-input" data-guided-field="sectors" value="${guidedEsc((active.sectors || []).join(', '))}" placeholder="Protection, Health, WASH"></label><div class="guided-upload"><span>Grant call</span><input id="guided-reference" type="file" accept=".docx,.txt,.md"><small>${guidedEsc(active.reference_filename || 'Attach a call document to ground the agent in the actual requirements.')}</small></div>${guidedActionBar(1, locked)}`; }
  else if (step === 2) { const d = active.context_data || {}; html += `<p class="guided-help">The agent can draft this stage from your locked setup and attached call. Edit the text, then analyze and lock it.</p>${guidedField('Humanitarian context','humanitarian_context',d.humanitarian_context || '','textarea','rows="8"')}${guidedField('Needs assessment','needs_assessment',d.needs_assessment || '','textarea','rows="8"')}${guidedField('Strategic justification','strategic_justification',d.strategic_justification || '','textarea','rows="8"')}<label class="guided-field full"><span>Beneficiary matrix (JSON)</span><textarea class="guided-input" data-guided-field="beneficiaries" rows="7">${guidedEsc(JSON.stringify(d.beneficiaries || {host_communities:{},idps:{},refugees_returnees:{}}, null, 2))}</textarea></label>${guidedActionBar(2, locked)}`; }
  else if (step === 3) { const d = active.technical_data || {}; html += `<p class="guided-help">Build the result chain visually and link each level to its parent.</p>${guidedField('Theory of change narrative','toc_narrative',d.toc_narrative || '','textarea','rows="5"')}${guidedTechnicalMatrixHtml(active, locked)}<label class="guided-field full"><span>Activity schedule (JSON)</span><textarea class="guided-input" data-guided-field="gantt" rows="5">${guidedEsc(JSON.stringify(d.gantt || [], null, 2))}</textarea></label>${guidedActionBar(3, locked)}`; }
  else if (step === 4) { html += `${guidedFinancialHtml(active, locked)}${guidedActionBar(4, locked)}`; }
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
  const actionBar = (step, locked) => {
    // Step 5 is a read-only audit stage. Only Steps 1–4 have lock endpoints.
    if (step === 5) return '';
    return locked ? `<div class="wizard-section-actions"><span class="wizard-status-badge wizard-status-complete">Locked — immutable</span></div>` : `<div class="wizard-section-actions" style="display:flex;gap:8px;flex-wrap:wrap;padding:12px 0;border-top:1px solid var(--border-light)">${step === 3 ? '<button class="btn btn-secondary btn-sm" data-guided-action="fill-indicators" data-step="3">AI complete SMART indicators</button>' : ''}<button class="btn btn-secondary btn-sm" data-guided-action="generate" data-step="${step}">Generate draft</button><button class="btn btn-primary btn-sm" data-guided-action="analyze" data-step="${step}">Analyze with AI</button><button class="btn btn-green btn-sm" data-guided-action="lock" data-step="${step}">Confirm &amp; Lock Step ${step}</button></div>`;
  };
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
  panel.addEventListener('click', e => { const target = e.target.closest('[data-v2-action="view-edit"], [data-v2-action="view-document"]'); if (!target) return; e.preventDefault(); e.stopImmediatePropagation(); guidedProposalState.viewMode = target.dataset.v2Action === 'view-document' ? 'document' : 'edit'; if (guidedProposalState.viewMode === 'document') { content.innerHTML = `<div class="proposal-view-toolbar"><span>Workspace view</span><div><button class="btn btn-secondary btn-sm" data-v2-action="view-edit">Edit</button><button class="btn btn-secondary btn-sm" data-v2-action="view-document">Document view</button></div></div>${guidedDocumentViewHtml(guidedProposalState.active, guidedProposalState.step)}`; formatBeneficiaryDocument(); } else render(); }, true);
  panel.addEventListener('click', e => { const target = e.target.closest('[data-guided-action="step"]'); if (!target || !guidedProposalState.active) return; const n = Number(target.dataset.step); if (n > maxReachableStep()) return; e.preventDefault(); e.stopImmediatePropagation(); guidedProposalState.step = n; render(); }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action="generate"]'); const step = Number(target?.dataset.step || guidedProposalState.step); if (!target || ![3,4].includes(step) || !guidedProposalState.active) return; e.preventDefault(); e.stopImmediatePropagation(); try { notifyProposal(step === 4 ? 'Generating commitments and financials draft…' : 'Generating Technical Design draft…'); const endpoint = step === 4 ? 'generate-step4-draft' : 'generate-step3-draft'; const result = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/${endpoint}`,{method:'POST'}); if (step === 4) guidedProposalState.active.financial_data = result.draft || {}; else guidedProposalState.active.technical_data = result.draft || {}; render(); notifyProposal(step === 4 ? 'Financial draft is ready. Review and edit it before analysis.' : 'Technical Design draft is ready. Review and edit it before analysis.'); } catch (err) { notifyProposal(err.message || 'Draft could not be generated.', 'error'); } }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action="fill-indicators"]'); if (!target || Number(target.dataset.step || guidedProposalState.step) !== 3 || !guidedProposalState.active) return; e.preventDefault(); e.stopImmediatePropagation(); try { notifyProposal('AI is completing SMART indicators…'); const result = await guidedRequest(`/api/proposals/setups/${guidedProposalState.active.id}/generate-step3-draft`,{method:'POST'}); const draft = result.draft || {}; guidedProposalState.active.technical_data = draft; render(); notifyProposal('SMART indicator draft is ready. Review it, then analyze and lock.'); } catch (err) { notifyProposal(err.message || 'SMART indicator draft could not be generated.', 'error'); } }, true);
  panel.addEventListener('click', async e => { const target = e.target.closest('[data-guided-action]'); if (!target) return; e.preventDefault(); e.stopImmediatePropagation(); try { const a = target.dataset.guidedAction; if (a === 'new') return create(); if (a === 'select') { guidedProposalState.active = await guidedRequest(`/api/proposals/setups/${target.dataset.id}`); guidedProposalState.step = guidedProposalState.active.state === 'locked' ? 2 : 1; return render(); } if (a === 'step') { const n = Number(target.dataset.step); if (n <= guidedProposalState.step) { guidedProposalState.step = n; render(); } return; } const p = guidedProposalState.active; if (!p) return; const step = Number(target.dataset.step || guidedProposalState.step); const base = step === 1 ? `/api/proposals/setups/${p.id}` : `/api/proposals/steps/${step}`; const data = payload(step); if (a === 'generate') { const result = await guidedRequest(step === 1 ? `/api/proposals/setups/${p.id}/generate-draft` : `/api/proposals/setups/${p.id}/generate-step2-draft`,{method:'POST'}); if (step === 1 && result.draft) Object.assign(p,result.draft); if (step === 2 && result.draft) p.context_data = result.draft; return render(); } if (step === 1 && (a === 'analyze' || a === 'lock')) { await guidedRequest(`/api/proposals/setups/${p.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); } if (a === 'analyze') { const result = await guidedRequest(`${base}/analyze`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data, ...(step > 1 ? {setup_id:p.id} : {})})}); if (step === 1) p.analysis = result; else p[`step${step}_analysis`] = result; setNotice(result.is_valid ? 'Analysis complete. Review the feedback before locking.' : 'Analysis found issues to address.', !result.is_valid); return render(); } if (a === 'lock') { const result = await guidedRequest(`${base}/lock`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data, ...(step > 1 ? {setup_id:p.id} : {})})}); guidedProposalState.active = result; guidedProposalState.step = Math.min(5, step + 1); await refresh(); return render(); } if (a === 'summary' || a === 'evaluate') { const result = await guidedRequest(`/api/proposals/setups/${p.id}/${a === 'summary' ? 'summary' : 'evaluate'}`,{method:a === 'summary' ? 'GET' : 'POST'}); const out = document.getElementById('guided-final-output'); if (out) out.innerHTML = guidedFinalResultHtml(result); } if (a === 'pdf') { const response = await api(`/api/proposals/setups/${p.id}/compile-pdf`,{method:'POST'}); if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || `PDF compilation failed (${response.status})`); } const blob = await response.blob(); const url = URL.createObjectURL(blob); const filename = `${(p.project_title || 'proposal').replace(/[^a-z0-9_-]+/gi, '_')}.pdf`; const oldLink = document.getElementById('guided-pdf-download'); if (oldLink) { URL.revokeObjectURL(oldLink.href); oldLink.remove(); } const link = document.createElement('a'); link.id = 'guided-pdf-download'; link.className = 'guided-btn secondary'; link.href = url; link.download = filename; link.rel = 'noopener'; link.textContent = 'Download PDF'; document.querySelector('.guided-final-actions')?.appendChild(link); link.click(); notifyProposal('PDF hazırlandı. Otomatik indirme engellenirse Download PDF bağlantısına tıkla.'); } } catch (err) { setNotice(err.message, true); } });
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
  const enhanceFinalReview = () => { if (guidedProposalState.step !== 5) return; const output = content.querySelector('#guided-final-output'); if (output && output.tagName === 'PRE') { const panel = document.createElement('div'); panel.id = 'guided-final-output'; panel.className = 'guided-final-output structured'; output.replaceWith(panel); } const actions = content.querySelector('.proposal-narrative-card, .guided-final-actions'); const p = guidedProposalState.active; if (actions && p && !actions.querySelector('[data-guided-download-pdf]')) { const link = document.createElement('a'); link.className = 'btn btn-secondary'; link.dataset.guidedDownloadPdf = 'true'; link.href = `/api/proposals/setups/${encodeURIComponent(p.id)}/compile-pdf`; link.download = `${(p.project_title || 'proposal').replace(/[^a-z0-9_-]+/gi, '_')}.pdf`; link.textContent = 'Download PDF'; actions.querySelector('[data-guided-action="pdf"]')?.after(link); } };
  new MutationObserver(() => { syncDonorContext(); syncCallBrief(); enhanceDonorField(); enhanceBeneficiaryEditor(); enforceLock(); syncDeleteControls(); ensureCallBrief(); syncReviewPanel(); syncViewToolbar(); enhanceFinalReview(); }).observe(content, {childList:true});
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
  if (el.dataset.guidedLogframeAction === 'indicator') { const indicator = { ...(row.indicators?.[0] && typeof row.indicators[0] === 'object' ? row.indicators[0] : {}) }; indicator[el.dataset.indicatorField || 'indicator_title'] = el.value; row.indicators = [indicator]; }
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
document.addEventListener('click', event => {
  const button = event.target.closest('[data-guided-financial-action]'); if (!button || !guidedProposalState.active) return;
  const data = guidedProposalState.active.financial_data || (guidedProposalState.active.financial_data = {}); const kind = button.dataset.guidedFinancialAction;
  if (kind === 'add-budget') (data.budget_items ||= []).push({item_code:`${(data.budget_items.length || 0) + 1}.1`,category:1,description:'',unit_type:'unit',quantity:1,unit_cost:0,duration_frequency:1,donor_grant_share:0,co_financing_share:0});
  if (kind === 'remove-budget') data.budget_items.splice(Number(button.dataset.index), 1);
  if (kind === 'add-risk') (data.risks ||= []).push({category:'Operational',risk_description:'',likelihood:3,impact:3,mitigation_strategy:''});
  if (kind === 'remove-risk') data.risks.splice(Number(button.dataset.index), 1);
  event.preventDefault(); event.stopPropagation(); const host = document.querySelector('.guided-financial-upgraded'); if (host) host.innerHTML = guidedFinancialHtml(guidedProposalState.active, guidedProposalState.active.step4_state === 'locked'); syncFinancialPayloadFields();
}, true);
document.addEventListener('input', event => {
  const el = event.target.closest('[data-guided-financial-kind]'); if (!el || !guidedProposalState.active) return;
  const data = guidedProposalState.active.financial_data || (guidedProposalState.active.financial_data = {}); const kind = el.dataset.guidedFinancialKind; const index = Number(el.dataset.index); const field = el.dataset.field;
  if (kind === 'budget') { const item = (data.budget_items ||= [])[index]; if (item) item[field] = ['quantity','unit_cost','duration_frequency','category'].includes(field) ? Number(el.value || 0) : el.value; }
  else if (kind === 'risk') { const risk = (data.risks ||= [])[index]; if (risk) risk[field] = ['likelihood','impact'].includes(field) ? Number(el.value || 0) : el.value; }
  else if (kind === 'root') data[field] = el.type === 'checkbox' ? el.checked : el.value;
  syncFinancialPayloadFields();
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
function syncFinancialPayloadFields() {
  const content = document.getElementById('wizard-section-content'); const data = guidedProposalState.active?.financial_data || {}; if (!content || guidedProposalState.step !== 4) return;
  [['budget_items', data.budget_items || []], ['risks', data.risks || []], ['psea_signoff', !!data.psea_signoff], ['sphere_standards_narrative', data.sphere_standards_narrative || '']].forEach(([key, value]) => { let field = content.querySelector(`[data-guided-field="${key}"]`); if (!field) { field = document.createElement(key === 'psea_signoff' ? 'input' : 'textarea'); field.dataset.guidedField = key; field.hidden = true; if (key === 'psea_signoff') field.type = 'checkbox'; content.appendChild(field); } if (field.type === 'checkbox') field.checked = !!value; else field.value = typeof value === 'string' ? value : JSON.stringify(value); });
}
function upgradeVisibleFinancialEditor() {
  const content = document.getElementById('wizard-section-content'); if (!content || guidedProposalState.step !== 4) return;
  const budget = content.querySelector('[data-guided-field="budget_items"]:not([hidden])');
  if (budget && budget.dataset.financialUpgraded !== 'true') { const wrapper = budget.closest('.guided-field, .form-group, label') || budget.parentElement; if (wrapper) { const host = document.createElement('div'); host.className = 'guided-financial-upgraded'; host.innerHTML = guidedFinancialHtml(guidedProposalState.active, guidedProposalState.active?.step4_state === 'locked'); budget.dataset.financialUpgraded = 'true'; wrapper.replaceWith(host); } }
  const risk = content.querySelector('[data-guided-field="risks"]:not([hidden])'); if (risk) risk.closest('.guided-field, .form-group, label')?.remove();
  const psea = content.querySelector('[data-guided-field="psea_signoff"]:not([hidden])'); if (psea) psea.closest('label')?.remove();
  const sphere = content.querySelector('[data-guided-field="sphere_standards_narrative"]:not([hidden])'); if (sphere) sphere.closest('.guided-field, .form-group, label')?.remove();
  syncFinancialPayloadFields();
}
setInterval(() => { upgradeVisibleTechnicalMatrix(); upgradeVisibleFinancialEditor(); }, 250);

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
})();

// ── Expose proposal functions for app.js event delegation ────────────────────
window.selectProposal = selectProposal;
window.deleteProposalItem = deleteProposalItem;
window.generateSection = generateSection;
window.saveSectionManual = saveSectionManual;
window.approveSection = approveSection;
window.skipSection = skipSection;
window.wizardSelectStep = wizardSelectStep;
window.createProposalFromSitrep = createProposalFromSitrep;
