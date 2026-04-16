# Contributing

## Before You Start

- Read [`README.md`](README.md) or [`README_EN.md`](README_EN.md) first.
- Check [`CHANGELOG.md`](CHANGELOG.md) for release-facing changes and [`RELEASING.md`](RELEASING.md) if your change affects the public release process.
- Install any managed CLI you plan to exercise locally before testing it with `doctor`, `switch`, or `run`.
- Use the GitHub issue templates when reporting bugs or requesting features.
- Open an issue or discussion before large behavior changes.
- Keep the CLI surface compatible unless the change is explicitly intended.

## Development Workflow

1. Create a feature branch.
2. Make focused changes.
3. Add or update automated tests for every behavior change.
4. Run the verification commands below.
5. Open a pull request with a concise summary, verification notes, and any risks. The repository PR template already asks for exactly that information.

## Verification

Run the minimum suite:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 -m unittest discover -s tests -q
```

For CLI-level changes, also run:

```bash
python3 -m unittest -q tests.test_bootstrap tests.test_cli_smoke
```

If your change only touches docs, community-health files, or workflow metadata, you can usually skip the unittest suite and instead verify the affected docs/examples plus any changed workflow files. Be explicit in the PR about what you did and did not run.

For docs-only changes to the public repo surface, run the lightweight docs consistency workflow locally where practical, or mirror its checks before opening the PR: public docs should link the release docs, keep localized quickstarts aligned, and avoid stale wording.
When the README surface changes, keep the visible top structure aligned across all public README variants: banner, language switcher, primary install path, and links to support / security / release docs.

## Coding Guidelines

- Keep implementations simple and fail closed on ambiguous state.
- Prefer reusing existing helpers over adding parallel logic.
- Treat docs as product surface: update `README*.md`, `CHANGELOG.md`, `RELEASING.md`, and relevant `.github` templates/workflows when public behavior changes.
- Document `doctor --json` as newline-delimited JSON with one payload per tool, not as a single wrapped document.
- When writing shell examples, make it explicit that generated `~/.ccswitch/*.env` files are POSIX shell snippets; non-POSIX shells should translate the emitted exports instead of sourcing those files directly.
- Use env refs by default for secrets. Avoid introducing new plaintext-secret storage paths.
- Keep community-health files and automation simple: issue/PR templates, CODEOWNERS, Dependabot, CI, and CodeQL should stay easy to audit.

## Pull Request Notes

Please include:

- what changed
- why it changed
- exact verification commands you ran
- any remaining risks or follow-up work
- whether `CHANGELOG.md` or `RELEASING.md` needed updates
