// ═══════════════════════════════════════════════════════════════
// chat.js — TAB 2: Agent Chat (multi-chat) — extracted from app.js
// Loaded via <script> tag after shared.js, before app.js
// ═══════════════════════════════════════════════════════════════

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
  el.className = 'tool-ind pending';
  el.dataset.toolName = name;
  el.innerHTML = `<div class="spin"></div><span class="tool-ind-label"><strong>${esc(name)}</strong> running...</span>`;
  center.appendChild(el);
  chatDiv.scrollTop = chatDiv.scrollHeight;
  return el;
}

function finalizeToolInd(name, data) {
  const inds = chatDiv.querySelectorAll('.tool-ind');
  for (const ind of inds) {
    if (ind.dataset.toolName !== name) continue;
    ind.classList.remove('pending');
    ind.classList.add('done');
    if (data && data.status === 'error') ind.classList.add('error');
    const label = ind.querySelector('.tool-ind-label');
    const spin = ind.querySelector('.spin');
    if (spin) spin.remove();
    const summary = (data && data.summary) || '';
    const dur = (data && data.duration_ms) ? ` · ${(data.duration_ms / 1000).toFixed(1)}s` : '';
    const mark = (data && data.status === 'error') ? '✗' : '✓';
    if (label) {
      label.innerHTML = `<strong>${esc(name)}</strong> <span class="tool-status">${mark}</span>${summary ? ` <span class="tool-summary">${esc(summary)}</span>` : ''}${dur}`;
    }
    return;
  }
}

function clearToolInds() {
  chatDiv.querySelectorAll('.tool-ind').forEach(e => e.remove());
}

function fmtTokens(n) {
  n = n || 0;
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(n);
}

function renderTeleFooter(meta) {
  if (!meta) return '';
  const parts = [];
  if (meta.latency_ms) parts.push((meta.latency_ms / 1000).toFixed(1) + 's');
  if (meta.iterations) parts.push(meta.iterations + ' iter');
  if (meta.tools && meta.tools.length) parts.push(meta.tools.length + ' tools');
  if (meta.model) parts.push(esc(meta.model));
  if (meta.usage && (meta.usage.in || meta.usage.out)) {
    parts.push(fmtTokens(meta.usage.in) + ' in / ' + fmtTokens(meta.usage.out) + ' out');
  }
  if (meta.cost != null) parts.push('$' + meta.cost.toFixed(4));
  if (!parts.length) return '';
  return `<div class="tele-footer">${parts.join(' · ')}</div>`;
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
  } catch {
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
        } else if (evt.type === 'tool_done') {
          finalizeToolInd(evt.name, evt);
        } else if (evt.type === 'error') {
          chatState.currentAiEl.innerHTML = `<span class="msg-error">Error: ${esc(evt.text)}</span>`;
          clearToolInds();
        } else if (evt.type === 'done') {
          // Drop any tool indicator that never got a matching tool_done
          chatDiv.querySelectorAll('.tool-ind.pending').forEach(e => e.remove());
          if (!chatState.currentAiText) chatState.currentAiEl.innerHTML = '<span class="msg-placeholder">—</span>';
          const footer = renderTeleFooter(evt);
          if (footer) chatState.currentAiEl.insertAdjacentHTML('beforeend', footer);
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

