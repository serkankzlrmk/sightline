/**
 * auth.js — Firebase Authentication (Google Sign-In) for RedAgent online.
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

export function getIdToken() {
  return localStorage.getItem("id_token") || "";
}
window.getIdToken = getIdToken; // legacy compat

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

// Admin check helper
async function checkAdminStatus() {
  try {
    const tok = getIdToken();
    if (!tok) { window.__isAdmin = false; return; }
    const resp = await fetch("/api/auth/me", { headers: { "Authorization": "Bearer " + tok } });
    const data = await resp.json();
    window.__isAdmin = !!data.is_admin;
  } catch (e) {
    window.__isAdmin = false;
  }
}

// ── UI toggles based on admin ──────────────────────────────────────────
function updateVisibility() {
  const isAdmin = !!window.__isAdmin;
  // Hide Ingest tab for non-admins
  const ingestTab = document.getElementById("tab-ingest");
  if (ingestTab) {
    ingestTab.style.display = isAdmin ? "" : "none";
  }
  // Hide SITREP "New Report" form for non-admins
  const sitrepRunForm = document.getElementById("btn-toggle-form");
  const runForm = document.getElementById("run-form");
  if (sitrepRunForm) {
    sitrepRunForm.style.display = isAdmin ? "" : "none";
    if (runForm) runForm.classList.add("hidden");
  }
  if (!isAdmin) {
    // Switch away from Ingest if a non-admin managed to land on it
    if (document.getElementById("tab-ingest")?.classList.contains("active")) {
      if (typeof switchTab === "function") switchTab("agent");
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
  } catch (err) {
    console.error("Login failed:", err);
    if (err.code === "auth/popup-closed-by-user") {
      setAuthError("Sign-in popup was closed before completing.");
    } else if (err.code === "auth/configuration-not-found") {
      setAuthError("Google Sign-In is disabled in Firebase Console. Go to Firebase Console → Authentication → Sign-in method → Google → Enable.");
    } else if (err.code === "auth/auth-domain-config-required" || err.code === "auth/unauthorized-domain") {
      setAuthError("This domain (e.g. localhost) is not authorized in Firebase Console. Add it in Firebase Console → Authentication → Settings → Authorized domains. For local testing add: localhost");
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
  showOverlay();
  showUserBar(null);
}
window.signOut = signOut;

// ═══════════════════════════════════════════════════════════
// Wire UI
// ═══════════════════════════════════════════════════════════

function init() {
  const btn = document.getElementById("auth-google-btn");
  if (btn) btn.addEventListener("click", doSignIn);

  onAuthStateChanged(auth, async (user) => {
    if (user) {
      const token = await user.getIdToken(true);
      setToken(token);
      await checkAdminStatus();
      updateVisibility();
      hideOverlay();
      showUserBar(user);
    } else {
      clearToken();
      window.__isAdmin = false;
      showOverlay();
      showUserBar(null);
    }
  });
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
    hideOverlay();
    showUserBar(result.user);
  } catch (err) {
    console.error("Login failed:", err);
    if (err.code === "auth/popup-closed-by-user") {
      setAuthError("Sign-in popup was closed before completing.");
    } else if (err.code === "auth/configuration-not-found") {
      setAuthError("Google Sign-In is disabled in Firebase Console. Go to Firebase Console → Authentication → Sign-in method → Google → Enable.");
    } else if (err.code === "auth/auth-domain-config-required" || err.code === "auth/unauthorized-domain") {
      setAuthError("This domain (e.g. localhost) is not authorized in Firebase Console. Add it in Firebase Console → Authentication → Settings → Authorized domains. For local testing add: localhost");
      setAuthError("This domain is not authorized in Firebase. Add it in Firebase Console → Authentication → Settings → Authorized domains.");
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
  showOverlay();
  showUserBar(null);
}
window.signOut = signOut;

// ═══════════════════════════════════════════════════════════
// Wire UI
// ═══════════════════════════════════════════════════════════

function init() {
  const btn = document.getElementById("auth-google-btn");
  if (btn) btn.addEventListener("click", doSignIn);

  onAuthStateChanged(auth, async (user) => {
    if (user) {
      const token = await user.getIdToken(true);
      setToken(token);
      hideOverlay();
      showUserBar(user);
    } else {
      clearToken();
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
