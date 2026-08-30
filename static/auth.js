/**
 * auth.js — Firebase Authentication (Google Sign-In) for Sightline online.
 *
 * - Handles login / logout via Firebase popup.
 * - Stores the ID token in localStorage as `id_token`.
 * - Provides getIdToken() for every API request (used by app.js).
 * - Toggles the auth overlay and user-info bar.
 */

import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as firebaseSignOut,
  onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

// Firebase config is loaded from window.FIREBASE_CONFIG (set by firebase-config.js).
// If firebase-config.js is absent, Sightline runs in DESKTOP_MODE (no Firebase auth).
if (typeof window.FIREBASE_CONFIG === 'undefined') {
  console.warn('[auth] No firebase-config.js found — running in DESKTOP_MODE (no Firebase auth)');
  // Provide a no-op stub so the module doesn't crash on import
  window.FIREBASE_CONFIG = null;
}

if (window.FIREBASE_CONFIG) {
  initializeApp(window.FIREBASE_CONFIG);
}
const auth   = window.FIREBASE_CONFIG ? getAuth() : null;
const google = window.FIREBASE_CONFIG ? new GoogleAuthProvider() : null;

// ═══════════════════════════════════════════════════════════
// Token storage
// ═══════════════════════════════════════════════════════════

function setToken(tok) {
  localStorage.setItem("id_token", tok);
  window.__idToken = tok;
}

function clearToken() {
  localStorage.removeItem("id_token");
  window.__idToken = "";
}

async function refreshIdToken() {
  if (typeof auth !== 'undefined' && auth.currentUser) {
    try {
      const freshToken = await auth.currentUser.getIdToken(true);
      setToken(freshToken);
      return freshToken;
    } catch (e) {
      console.warn("Token refresh failed:", e);
    }
  }
  return localStorage.getItem("id_token") || "";
}

export function getIdToken() {
  return localStorage.getItem("id_token") || "";
}
window.getIdToken = getIdToken;
window.refreshIdToken = refreshIdToken;
window.showLoginPanel = showLoginPanel;

// ═══════════════════════════════════════════════════════════
// UI helpers
// ═══════════════════════════════════════════════════════════

function showLoginPanel() {
  // Slide-in the login panel from the right (triggered by gated tab click).
  // The backdrop locks the page behind it — the gated tab IS visible (the
  // visitor can see where they clicked) but nothing behind is clickable
  // until they sign in or close the panel.
  const el = document.getElementById("auth-overlay");
  if (el) {
    el.classList.remove("hidden");
    el.classList.add("slide-in");
    el.style.display = "";
  }
  document.body.classList.add("auth-locked");
}

function hideOverlay() {
  const el = document.getElementById("auth-overlay");
  if (el) {
    el.classList.add("hidden");
    el.classList.remove("slide-in");
    el.style.display = "none";
  }
  document.body.classList.remove("preview-mode");
  document.body.classList.remove("auth-locked");
  document.body.offsetHeight;
  // Remember the dismiss so the panel doesn't keep forcing itself open
  // for the rest of this browser session (tab switch re-opens on demand).
  try { sessionStorage.setItem("sightline_login_dismissed", "1"); } catch (e) { console.debug(e); }
}

// Close button on the slide-in login panel
document.addEventListener("click", (e) => {
  if (e.target && e.target.id === "auth-close-btn") {
    hideOverlay();
  }
});

function showUserBar(user) {
  const bar   = document.getElementById("user-bar");
  const photo = document.getElementById("user-photo");
  const name  = document.getElementById("user-name");
  if (!bar) return;
  if (user) {
    if (photo) photo.src = user.photoURL || "";
    if (name)  name.textContent = user.displayName || user.email || "User";
    bar.classList.remove("hidden");
    // Mobile user button
    const mBtn  = document.getElementById("mobile-user-btn");
    const mPhoto = document.getElementById("mobile-user-photo");
    const mName = document.getElementById("mobile-user-name");
    if (mBtn) {
      if (mPhoto) mPhoto.src = user.photoURL || "";
      if (mName) mName.textContent = (user.displayName || user.email || "User").split(' ')[0];
      mBtn.style.display = '';
    }
  } else {
    bar.classList.add("hidden");
    const mBtn = document.getElementById("mobile-user-btn");
    if (mBtn) mBtn.style.display = 'none';
  }
}

function setAuthError(msg) {
  const el = document.getElementById("auth-error");
  if (el) el.textContent = msg;
}

// ═══════════════════════════════════════════════════════════
// Admin check — only called when we have a real token
// ═══════════════════════════════════════════════════════════

let _adminCheckPromise = null;

async function checkAdminStatus() {
  const tok = getIdToken();
  if (_adminCheckPromise) return _adminCheckPromise;
  _adminCheckPromise = (async () => {
    try {
      // In DESKTOP_MODE there is no Firebase token — still call /api/auth/me
      // (backend resolves the dev-local admin user without a token).
      const headers = tok ? { "Authorization": "Bearer " + tok } : {};
      const resp = await fetch("/api/auth/me", { headers });
      if (!resp.ok) {
        const err = await resp.text();
        console.error("[auth] /api/auth/me failed:", resp.status, err);
        window.__isAdmin = false;
        window.__userRole = "free";
        window.__rateLimit = null;
        return;
      }
      const data = await resp.json();
      console.log("[auth] /api/auth/me result:", data);
      window.__isAdmin = !!data.is_admin;
      window.__userRole = data.role || "free";
      window.__rateLimit = data.rate_limit || null;
      updateRateLimitUI();
      updateVisibility();
    } catch (e) {
      console.error("[auth] checkAdminStatus error:", e);
      window.__isAdmin = false;
      window.__userRole = "free";
      window.__rateLimit = null;
    } finally {
      _adminCheckPromise = null;
    }
  })();
  return _adminCheckPromise;
}

function updateRateLimitUI() {
  const bar = document.getElementById("user-bar");
  if (!bar) return;

  // Find or create badges container
  let badgesDiv = bar.querySelector(".user-bar-badges");
  if (!badgesDiv) {
    badgesDiv = document.createElement("div");
    badgesDiv.className = "user-bar-badges";
    const infoDiv = bar.querySelector(".user-bar-info");
    if (infoDiv) infoDiv.appendChild(badgesDiv);
  }

  // Role badge
  let roleBadge = document.getElementById("role-badge");
  if (!roleBadge) {
    roleBadge = document.createElement("span");
    roleBadge.id = "role-badge";
    badgesDiv.appendChild(roleBadge);
  }
  const role = window.__userRole || "free";
  if (role === "admin") {
    roleBadge.textContent = "ADMIN";
    roleBadge.className = "role-badge role-admin";
    roleBadge.style.display = "";
  } else if (role === "premium") {
    roleBadge.textContent = "PRO";
    roleBadge.className = "role-badge role-premium";
    roleBadge.style.display = "";
  } else {
    roleBadge.style.display = "none";
  }

  // Rate limit badge
  let badge = document.getElementById("rate-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.id = "rate-badge";
    badgesDiv.appendChild(badge);
  }
  const rl = window.__rateLimit;
  if (!rl || window.__isAdmin) {
    badge.textContent = "";
    badge.style.display = "none";
    return;
  }
  badge.style.display = "";
  const remaining = rl.remaining;
  if (remaining <= 0) {
    badge.textContent = "0/" + rl.limit;
    badge.className = "rate-badge rate-limit-exhausted";
  } else if (remaining <= 3) {
    badge.textContent = remaining + "/" + rl.limit;
    badge.className = "rate-badge rate-limit-low";
  } else {
    badge.textContent = remaining + "/" + rl.limit;
    badge.className = "rate-badge";
  }

  // Lock/unlock chat input based on rate limit
  if (typeof lockChatInput === 'function') lockChatInput();
}

function updateVisibility() {
  const role = window.__userRole || "free";
  const isAdmin = role === "admin";
  const isPremium = role === "premium" || isAdmin;

  // SITREP run form: visible for premium + admin
  const sitrepFormBar = document.getElementById("sitrep-form-bar");
  if (sitrepFormBar) sitrepFormBar.style.display = isPremium ? "" : "none";

  // PDF upload button: admin only
  const uploadBtn = document.getElementById("btn-upload-pdf");
  if (uploadBtn) uploadBtn.style.display = isAdmin ? "" : "none";

  // Admin tab: admin only
  const adminTab = document.getElementById("tab-admin");
  if (adminTab) adminTab.style.display = isAdmin ? "" : "none";

  // Bulletin generate button: admin only
  document.querySelectorAll(".admin-only").forEach(el => {
    el.style.display = isAdmin ? "" : "none";
  });

  // Model selector: lock premium models for non-premium
  document.querySelectorAll('.model-option-premium').forEach(opt => {
    opt.classList.toggle("locked", !isPremium);
  });

  // Custom model dropdown (premium/admin only)
  const customWrap = document.getElementById("model-custom");
  const customSelect = document.getElementById("custom-model-select");
  if (customSelect) customSelect.disabled = !isPremium;
  if (customWrap) customWrap.classList.toggle("locked", !isPremium);

  // Database: show premium banner for free users
  const premiumBanner = document.getElementById("db-premium-banner");
  const recentList = document.getElementById("db-recent-list");
  const fullAccess = document.getElementById("db-full-access");
  if (premiumBanner) premiumBanner.style.display = isPremium ? "none" : "flex";
  if (recentList) recentList.style.display = isPremium ? "none" : "block";
  if (fullAccess) fullAccess.classList.toggle("hidden", !isPremium);

  // Bottom CTA Section + Promo block visibility
  const ctaAuth    = document.getElementById("walkthrough-cta-auth");
  const ctaExplore = document.getElementById("walkthrough-cta-explore");
  const promoBlock = document.getElementById("wt-promo-block");
  const isAuthed   = !!getIdToken();

  // Individual CTA cards (used only when block is visible)
  if (ctaAuth)    ctaAuth.style.display    = isAuthed ? "none"  : "block";
  if (ctaExplore) ctaExplore.style.display = isAuthed ? "block" : "none";

  // Collapse/expand the whole walkthrough section smoothly
  if (promoBlock) {
    if (isAuthed) {
      promoBlock.style.maxHeight = "0px";
      promoBlock.style.opacity   = "0";
      promoBlock.style.pointerEvents = "none";
      promoBlock.style.marginTop = "0";
      promoBlock.style.paddingTop = "0";
    } else {
      promoBlock.style.maxHeight = "9999px";
      promoBlock.style.opacity   = "1";
      promoBlock.style.pointerEvents = "auto";
    }
  }
}

// ═══════════════════════════════════════════════════════════
// Login / Logout
// ═══════════════════════════════════════════════════════════

async function doSignIn() {
  setAuthError("");
  try {
    const result = await signInWithPopup(auth, google);
    const token  = await result.user.getIdToken(true);
    setToken(token);
    await checkAdminStatus();
    updateVisibility();
    hideOverlay();
    showUserBar(result.user);
    window.__authReady = true;
    window.dispatchEvent(new Event('auth-ready'));
  } catch (err) {
    console.error("Login failed:", err);
    if (err.code === "auth/popup-blocked" || err.code === "auth/operation-not-supported-in-this-environment") {
      setAuthError("Popup was blocked by your browser. Please allow popups for this site and try again.");
    } else if (err.code === "auth/popup-closed-by-user") {
      setAuthError("Sign-in popup was closed before completing.");
    } else if (err.code === "auth/configuration-not-found") {
      setAuthError("Google Sign-In is disabled in Firebase Console. Go to Firebase Console → Authentication → Sign-in method → Google → Enable.");
    } else if (err.code === "auth/auth-domain-config-required" || err.code === "auth/unauthorized-domain") {
      setAuthError("This domain is not authorized in Firebase Console. Add it in Firebase Console → Authentication → Settings → Authorized domains.");
    } else if (err.code === "auth/cancelled-by-user") {
      setAuthError("Sign-in was cancelled.");
    } else {
      setAuthError("Sign-in failed: " + err.message);
    }
  }
}

export async function signOut() {
  try {
    await firebaseSignOut(auth);
  } catch (e) {
    console.warn("Sign-out error:", e);
  }
  clearToken();
  window.__isAdmin = false;
  window.__userRole = "free";
  // Sign-out drops back to freemium preview (public content visible,
  // no forced login) — onAuthStateChanged fires the null branch which
  // emits `preview-ready` and loads public data.
  hideOverlay();
  showUserBar(null);
}
window.signOut = signOut;

setInterval(async () => {
  if (typeof auth !== 'undefined' && auth.currentUser) {
    try {
      const freshToken = await auth.currentUser.getIdToken(true);
      setToken(freshToken);
    } catch { /* ignore */ }
  }
}, 50 * 60 * 1000);

window.checkAdminStatus = checkAdminStatus;
window.updateVisibility = updateVisibility;

// ═══════════════════════════════════════════════════════════
// Wire UI — onAuthStateChanged is the SINGLE source of truth
// ═══════════════════════════════════════════════════════════

let _initialized = false;

async function _checkDevMode() {
  /* When server runs in dev mode (SERVER_DEBUG=true, no Firebase SA, no API key),
     auto-bypass the auth overlay so we can test locally without Google Sign-In.
     We probe /api/auth/me with a dummy bearer token — in dev mode the server
     bypasses auth and returns a mock user; in production it returns 401. */
  try {
    const resp = await fetch("/api/auth/me", {
      headers: { "Authorization": "Bearer dev-probe" },
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    return data.uid === "dev-local" || data.dev_mode === true;
  } catch {
    return false;
  }
}

function _enableDevMode() {
  /* Set mock auth state for dev mode — all features unlocked, admin access. */
  console.log("[auth] Dev mode detected — bypassing Firebase Sign-In");
  setToken("dev-mode-bypass");
  window.__isAdmin = true;
  window.__userRole = "admin";
  window.__rateLimit = { remaining: 999, limit: 999, used: 0 };
  window.__authReady = true;
  hideOverlay();
  showUserBar({ photoURL: "", displayName: "Dev User", email: "dev@localhost" });
  updateVisibility();
  updateRateLimitUI();
  window.dispatchEvent(new Event('auth-ready'));
}

function init() {
  if (_initialized) return;
  _initialized = true;

  // Dev mode check — if server has no Firebase, skip sign-in entirely
  _checkDevMode().then((isDev) => {
    if (isDev) {
      _enableDevMode();
      return; // skip Firebase listeners entirely
    }
    _initFirebase();
  });
}

function _initFirebase() {
  const btn = document.getElementById("auth-google-btn");
  if (btn) btn.addEventListener("click", doSignIn);

  const btnBottom = document.getElementById("auth-google-btn-bottom");
  if (btnBottom) btnBottom.addEventListener("click", doSignIn);

  // NOTE: signInWithRedirect removed — was causing blank page on firebaseapp.com/__/auth/handler.
  // signInWithPopup is the only auth method now. If popup is blocked, user is prompted to allow popups.

  onAuthStateChanged(auth, async (user) => {
    if (user) {
      console.log("[auth] onAuthStateChanged: user detected, uid=", user.uid);
      const token = await user.getIdToken(true);
      setToken(token);
      console.log("[auth] token obtained, length=", token.length);
      await checkAdminStatus();
      updateVisibility();
      hideOverlay();
      showUserBar(user);
      window.__authReady = true;
      window.dispatchEvent(new Event('auth-ready'));
    } else {
      console.log("[auth] onAuthStateChanged: no user (signed out or first load) — entering preview mode");
      clearToken();
      window.__isAdmin = false;
      window.__userRole = "free";
      // Freemium preview: anonymous visitors read public content freely —
      // dashboard, crisis map, bulletins and SITREP reports load without
      // login. NO overlay is shown on arrival from search engines or shared
      // links; the slide-in login panel opens ONLY when a gated tab (Chat,
      // Database, Admin) is clicked (see switchTab in app.js).
      // `preview-ready` still fires so public data initializes (map-init.js).
      window.__authReady = false;
      window.dispatchEvent(new Event('preview-ready'));
      showUserBar(null);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}