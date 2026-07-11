# Stitch Prompt — Sightline Login Screen

> **Scope:** Sadece giriş ekranı (auth-overlay veya tam sayfa login). Ana uygulama arayüzü değil.  
> **Stitch'e ver:** Bu dosyanın tamamını prompt olarak yapıştır, ardından "Generate the login screen for Sightline" de.

---

## Context & Intent

Design a standalone **login / authentication screen** for **Sightline** — a professional humanitarian data intelligence platform used by UN agencies, NGOs, and field coordinators to track global crises. The screen must feel like it belongs between Apple.com and a premium SaaS tool — not a generic B2B login page, not a fintech dark theme, not a purple-gradient AI product.

The user landing on this screen is **an experienced professional**, not a consumer. They've been invited or approved for access. The screen should feel like unlocking something serious and trusted — not exciting, not playful. Calm authority.

**One job: get them signed in, beautifully.**

---

## 1. Visual Theme & Atmosphere

**Atmosphere:** Restrained liquid clarity. Think Apple's product pages crossed with a premium data terminal — soft, controlled light with a single purposeful focal point. Not dark. Not frosted glass cliché. Warm off-white light with one structural data visualization element breathing quietly in the background.

- **Density:** 2 / 10 — Art Gallery Airy. The login card is the only element that matters.
- **Variance:** 5 / 10 — Slightly asymmetric. Not centered-centered. Card sits at 52% vertical, 48% horizontal. Background geometry is subtly offset.
- **Motion:** 6 / 10 — Fluid, hardware-accelerated. Background breathes (not loops visibly). Card entrance is spring-weighted. No particles, no confetti.

**Mood words:** Quiet authority. Institutional clarity. Field-tested. Trusted infrastructure. A briefing room, not a startup landing page.

**What it is NOT:** 
- Not a dark cyberpunk terminal
- Not a purple AI gradient 
- Not a centered card on a stock photo
- Not glassmorphism with blur-everything
- Not a warm coffee-shop SaaS vibe

---

## 2. Color Palette & Roles

The palette is a warm neutral system with a **single, controlled crimson-red accent**. The red is not aggressive — it anchors the brand without shouting.

| Name | Hex | Role |
|---|---|---|
| **Warm Canvas** | `#F5F5F7` | Full-screen background — Apple's signature warm off-white, never pure white |
| **Pure Surface** | `#FFFFFF` | Login card background — floating above canvas |
| **Charcoal Ink** | `#1D1D1F` | Primary headlines, button text — Apple's dark text, never pure black |
| **Steel Gray** | `#6E6E73` | Subheadings, helper text, legal/copyright line |
| **Dust Line** | `rgba(0, 0, 0, 0.08)` | Card border, divider lines — almost invisible, structural only |
| **Sightline Red** | `#E8364E` | Single brand accent: logo mark, primary button fill, focus rings |
| **Red Tint** | `rgba(232, 54, 78, 0.06)` | Subtle button hover state background wash |
| **Red Glow** | `rgba(232, 54, 78, 0.15)` | Focus ring shadow, logo ambient glow |
| **Data Ink** | `rgba(29, 29, 31, 0.04)` | Background geometry lines — barely visible grid/mesh |

**Strictly banned colors:**
- No `#7C3AED`, no purple of any shade
- No neon blue `#00D4FF` or cyan
- No green gradients
- No `#000000` pure black
- No warm amber/orange — this is not a startup

---

## 3. Typography Rules

**Font Stack:**

- **Display / Wordmark:** `Outfit` weight 600 — tracking `-0.04em`, size `2rem`. This is the "Sightline" logotype rendered in code.
- **Tagline:** `Outfit` weight 400 — `1rem`, tracking `0.08em` uppercase. Color: Steel Gray `#6E6E73`. The tagline is `INTELLIGENCE FOR HUMANITARIAN ACTION`.
- **Card Headline (if any):** `Outfit` weight 500, `1.125rem`, Charcoal Ink.
- **Body / Helper:** `Outfit` weight 400, `0.875rem`, Steel Gray.
- **Metadata / Legal:** `Outfit` weight 400, `0.75rem`, Steel Gray 50% opacity.
- **Data numbers in background:** `JetBrains Mono` weight 400 — used only in the ambient background geometry visualization, not on the card.

**Typography bans:**
- `Inter` — banned
- Any system serif (Times New Roman, Georgia) — banned
- `font-size` below `12px` for any readable text — banned
- ALL CAPS headings on the card — banned (tagline is the only caps element)
- Gradient text on the logo — banned

---

## 4. Background Design

The background is not a photo. It is not a gradient from purple to blue. It is a **data visualization artifact** — a ghost of the platform's purpose, rendered so lightly it barely exists.

**Background composition:**

A subtle, full-screen **globe or world-map mesh** rendered as extremely fine lines (`stroke: rgba(29,29,31,0.05)`, `stroke-width: 0.5px`). The mesh is not decorative — it references the geographic nature of humanitarian data. Think: faint latitude/longitude grid lines, or a very light Delaunay triangulation of world crisis coordinates.

The mesh is animated: a very slow, continuous, barely perceptible **breathing rotation** over 120 seconds, linear timing, will-change: transform. The motion is so slow you only notice it if you stare.

**No:**
- No blob shapes
- No floating gradient orbs
- No particle systems
- No animated gradient backgrounds
- No stock photos

---

## 5. Login Card Design

The card is the single focal point. It is centered on the page (52% from top, centered horizontally). It is **not full-bleed on desktop** — it is a floating object.

**Card dimensions:** `420px` wide, auto height. On mobile: `calc(100vw - 48px)`, max `380px`.

**Card shape:** `border-radius: 20px`. Generously rounded.

**Card elevation:**
```
box-shadow: 
  0 0 0 1px rgba(0,0,0,0.06),
  0 8px 32px rgba(0,0,0,0.06),
  0 24px 64px rgba(0,0,0,0.04);
```
No colored shadows. No red glow on the card itself. The card is calm.

**Card background:** Pure white `#FFFFFF`.

---

### 5.1 Card Interior Layout (top to bottom)

**Internal padding:** `40px` on all sides on desktop, `32px` on mobile.

**Stack (vertical, centered):**

```
[Top section]
  Logo mark (telescope SVG, 32×32, Sightline Red #E8364E)
  — 12px gap —
  Wordmark: "Sightline"
    Outfit 600, 1.75rem, #1D1D1F, tracking -0.03em
  — 6px gap —
  Tagline: "INTELLIGENCE FOR HUMANITARIAN ACTION"
    Outfit 400, 0.6875rem, #6E6E73, tracking 0.1em, uppercase

— 32px margin —
[Divider]
  1px horizontal rule, rgba(0,0,0,0.07)
— 32px margin —

[Access gate text]
  "Sign in to continue"
  Outfit 500, 0.9375rem, #1D1D1F, centered
  
  — 8px gap —
  
  "Access is by invitation. Your account is reviewed before activation."
  Outfit 400, 0.8125rem, #6E6E73, centered, max 34ch line length

— 24px gap —
[CTA Button]
  Google Sign-In button (see Section 5.2)

— 24px gap —
[Footer]
  "© 2026 Sightline · Humanitarian Data Intelligence"
  Outfit 400, 0.6875rem, rgba(110,110,115,0.6), centered
```

---

### 5.2 Google Sign-In Button

**Style:**
- Width: `100%`
- Height: `48px`
- `border-radius: 12px`
- Background: `#1D1D1F` (Charcoal Ink — dark button, not red)
- Text: `#FFFFFF`, Outfit 500, `0.9375rem`, tracking `-0.01em`
- Left-aligned Google logo SVG (monochrome white), `20×20`, `16px` from left edge
- Text: `"Continue with Google"` — centered in remaining space

**Rationale for dark button:** The red accent is already used by the logo. A red CTA button would fight it. The dark button is calm, Apple-like, and reads as the primary action without competition.

**Hover state:**
- Background: `#2D2D2F`
- `transform: translateY(-1px)`
- `box-shadow: 0 4px 16px rgba(0,0,0,0.16)`
- Transition: `150ms cubic-bezier(0.4, 0, 0.2, 1)`

**Active / pressed state:**
- `transform: translateY(0px) scale(0.98)` — tactile push-down
- `box-shadow: none`

**Loading state (after click):**
- Button text disappears
- A thin horizontal progress line at the button's bottom edge: `height: 2px`, `background: #E8364E`, animated `0% → 70%` width over `2s ease-out`
- No circular spinner

---

## 6. Logo Mark

The logo is a **telescope icon** — stroke-based SVG, not filled.

**SVG spec:**
- `32×32` viewBox
- `stroke: #E8364E`
- `stroke-width: 1.75`
- `fill: none`
- `stroke-linecap: round`
- `stroke-linejoin: round`

**Concept geometry:** A minimal telescope: a long diagonal barrel (rectangle rotated ~35 degrees), an eyepiece cap on the right end, and a small mount suggestion at the bottom. Reads as a telescope at 32px. 4-5 paths maximum.

**Ambient glow (only glow in the design):**
```css
filter: drop-shadow(0 0 12px rgba(232, 54, 78, 0.20));
```

---

## 7. Page-Level Layout & Spacing

**Full screen:** `min-height: 100dvh` (never `100vh` — iOS Safari jump bug).

**Card positioning:**
```css
display: flex;
align-items: center;
justify-content: center;
padding: 24px;
```

No absolute positioning. No transform translate tricks. Pure flexbox center.

---

## 8. Motion & Entrance Animation

**Card entrance (on page load):**
```css
@keyframes cardReveal {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.98);
    filter: blur(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}
.login-card {
  animation: cardReveal 600ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
```

Spring-weighted easing (slight overshoot, then settle) — the signature Apple pop on arrival.

**Staggered interior reveal:**
- Logo mark: delay `100ms`
- Wordmark: delay `150ms`
- Tagline: delay `200ms`
- Divider: delay `250ms`
- Body text: delay `300ms`
- Button: delay `380ms`

Each element: `opacity: 0 → 1`, `translateY: 6px → 0`, duration `400ms`, ease-out.

**Background mesh:** Fades in over `800ms` starting `200ms` delayed. Slow rotation starts immediately.

**No:**
- No confetti on login success
- No animated gradient border on the card
- No typewriter effect on the tagline

---

## 9. Error State

If sign-in fails, show a single line below the button:

`"Sign-in was cancelled or failed. Try again."`
- Outfit 400, `0.8125rem`, `#E8364E`
- `opacity: 0 → 1` over `200ms`
- Disappears when user clicks button again
- No red border. No red background flash.

---

## 10. Responsive Behavior

| Viewport | Card width | Padding |
|---|---|---|
| Desktop (≥ 768px) | `420px` | `40px` |
| Tablet (480–768px) | `calc(100vw - 64px)` max `400px` | `32px` |
| Mobile (< 480px) | `calc(100vw - 32px)` max `360px` | `28px 24px` |

Mobile extras: wordmark `1.5rem`, button height `52px`, background mesh reduced opacity.

---

## 11. Anti-Patterns — Strictly Banned

- No purple, violet, or indigo in any shade
- No animated gradient background
- No glassmorphism / `backdrop-filter: blur()` on the card
- No "3-feature-cards" list inside the login card
- No stock photography or hero images
- No emoji anywhere
- No `Inter` font
- No pure `#000000` black
- No outer glow or neon shadow on the card
- No animated blob/orb shapes
- No "Don't have an account? Sign up" link
- No "Forgot password?" link
- No social proof ("Trusted by 500+ NGOs")
- No "Powered by AI" anywhere
- No circular loading spinner
- No gradient text on "Sightline" wordmark
- No hero illustration (flat SVG of people/computers)
- No `box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.3)` purple focus ring

---

## 12. Implementation Notes for Stitch

1. **Single HTML file** — no external component dependencies
2. **CSS custom properties** at `:root` level
3. **SVG logo** inline in HTML — not an `<img>` tag
4. **Google Sign-In button** shows static design; event hook is `id="google-signin-btn"`
5. **Background mesh** as inline `<svg>` with `<pattern>` element, or CSS repeating-gradient
6. **Font import:** `@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&family=JetBrains+Mono:wght@400&display=swap');`
7. **No Tailwind** — pure CSS only
8. **No external icon libraries** — all SVGs inline

---

## 13. Final Quality Bar

Before accepting the output:

- [ ] Can you tell immediately this is NOT a generic SaaS login?
- [ ] Is the red used in exactly one place on the card? (Logo mark only)
- [ ] Does the button look Apple-like, not Material Design?
- [ ] Is the background interesting without being distracting?
- [ ] Is the tagline readable? (Small — check contrast)
- [ ] Does the entrance animation feel weighted and purposeful, not bouncy?
- [ ] Would an OCHA field coordinator trust this screen?
