# Security Policy

## Reporting a Vulnerability

The Sightline maintainer takes security bugs seriously. We appreciate your
efforts to responsibly disclose your findings, and will make every effort to
acknowledge your contributions.

### How to Report

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities privately:

1. **Email:** See [GitHub Security Advisories](https://github.com/serkankzlrmk/sightline/security) (preferred)
2. **Subject line:** `[SECURITY] Sightline — <short description>`
3. **Include in your report:**
   - Description of the vulnerability and its potential impact
   - Steps to reproduce (proof of concept if possible)
   - Affected versions (commit hash or release tag)
   - Any suggested mitigations or fixes

You should receive an acknowledgment within **72 hours**. If you do not receive
an acknowledgment within that time, please follow up by email.

### Response Timeline

| Step | Target |
|---|---|
| Acknowledge receipt | Within 72 hours |
| Initial assessment (valid/invalid) | Within 7 days |
| Fix development (if valid) | Within 30 days (critical: 7 days) |
| Public disclosure (after fix released) | Within 90 days of initial report, or per coordinated disclosure with reporter |

### Disclosure Policy

- We follow **coordinated disclosure**. We will not disclose a vulnerability
  publicly until a fix is available, unless the reporter agrees otherwise.
- We will credit the reporter in the release notes / security advisory, unless
  they prefer to remain anonymous.
- We request that reporters do not publicly disclose the vulnerability until a
  fix is available, or until 90 days have passed since the initial report
  (whichever comes first).

---

## Supported Versions

Sightline is pre-1.0 software. Security fixes are applied only to the latest
release on the `main` branch. No backports to older versions are provided.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| Older releases | ❌ |

---

## Security Measures Already in Place

Sightline has been hardened with the following measures (as of the current
release):

- **Authentication:** Firebase Auth + role-based access control (RBAC)
  (`require_auth`, `require_admin`, `require_role`, `optional_auth`).
- **Dev mode:** Local-only bypass (`DEV_AUTH_BYPASS=true` + `SERVER_HOST=127.0.0.1`).
  Blocked on `0.0.0.0` and public IPs.
- **Rate limiting:** Per-IP request limits + role-aware message limits.
- **Path traversal protection:** `Path.is_relative_to()` containment on all
  file-serving endpoints.
- **XSS protection:** `sanitizeHtml(md(...))` for chat output, `esc()` with
  single-quote escape for all dynamic HTML.
- **CSP:** `object-src 'none'; base-uri 'self'; form-action 'self'` plus
  HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy.
- **SQL injection:** SQL query tool is read-only (`SELECT` only) with a 5-second
  timeout.
- **Upload security:** `%PDF-` magic byte check + `secure_filename`.
- **Error sanitization:** Generic error messages to clients, details in server
  logs only.
- **Stream auth:** SITREP stream uses single-use nonce (not JWT in URL), bound
  to `(uid, job_id)` with 5-minute TTL.
- **Test coverage:** 200+ tests, including security tests (path traversal, dev
  mode safety, stream nonce).

---

## Scope

### In Scope

- Security vulnerabilities in the Sightline application code (Python, JavaScript).
- Authentication / authorization bypasses.
- Server-side request forgery, injection (SQL, command, XSS).
- Path traversal, file disclosure.
- Sensitive data exposure (API keys, credentials, PII).
- Security-relevant misconfigurations (CSP, CORS, cookies).

### Out of Scope

- Vulnerabilities in third-party dependencies (report to the upstream project).
- Vulnerabilities in the underlying infrastructure (OS, Docker, Node.js,
  Python runtime).
- Social engineering, phishing.
- Denial of service via volume (we have rate limiting; DoS resilience is
  best-effort, not a security guarantee).
- Theoretical issues without a working proof of concept.
- Issues requiring physical access to the server or user's machine.
- Bugs in the LLM agent's tool-calling behavior that do not have a security
  impact.

---

## Bug Bounty

Sightline is a pre-revenue open-source project and does not currently offer a
monetary bug bounty. We genuinely appreciate responsible disclosure and will
credit reporters in release notes.

(If you would like to sponsor a bug bounty fund, please contact the maintainer.)

---

## Contact

- **Security reports:** [GitHub Security Advisories](https://github.com/serkankzlrmk/sightline/security) (preferred)
- **General questions:** open a [GitHub Discussion](https://github.com/serkankzlrmk/sightline/discussions)

---

_Sightline Security Policy v1.0_
