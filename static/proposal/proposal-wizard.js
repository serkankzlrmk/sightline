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

// ── Resolve shared dependencies ──────────────────────────────────────────────
// api/escHtml/toast/sanitizeHtml now come from shared.js (loaded before
// app.js); switchTab is still exported by app.js (depends on currentTab).
// (toast not imported here — proposal.js uses its own inline toast element.)
const api = window.api;
const escHtml = window.escHtml;
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
        : renderJsonSection(typeof sectionContent === 'string' ? (() => { try { return JSON.parse(sectionContent); } catch { return sectionContent; } })() : sectionContent, step))
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

