
// (removed: viewCrisisSitrep was dead code — 'dash-view-crisis' action
// handles country navigation inline in the event delegation switch)




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
  const isPremium = window.__userRole === 'premium' || window.__userRole === 'admin';
  if (modelToggle && modelMenu) {
    modelToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      modelMenu.classList.toggle('open');
    });
    document.addEventListener('click', () => modelMenu.classList.remove('open'));
    modelMenu.addEventListener('click', (e) => e.stopPropagation());

    function selectModel(key, name) {
      chatState.selectedModel = key;
      const label = document.getElementById('model-selector-label');
      if (label) label.textContent = name;
      modelMenu.querySelectorAll('.model-option').forEach(o => o.classList.remove('active'));
      const opt = modelMenu.querySelector('.model-option[data-model="' + key + '"]');
      if (opt) opt.classList.add('active');
      const cs = document.getElementById('custom-model-select');
      if (cs) cs.value = '';
      modelMenu.classList.remove('open');
      if (typeof updateObsModel === 'function') updateObsModel();
    }

    modelMenu.querySelectorAll('.model-option').forEach(opt => {
      opt.addEventListener('click', () => {
        const key = opt.dataset.model;
        if (!key) return;
        const cfg = CHAT_MODELS[key];
        if (cfg && cfg.premium && !isPremium) {
          toast(`${cfg.name} requires a Premium account`, 'warning');
          return;
        }
        selectModel(key, cfg.name);
      });
    });

    // Custom model dropdown (premium/admin only) — OpenRouter extras
    const customSelect = document.getElementById('custom-model-select');
    const customWrap = document.getElementById('model-custom');
    if (customSelect) {
      customSelect.innerHTML = '<option value="">— Select model —</option>' +
        Object.keys(CUSTOM_MODELS).map(k =>
          '<option value="' + k + '">' + CUSTOM_MODELS[k].name + '</option>'
        ).join('');
      customSelect.addEventListener('change', () => {
        const key = customSelect.value;
        if (!key) return;
        const cfg = CUSTOM_MODELS[key];
        if (cfg && cfg.premium && !isPremium) {
          toast('Premium account required', 'warning');
          customSelect.value = '';
          return;
        }
        selectModel(key, cfg.name);
      });
      if (!isPremium && customWrap) {
        customWrap.classList.add('locked');
        customSelect.disabled = true;
      }
    }

    // Lock premium models for non-premium users (Deep Think + Vision)
    if (!isPremium) {
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
    mainEl.addEventListener('click', () => {
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
  // Observation panel toggle (right-side agent trace)
  const obsToggleBtn = document.getElementById('obs-toggle-btn');
  if (obsToggleBtn) obsToggleBtn.addEventListener('click', toggleObsPanel);
  const obsCloseBtn = document.getElementById('obs-close-btn');
  if (obsCloseBtn) obsCloseBtn.addEventListener('click', () => setObsOpen(false));
  // Restore observation panel open state (if previously opened)
  try {
    if (localStorage.getItem('sightline.obsOpen') === '1') {
      setObsOpen(true);
      renderObsOverview();
      updateObsModel();
    }
  } catch (e) { /* ignore */ }
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
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      chatState.mode = mode;
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
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

  ['inp-date-from', 'inp-date-to', 'inp-themes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', scheduleChunkPreview);
    if (el && el.tagName === 'INPUT' && el.type !== 'date') el.addEventListener('input', scheduleChunkPreview);
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
      case 'cc-start-sitrep':
        ccStartSitrep();
        break;
      case 'cc-start-proposal':
        switchTab('proposal');
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
        switchTab('proposal');
        break;
      case 'cc-open-sitrep': {
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
      }
      case 'cc-open-bulletin': {
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
      }
      case 'toggle-cc-acc': {
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
      }
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
      case 'dash-view-crisis': {
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
      }
      case 'switch-report-view':
        switchReportView(target.dataset.mode);
        break;
      case 'view-recent-report': {
        const rid = parseInt(target.dataset.reportId, 10);
        if (rid) openDbReport(rid);
        break;
      }
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
      case 'delete-sitrep-report':
        event.stopPropagation();
        deleteSitrepReport(target.dataset.file, target.closest('.report-item'));
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
    console.warn('[app] initPreviewData — showing app with login overlay');
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
      console.warn('[app] preview-ready event — forcing login');
      initPreviewData();
    }, { once: true });
    // Listen for auth-ready (user signed in — load full app)
    window.addEventListener('auth-ready', () => {
      console.warn('[app] auth-ready event — loading full app after sign-in');
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
        console.warn('[app] auth-ready event missed, initializing with cached token');
        initAppData();
      }
    }, 3000);
  }
});
