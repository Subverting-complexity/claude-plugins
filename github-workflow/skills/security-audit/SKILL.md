---
name: security-audit
description: "Dedicated security audit of the codebase: dependency vulnerabilities, secrets detection, OWASP Top 10 checks, input validation, and auth review. Use when the user says 'security audit', 'check for vulnerabilities', 'find security issues', 'scan for secrets', 'is this secure', 'security review', 'pen test', 'threat model', or 'check dependencies for CVEs'. Also trigger on 'audit for security' or 'check for leaked credentials'. Do NOT use for general code review (use code-review) or architecture audits (use code-architect --mode audit)."
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(npm audit *)
  - Bash(npx *)
  - Bash(pip audit *)
  - Bash(pip-audit *)
  - Bash(cargo audit *)
  - Bash(go *)
  - Bash(dotnet list * --vulnerable)
  - Bash(gh *)
  - Bash(git *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Security Audit

Deep security-focused review of the codebase. This is not a general
code review — it specifically targets security vulnerabilities, leaked
secrets, and attack surface.

## Plain-English output

Everything you write for a person to read (each finding, its risk, and the summary) follows `_shared/wording-standard.md` and avoids `_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component, vulnerability class, or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

## Phase 1 — Scope

Determine what to audit.

1. **Detect the tech stack.** Read package manifests, build files, and
   project structure to identify languages, frameworks, and package
   managers.
2. **Identify the attack surface.** What takes external input? HTTP
   endpoints, CLI args, file uploads, WebSocket handlers, message
   queue consumers, database queries, environment variables from
   untrusted sources.
3. **Check for existing security config.** Look for `.npmrc`,
   `.snyk`, `dependabot.yml`, `.github/workflows/*security*`,
   `SECURITY.md`, CSP headers, CORS config.

## Phase 2 — Dependency Vulnerabilities

Scan dependencies for known CVEs.

Run the appropriate audit command for the detected package manager:

- **npm/pnpm/yarn:** `npm audit --json` or equivalent
- **Python:** `pip audit` or `pip-audit`
- **Rust:** `cargo audit`
- **Go:** `go list -m -json all` and check against vuln DB
- **C#/.NET:** `dotnet list package --vulnerable`

For each vulnerability found, record:
- Package name and version
- CVE ID and severity (critical/high/medium/low)
- Whether a fix version exists
- Whether the vulnerable code path is actually reachable

Skip low-severity vulnerabilities in dev-only dependencies unless
they affect the build pipeline.

## Phase 3 — Secrets Detection

Scan for hardcoded credentials, API keys, and tokens.

1. **Search for common patterns:**
   - API keys: strings matching `[A-Za-z0-9]{20,}` near keywords like
     `key`, `token`, `secret`, `password`, `credential`, `auth`
   - Connection strings with embedded passwords
   - Private keys (RSA, SSH, PGP headers)
   - JWT tokens (three base64 segments separated by dots)
   - AWS access keys (`AKIA...`)
   - Environment files committed to git (`.env`, `.env.local`)

2. **Check git history** for previously committed secrets:
   ```
   git log --all --diff-filter=A -- '*.env' '*.pem' '*.key' '*credentials*'
   ```

3. **Verify .gitignore coverage** for sensitive file patterns.

## Phase 4 — OWASP Top 10 Review

Check for the most common web application vulnerabilities:

1. **Injection** — SQL, NoSQL, OS command, LDAP. Search for string
   concatenation in queries, `exec()`, `eval()`, `system()` calls
   with user input.
2. **Broken Authentication** — Weak password policies, missing rate
   limiting on auth endpoints, session tokens in URLs, missing
   MFA support.
3. **Sensitive Data Exposure** — Unencrypted storage of PII, tokens
   in logs, verbose error messages in production, missing HTTPS
   redirects.
4. **XML External Entities (XXE)** — XML parsers accepting external
   entity references.
5. **Broken Access Control** — Missing authorization checks, IDOR
   vulnerabilities, privilege escalation paths.
6. **Security Misconfiguration** — Debug mode in production, default
   credentials, unnecessary features enabled, missing security
   headers.
7. **Cross-Site Scripting (XSS)** — Unescaped user input in HTML,
   `dangerouslySetInnerHTML`, `innerHTML` assignments.
8. **Insecure Deserialization** — Untrusted data passed to
   deserializers (pickle, Java serialization, JSON.parse of
   user-controlled class constructors).
9. **Known Vulnerabilities** — Covered in Phase 2.
10. **Insufficient Logging** — Missing audit logs for auth events,
    admin actions, and data access.

Focus on items 1, 3, 5, and 7 — they are the most commonly exploited.

## Phase 5 — Input Validation

For every external input identified in Phase 1:

1. Is it validated before use? (type, length, format, range)
2. Is it sanitized before output? (HTML encoding, SQL parameterization)
3. Are error messages safe? (no stack traces, no internal paths, no
   sensitive data in responses)
4. Are file uploads restricted? (type, size, content validation)

## Phase 6 — Report

Organize findings by severity:

**Critical** — Exploitable now, data at risk, or secrets exposed.
Fix immediately.

**High** — Exploitable with moderate effort or missing a key control.
Fix before next release.

**Medium** — Defense-in-depth gaps or best-practice violations.
Schedule for near-term fix.

**Low** — Informational findings or hardening recommendations.
Address opportunistically.

For each finding, include:
- File and line number
- What the vulnerability is
- How it could be exploited (attack scenario)
- Recommended fix

Do not make code changes during a security audit. Report findings only.
Use `/github-workflow:execute` or `/github-workflow:report-issue` to
address individual findings.
