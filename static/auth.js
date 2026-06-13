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
  signInWithRedirect,
  getRedirectResult,
  signOut as firebaseSignOut,
  onAuthStateChanged,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

const FIREBASE_CONFIG = {
  apiKey: "AIzaSyDPKhEe-ftF_Fm0Vp4X8SqqVgK5844ps8I",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT_ID",
  storageBucket: "YOUR_PROJECT_ID.firebasestorage.app",
  messagingSenderId: "402718388379",
  appId: "1:402718388379:web:3c546d2ff143052abbd63e",
  measurementId: "G-S1D8L1CNTB"
};

initializeApp(FIREBASE_CONFIG);
const auth   = getAuth();
const google = new GoogleAuthProvider();

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

// ═══════════════════════════════════════════════════════════
// UI helpers
// ═══════════════════════════════════════════════════════════

function showOverlay() {
  const el = document.getElementById("auth-overlay");
  if (el) el.classList.remove("hidden");
  document.body.classList.add("auth-locked");
}

function hideOverlay() {
  const el = document.getElementById("auth-overlay");
  if (el) el.classList.add("hidden");
  document.body.classList.remove("auth-locked");
}

function showUserBar(user) {
  const bar   = document.getElementById("user-bar");
  const photo = document.getElementById("user-photo");
  const name  = document.getElementById("user-name");
  if (!bar) return;
  if (user) {
    if (photo) photo.src = user.photoURL || "";
    if (name)  name.textContent = user.displayName || user.email || "User";
    bar.classList.remove("hidden");
  } else {
    bar.classList.add("hidden");
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
  if (!tok) {
    window.__isAdmin = false;
    window.__userRole = "free";
    window.__rateLimit = null;
    return;
  }
  if (_adminCheckPromise) return _adminCheckPromise;
  _adminCheckPromise = (async () => {
    try {
      console.log("[auth] checkAdminStatus: calling /api/auth/me with token prefix", tok.substring(0, 12) + "...");
      const resp = await fetch("/api/auth/me", { headers: { "Authorization": "Bearer " + tok } });
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
  const sitrepRunForm = document.getElementById("btn-toggle-form");
  const runForm = document.getElementById("run-form");
  if (sitrepRunForm) {
    sitrepRunForm.style.display = isPremium ? "" : "none";
    if (runForm && !isPremium) runForm.classList.add("hidden");
  }

  // PDF upload button: admin only
  const uploadBtn = document.getElementById("btn-upload-pdf");
  if (uploadBtn) uploadBtn.style.display = isAdmin ? "" : "none";

  // Admin tab: admin only
  const adminTab = document.getElementById("tab-admin");
  if (adminTab) adminTab.style.display = isAdmin ? "" : "none";
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
      console.log("[auth] Popup blocked, falling back to redirect...");
      try {
        await signInWithRedirect(auth, google);
      } catch (redirectErr) {
        setAuthError("Redirect sign-in failed: " + redirectErr.message);
      }
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
  showOverlay();
  showUserBar(null);
}
window.signOut = signOut;

setInterval(async () => {
  if (typeof auth !== 'undefined' && auth.currentUser) {
    try {
      const freshToken = await auth.currentUser.getIdToken(true);
      setToken(freshToken);
    } catch (e) { /* ignore */ }
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
     auto-bypass the auth overlay so we can test locally without Google Sign-In. */
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) return false;
    const data = await resp.json();
    return !!data.dev_mode;
  } catch (e) {
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

  // Check for redirect sign-in result (page reload after redirect)
  getRedirectResult(auth).then(async (result) => {
    if (result && result.user) {
      console.log("[auth] Redirect sign-in successful, uid=", result.user.uid);
      const token = await result.user.getIdToken(true);
      setToken(token);
      await checkAdminStatus();
      updateVisibility();
      hideOverlay();
      showUserBar(result.user);
      window.__authReady = true;
      window.dispatchEvent(new Event('auth-ready'));
    }
  }).catch((err) => {
    console.error("[auth] Redirect result error:", err);
  });

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
      console.log("[auth] onAuthStateChanged: no user (signed out or first load)");
      clearToken();
      window.__isAdmin = false;
      window.__userRole = "free";
      showOverlay();
      showUserBar(null);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}