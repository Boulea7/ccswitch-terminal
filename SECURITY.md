# Security Policy

## Supported Scope

Please report issues related to:

- secret handling
- provider switching safety
- runtime lease / restore behavior that can corrupt live config
- unintended credential exposure in history, probe cache, generated files, or activation env files

## Private Reporting Path

Do **not** open a public issue for an active vulnerability or a report that contains sensitive material.

Use one of these private reporting paths:

- <https://github.com/Boulea7/ccswitch-terminal/security/advisories/new>
- <mailto:opensource@lnzai.com>

Recommended order:

1. Use GitHub Security Advisories private reporting when it is available to you.
2. If you cannot use GitHub private advisories, email `opensource@lnzai.com`.
3. Only fall back to a public issue when both private channels are unavailable, and remove all sensitive details first.

Include:

- affected version, commit, or branch
- whether the report applies to `main` only or to an already published release noted in [`CHANGELOG.md`](CHANGELOG.md)
- reproduction steps
- impact and attacker prerequisites
- sanitized logs, screenshots, or temp-home artifacts
- whether the issue requires a managed CLI to already be installed

If you report by email, include `[security]` in the subject line and provide the same sanitized reproduction details listed below.

If private advisories are unavailable from your account and email is not possible, open a public issue with sensitive details removed and explicitly say that a private security follow-up is needed.

GitHub CodeQL is enabled for this repository, but automated alerts are only an additional signal. They are not a substitute for a private security report when you have a real exploit path or sensitive reproduction details.

## Response Window

- Initial acknowledgement target: within 3 business days
- Reproducibility / severity follow-up target: within 7 calendar days after acknowledgement
- Status updates target: at least every 14 calendar days until the issue is resolved or a mitigation is published

These are response targets, not guarantees of a fixed release date.

## Safe Disclosure Notes

- Never include real API keys, tokens, cookies, session exports, or auth-bearing URLs in reports.
- Prefer reproductions that use temp directories, fake homes, and test tokens.
- If the issue depends on generated `~/.ccswitch/*.env` files, describe the shell and whether it is POSIX-compatible.
