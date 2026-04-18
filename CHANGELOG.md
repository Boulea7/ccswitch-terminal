# Changelog

All notable public, release-facing changes to this repository should be recorded here.

This project does not yet maintain an in-code version constant. Until that changes, release numbers live in Git tags and GitHub Releases, and this changelog tracks the public surface that ships with each release.

The format follows a simple Keep a Changelog style with `Added`, `Changed`, `Fixed`, and `Removed` sections when useful.

## Unreleased

## v0.1.0 - 2026-04-16

### Added

- Added a five-tool control plane for `Claude Code`, `Codex CLI`, `Gemini CLI`, `OpenCode`, and `OpenClaw`, including direct live-config writes for the first three and generated overlays for the latter two.
- Added higher-level CLI workflows: `profile`, `doctor`, `run`, `history`, `rollback`, `repair`, `settings`, and `import current`.
- Added persisted runtime lease / manifest tracking in SQLite `managed_targets` so stale `run` sessions can be diagnosed and repaired explicitly instead of being silently overwritten.
- Added subprocess-driven CLI smoke coverage, bootstrap shell-contract tests, and docs consistency checks alongside the existing unit coverage.
- Added [`RELEASING.md`](RELEASING.md) to document the release checklist, tagging flow, and GitHub release handoff.
- Added this `CHANGELOG.md` so public releases have a stable place for notes outside of internal agent docs.
- Added public repository health files and automation, including issue templates, PR template, CODEOWNERS, Dependabot, and CodeQL wiring.
- Added `opensource@lnzai.com` as a documented private security-reporting fallback when GitHub private advisories are unavailable.

### Changed

- Refreshed the public README set across all shipped languages so they now share the same banner/header treatment, clearer introductions, copy-paste install prompts for Claude Code / Codex, alias-first examples such as `openrouter -> op`, and folded sections for lower-priority details.
- Changed the repository to a public-release-oriented surface: private local assistant docs were removed from tracked files and from reachable git history, while local ignore rules still support keeping those files on the maintainer machine.
- Changed bootstrap to install one managed shell block that includes wrapper functions plus activation-file sourcing, and to better handle repeated installs, old rc snippets, and shell detection fallbacks.
- Changed Codex switching to use a custom `model_provider` block with `supports_websockets = false` instead of relying on legacy root-level `openai_base_url` guidance.
- Changed `run` to behave as a managed temporary fallback wrapper with persisted restore metadata rather than an implicit active-provider switch.
- Changed docs and examples to remove bundled relay-specific presets from the public release and keep provider examples generic.
- Unified public docs and workflow wording around the `main` branch.
- Linked release-facing docs from the main README, English README, localized quickstart READMEs, and community-health docs.
- Made localized quickstart READMEs explicitly describe themselves as consistent release-facing quickstart surfaces.

### Fixed

- Fixed bootstrap rc-file detection so installs prefer externally exported `SHELL` values and existing rc files instead of inferring from the bootstrap script's own shell process.
- Fixed stale-lease handling so unfinished or conflicting runtime scenes fail closed and can be repaired explicitly instead of being overwritten by later `run` calls.
- Fixed restore handling so post-restore local validation failures keep the stale lease and runtime artifacts available for `repair`.
- Fixed history/probe redaction to cover more auth-bearing fields and compact CLI credential forms such as `-uuser:pass`.
- Fixed snapshot/manifest decode failures so they scrub legacy inline snapshot payloads without leaving raw secret-bearing blobs around indefinitely.
- Fixed settings persistence for stores that only contain settings metadata after bundled preset removal.
- Fixed release test portability so shell/bootstrap coverage no longer assumes `/bin/zsh`, and Python 3.9 CI can import the shared test helpers again.
- Removed public contributor guidance that treated private assistant notes as part of the required external contribution flow.
- Replaced shell-detection examples with `command -v ...` in public docs.
- Reworded provider coverage examples so they describe a subset of supported tools instead of an arbitrary count.

### Removed

- Removed bundled relay-specific provider presets and relay-branded examples from the public release surface.
- Removed legacy default-branch wording from public GitHub workflow triggers. Public automation now speaks in terms of `main`.
