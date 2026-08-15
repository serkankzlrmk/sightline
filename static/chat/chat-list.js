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

