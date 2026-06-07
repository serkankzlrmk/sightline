# Stitch Prompt — ReliefAgent Data Platform UI Redesign

## Overview

Redesign the **ReliefAgent Data Platform** — a humanitarian data analytics web application with 3 main tabs (Database, ReliefAgent Chat, SITREP). The app uses Firebase Auth (Google Sign-In) and has role-based access (free/premium/admin).

## Current Tech Stack

- **Backend:** Python Flask (server.py)
- **Frontend:** Vanilla JS (no framework), single `index.html`, `app.js`, `auth.js`, `style.css`
- **Auth:** Firebase Auth (Google Sign-In)
- **Icons:** Inline SVGs (no icon library)
- **Font:** Inter (Google Fonts)
- **CSS:** Custom properties (CSS variables), no Tailwind

## Design System — Keep These

```css
:root {
  --primary: #C8102E;        /* Red Cross red — brand color */
  --primary-dark: #A00D24;
  --primary-light: #fdf2f2;
  --primary-glow: rgba(200,16,46,.12);
  --bg: #f4f5f7;
  --surface: #ffffff;
  --border: #e2e4e8;
  --border-light: #eff1f3;
  --text: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --navy: #0f1d36;
  --navy-light: #1a2d4d;
  --blue: #2563eb;
  --green: #059669;
  --red: #dc2626;
  --amber: #d97706;
  --radius: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,.06);
  --shadow-md: 0 4px 12px rgba(0,0,0,.07);
  --transition: .2s cubic-bezier(.4,0,.2,1);
  --nav-h: 56px;
  --sidebar-w: 260px;
}
```

## Pages to Design

### 1. Login/Auth Screen
- Full-screen overlay with centered card
- ReliefAgent logo + "Humanitarian Data Analytics Platform" subtitle
- 3 feature cards: Intelligent Search, SITREP Generation, Source Citations
- Google Sign-In button (prominent, centered)
- Clean, professional, humanitarian feel

### 2. Main Layout (3 tabs)
- **Top nav:** Logo left, tabs center, user bar right (avatar, name, role badge, logout)
- **Tab 1 — Database:** Table-based report browser with filters (country, theme, source, date range), stats cards at top
- **Tab 2 — ReliefAgent (Chat):** Gemini-style chat interface
  - Left sidebar: Chat history (slide drawer)
  - Center: Chat messages with welcome screen
  - Welcome screen has feature sections (Search, Ask, Ingest, More) + category-tinted quick prompt buttons
  - Messages: user chips (right-aligned, primary color), assistant messages (left-aligned, surface bg)
  - Tool indicators (pills showing which tool is being called)
  - Input: textarea with send button, disabled when rate limit reached
- **Tab 3 — SITREP:** Split layout
  - Left sidebar: Country/theme/date form + previous reports list
  - Right main: Welcome view → Pipeline progress (9.5 stages with animated steps) → Final report view
  - Pipeline stages: Connect → Load → Cluster → Questions → Filter → RAG Answers → Citations → Summaries → Executive Summary → Narrative → Assembly

### 3. Admin Tab (conditional, only for admin role)
- User management table (name, email, role, actions)
- Role change dropdown (free/premium/admin)

## Key UI Components

### Chat Welcome Screen
```
┌─────────────────────────────────────────┐
│          Welcome to ReliefAgent          │
│  Your AI-powered humanitarian data       │
│  analyst. Search, analyze, and synthesize │
│  reports from ReliefWeb.                 │
│                                          │
│  ┌──────────────────────────────────┐    │
│  │ 🔍 Search & Discover            │    │
│  │ Search ReliefWeb by country,    │    │
│  │ theme, org, disaster type...     │    │
│  └──────────────────────────────────┘    │
│  ┌──────────────────────────────────┐    │
│  │ 💬 Ask Questions                │    │
│  │ Natural-language Q&A with       │    │
│  │ cited answers from reports.     │    │
│  └──────────────────────────────────┘    │
│  ┌──────────────────────────────────┐    │
│  │ ⬇️ Ingest & Save                │    │
│  │ Fetch reports, paste URLs,      │    │
│  │ batch download to knowledge base.│    │
│  └──────────────────────────────────┘    │
│  ┌──────────────────────────────────┐    │
│  │ 📊 More Features                │    │
│  │ Database tab to browse reports. │    │
│  │ SITREP tab for automated reports│    │
│  └──────────────────────────────────┘    │
│                                          │
│  TRY ASKING:                             │
│  [🔍 Latest] [🌍 Country] [🏥 Theme]    │
│  [📋 Disaster] [💬 Ask] [📊 Summarize]  │
│  [⬇️ Fetch] [📎 URL] [📄 Report] [📑 MD] │
└─────────────────────────────────────────┘
```

### Rate Limit UX
- **User bar badge:** Shows "7/100" (remaining/limit), yellow at ≤3, red at 0
- **When limit reached:** Input locks (disabled, placeholder "Daily limit reached"), inline message in chat (no popup/toast)
- **Role badges:** ADMIN (red), PRO (purple), hidden for free

### SITREP Pipeline Progress
- 9.5 stages shown as a grid of step cards
- Each step: icon, name, status (pending → running ✓ → done ✓ or ✗)
- Running step has spinning animation
- Log output streams below the grid

## Design Principles

1. **Humanitarian feel** — Clean, professional, trustworthy. Red Cross red (#C8102E) as brand color. Navy (#0f1d36) for nav/sidebar.
2. **Data-dense but not cluttered** — Tables, stats, and chat should feel spacious with good hierarchy.
3. **Dark sidebar + light main** — SITREP sidebar and chat sidebar use navy background. Main content area is light (#f4f5f7).
4. **Consistent spacing** — Use 8px grid (8, 16, 24, 32, 48px).
5. **Smooth transitions** — All interactive elements have `transition: .2s cubic-bezier(.4,0,.2,1)`.
6. **Accessible** — Good contrast ratios, focus states, semantic HTML.
7. **Mobile responsive** — Sidebars become slide drawers on mobile.

## What to Generate

Please generate a complete, production-ready redesign of:

1. **`index.html`** — Full HTML structure with all 3 tabs + auth overlay + admin tab
2. **`style.css`** — Complete CSS with all components, responsive breakpoints, animations
3. **`app.js`** — Frontend logic (tab switching, chat, SITREP pipeline, database browsing, rate limits, auth state)
4. **`auth.js`** — Firebase Auth integration (Google Sign-In, token management, role checking, rate limit UI)

### Important Notes:
- Keep all existing API endpoints (`/api/agent/chat`, `/api/db/*`, `/api/sitrep/*`, `/api/auth/me`, `/api/admin/*`)
- Keep Firebase Auth flow (Google Sign-In popup)
- Keep SSE streaming for chat responses
- Keep SITREP pipeline SSE streaming
- The chat uses Server-Sent Events (SSE) for streaming responses
- Rate limit info comes from `/api/auth/me` response
- Role badges: ADMIN (red bg), PRO (purple bg), hidden for free users
- Quick prompt buttons have category colors: search (blue), kb (purple), ingest (green), analysis (amber)
- When rate limit is exhausted: input locks, no toast/popups, inline message in chat

## File Structure Reference

Current files to redesign:
- `templates/index.html` — Main HTML
- `static/style.css` — All styles
- `static/app.js` — Chat, SITREP, Database, Admin logic
- `static/auth.js` — Firebase Auth, role management, rate limit UI