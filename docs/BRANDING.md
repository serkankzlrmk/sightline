# Sightline — Brand Guidelines

> **Sightline** — Intelligence for Humanitarian Action

## Brand Identity

| Element | Value |
|---------|-------|
| **Brand Name** | Sightline |
| **Tagline** | Intelligence for Humanitarian Action |
| **Domain** | `sightline.io` (target) |
| **Previous Names** | ReliefAgent, RedAgent, NovaSphere (deprecated) |

## Component Branding

| Component | Brand | Slogan |
|-----------|-------|--------|
| **Platform** | **Sightline** | Intelligence for Humanitarian Action |
| **Agent (Chat)** | **Sightline Agent** | Ask. Analyze. Act. |
| **SITREP** | **Sightline SITREP** | Data-Driven Situation Reports |
| **Bulletin** | **Sightline Bulletin** | Weekly Crisis Intelligence |
| **Database** | **Sightline Database** | Search. Discover. Understand. |
| **HDX** | **Sightline HDX** | Quantitative Humanitarian Data |
| **Admin** | **Sightline Admin** | Manage Users & Access |

## UI Text Standards

### Page Title
```
Sightline
```

### Login Page
```
Sightline
Intelligence for Humanitarian Action

[Sign in with Google]

© 2026 Sightline
```

### Sidebar
```
🔭 Sightline
```

### Chat Welcome
```
Welcome to Sightline
Your AI-powered humanitarian data analyst.
Message Sightline...
```

### SITREP Button
```
💬 Discuss with Sightline
```

### Agent Identity (System Prompt)
```
You are Sightline — a specialized humanitarian data analyst.
```

### Startup Banner
```
Tabs : Database | Sightline | SITREP
```

## Deployment Naming

| Old | New |
|-----|-----|
| `/opt/reliefagent` | `/opt/sightline` |
| `reliefagent` (user/service) | `sightline` |
| `/var/log/reliefagent` | `/var/log/sightline` |
| `reliefagent.service` | `sightline.service` |
| `YOUR_DOMAIN` | `sightline.duckdns.org` |
| `redagent_platform` | `sightline_platform` |
| `novasphere_platform` | `sightline_platform` |

## Preserved (Do NOT Change)

| Item | Value | Reason |
|------|-------|--------|
| Firebase Project ID | `YOUR_PROJECT_ID` | Requires new Firebase project |
| ReliefWeb API Appname | `RELIEFWEB_APPNAME_PLACEHOLDER` | Approved by ReliefWeb |
| GitHub Repo URL | `github.com/serkankzlrmk/RedAgent.git` | Rename separately on GitHub |

## Brand Colors (Future)

| Role | Color | Hex |
|------|-------|-----|
| Primary | Deep Blue | `#1e40af` |
| Accent | Teal | `#0d9488` |
| Alert | Amber | `#f59e0b` |
| Danger | Red | `#dc2626` |
| Success | Green | `#059669` |
| Background | Slate | `#0f172a` |

## Logo Concept

🔭 (Telescope icon) — representing "sight" + "line of sight" to humanitarian data.

The telescope metaphor captures:
- **Sight**: Seeing, observing, understanding humanitarian crises
- **Line**: Direction, focus, clear line of sight to data
- **Horizon**: Looking forward, anticipating needs

## Voice & Tone

- **Professional** but approachable
- **Data-driven** but human-centered
- **Authoritative** but not bureaucratic
- **Clear** and concise — no jargon without explanation
- **Citation-first** — every claim backed by sources

## Naming Rules

1. Always use **Sightline** (not "SightLine", "Sight Line", or "sightline" at sentence start)
2. Component names: **Sightline Agent**, **Sightline SITREP**, etc. (not "SightlineAgent")
3. In code: `sightline` (lowercase) for paths, users, services
4. In UI: **Sightline** (title case) for display text
5. In agent prompts: **Sightline** (title case) for identity