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
  for (const [, f] of Object.entries(fieldMap)) {
    const c = prop[f];
    if (c && c !== '{}' && c !== '[]' && c !== '' && c !== null && c !== undefined) filledSections++;
  }
  const progressPct = Math.round((filledSections / totalSections) * 100);

  // Get existing review data
  let review = null;
  try { review = prop.review ? (typeof prop.review === 'string' ? JSON.parse(prop.review) : prop.review) : null; } catch { review = null; }

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

  levels.forEach((prob) => {
    levels.toReversed().forEach((imp) => {
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

// Called from inline HTML attributes (onchange="uploadReference()").
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

// Called from inline HTML attributes (onclick="deleteReference()").
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

