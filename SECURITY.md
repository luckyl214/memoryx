# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.1.x   | ✅ Yes |
| < 1.1   | ❌ No |

## Reporting a Vulnerability

Please do **not** open a public issue for security vulnerabilities.

Use GitHub private vulnerability reporting if enabled, or email:
your_email@example.com

Include:
- Affected version or commit SHA
- Steps to reproduce
- Impact assessment
- Suggested fix, if available

We aim to acknowledge reports within 7 days and provide a fix timeline within 14 days.

## Security Design

- All REST endpoints require `X-MemoryX-API-Key` when `MEMORYX_API_KEY` is set
- API key comparison uses `secrets.compare_digest` to prevent timing attacks
- Rate limiting via sliding window prevents brute-force on search endpoints
- PII filter detects and anonymizes emails, phones, credit cards, API keys on write
- `.env` and `.env.local` are excluded from git via `.gitignore`
- `BEGIN IMMEDIATE` ensures atomic writes for memory + version + audit
