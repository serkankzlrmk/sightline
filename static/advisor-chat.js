// ── Proposal Assistant: Review / Chat tab switching ──────────────────────────
// V2-only: uses guidedProposalState.active.id.
window.switchAdvisorTab = function switchAdvisorTab(tab) {
  const reviewEl = document.getElementById("review-content");
  const chatEl = document.getElementById("advisor-chat-content");
  const tabReview = document.getElementById("tab-btn-review");
  const tabChat = document.getElementById("tab-btn-chat");

  if (tab === "chat") {
    if (reviewEl) reviewEl.style.display = "none";
    if (chatEl) chatEl.style.display = "flex";
    if (tabReview) tabReview.classList.remove("active");
    if (tabChat) tabChat.classList.add("active");
    loadAdvisorChatHistory();
    const input = document.getElementById("advisor-chat-input");
    if (input) setTimeout(() => input.focus(), 100);
  } else {
    if (reviewEl) reviewEl.style.display = "block";
    if (chatEl) chatEl.style.display = "none";
    if (tabReview) tabReview.classList.add("active");
    if (tabChat) tabChat.classList.remove("active");
  }
};

// ── Helper: resolve the active V2 setup id ──────────────────────────────────
function _advisorSetupId() {
  // V2 guided proposal (the only proposal workspace)
  if (typeof guidedProposalState !== "undefined" && guidedProposalState.active?.id) {
    return { id: guidedProposalState.active.id, isV2: true };
  }
  return null;
}

// ── Advisor Chat ─────────────────────────────────────────────────────────────
async function loadAdvisorChatHistory() {
  const info = _advisorSetupId();
  if (!info) return;

  const messagesEl = document.getElementById("advisor-chat-messages");
  if (!messagesEl) return;

  // Avoid reloading for the same session
  const cacheKey = `_chatHistoryLoaded_${info.id}`;
  if (typeof window[cacheKey] !== "undefined" && window[cacheKey] === info.id) return;
  window[cacheKey] = info.id;

  try {
    const path = `/api/proposals/setups/${info.id}/advisor/history`;

    const resp = await api(path);
    if (!resp.ok) return;
    const data = await resp.json();
    const messages = Array.isArray(data) ? data : (data.messages || []);
    if (messages.length > 0) {
      messagesEl.innerHTML = "";
      for (const msg of messages) {
        appendAdvisorChatBubble(msg.role === "user" ? "You" : "Sightline Advisor", msg.content, msg.role);
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  } catch(e) {
    console.warn("Failed to load advisor chat history:", e);
  }
}

// Markdown render for advisor bubbles. `marked` is loaded via CDN in
// index.html; fall back to escaped plain text when unavailable.
function renderMarkdown(text) {
  if (typeof text !== 'string') return '';
  if (typeof window.marked === 'function') {
    try { return window.marked.parse(text); } catch { /* fall through */ }
  }
  return escHtml(text);
}

function appendAdvisorChatBubble(sender, text, role) {
  const messagesEl = document.getElementById("advisor-chat-messages");
  if (!messagesEl) return;
  const isUser = role === "user";
  const bubble = document.createElement("div");
  bubble.style.cssText = `padding:10px 14px; border-radius:10px; max-width:90%; font-size:13px; line-height:1.5; word-break:break-word; ${isUser ? "margin-left:auto; background:var(--primary); color:white; border-bottom-right-radius:3px;" : "margin-right:auto; background:var(--bg-light); color:var(--text-primary); border:1px solid var(--border-color); border-bottom-left-radius:3px;"}`;
  bubble.innerHTML = `<div style="font-size:11px; font-weight:600; margin-bottom:4px; ${isUser ? "color:rgba(255,255,255,0.8);" : "color:var(--primary);"}">${escHtml(sender)}</div>${isUser ? escHtml(text) : renderMarkdown(text)}`;
  messagesEl.appendChild(bubble);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

let _advisorChatBusy = false;
async function sendAdvisorChat() {
  const input = document.getElementById("advisor-chat-input");
  const btn = document.getElementById("btn-send-advisor-chat");
  const messagesEl = document.getElementById("advisor-chat-messages");
  const info = _advisorSetupId();
  if (!input || !info) return;

  const message = input.value.trim();
  if (!message || _advisorChatBusy) return;

  _advisorChatBusy = true;
  if (btn) btn.disabled = true;
  input.value = "";

  appendAdvisorChatBubble("You", message, "user");

  const typingEl = document.createElement("div");
  typingEl.id = "advisor-typing";
  typingEl.style.cssText = "padding:10px 14px; border-radius:10px; max-width:90%; margin-right:auto; background:var(--bg-light); border:1px solid var(--border-color); font-size:13px; color:var(--text-muted);";
  typingEl.innerHTML = '<div class="typing-dots" style="justify-content:center;"><span></span><span></span><span></span></div>';
  messagesEl.appendChild(typingEl);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {
    const path = `/api/proposals/setups/${info.id}/advisor/chat`;

    const resp = await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });
    const data = await resp.json();
    const tEl = document.getElementById("advisor-typing");
    if (tEl) tEl.remove();

    if (data.error) {
      appendAdvisorChatBubble("Error", data.error, "assistant");
    } else {
      appendAdvisorChatBubble("Sightline Advisor", data.response || "Done.", "assistant");
      if (data.command && data.command.action === "refresh") {
        // Refresh the active V2 proposal
        if (typeof guidedProposalState !== "undefined") {
          try {
            const refreshed = await guidedRequest(`/api/proposals/setups/${info.id}`);
            guidedProposalState.active = refreshed;
            if (typeof guidedRender === "function") guidedRender();
          } catch (_) {}
        }
      }
    }
  } catch(err) {
    const tEl = document.getElementById("advisor-typing");
    if (tEl) tEl.remove();
    appendAdvisorChatBubble("Error", "Failed to send message: " + err.message, "assistant");
  } finally {
    _advisorChatBusy = false;
    if (btn) btn.disabled = false;
    input.focus();
  }
}
window.sendAdvisorChat = sendAdvisorChat;