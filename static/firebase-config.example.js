/**
 * firebase-config.example.js — Template for Firebase web SDK configuration.
 *
 * Copy this file to firebase-config.js and fill in your Firebase project's
 * web app credentials. These values are PUBLIC (used by the client-side
 * Firebase JS SDK) — they are NOT secret. Firebase security is enforced
 * server-side via the Admin SDK (firebase-service-account.json) and
 * Firestore Security Rules, not by hiding these values.
 *
 * Get these from: Firebase Console → Project Settings → General → Your apps → Web app.
 * https://console.firebase.google.com/
 *
 * If firebase-config.js is absent, Sightline runs in DESKTOP_MODE
 * (no Firebase auth, local admin bypass).
 *
 * IMPORTANT: Set authDomain to your custom domain (not the firebaseapp.com default).
 * This is required for redirect-based auth to work correctly.
 */

window.FIREBASE_CONFIG = {
  apiKey: "YOUR_API_KEY",
  authDomain: "your-domain.com",
  projectId: "your-project-id",
  storageBucket: "your-project-id.firebasestorage.app",
  messagingSenderId: "YOUR_SENDER_ID",
  appId: "YOUR_APP_ID",
  measurementId: "YOUR_MEASUREMENT_ID"
};