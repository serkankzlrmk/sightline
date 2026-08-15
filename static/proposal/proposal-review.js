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
    } catch {}

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
          // Stream tokens are not displayed incrementally — the server
          // returns the full updated section at the end (see below).
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
  } catch { }

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

