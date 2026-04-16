# Releasing

This repository currently publishes release identity through Git tags and GitHub Releases. There is no in-code version constant to update, so the release checklist is mostly about docs, verification, tagging, and publishing from `main`.

## Release Principles

- Release from `main`.
- Keep public release notes in [`CHANGELOG.md`](CHANGELOG.md), not in private assistant notes.
- Do not tag a release that has not passed the current CI and the release checks below.

## Pre-release Checklist

1. Confirm the release commit is already on `main`, or that the current `main` state is the one you want to publish.
2. Update [`CHANGELOG.md`](CHANGELOG.md) so the release-facing changes are captured under `Unreleased`.
3. Check the public docs surface:
   - `README.md`
   - `README_EN.md`
   - `README_ES.md`
   - `README_PT.md`
   - `README_RU.md`
   - `README_JA.md`
   - `CONTRIBUTING.md`
   - `SUPPORT.md`
   - `SECURITY.md`
4. Confirm public docs stand on their own for installation, support, contribution, and release flow without relying on private assistant notes.
5. Run the minimum verification set from a clean working tree:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 ccsw.py list
python3 -m unittest discover -s tests -q
```

6. If the release touched bootstrap, command chaining, runtime lease behavior, overlays, or workflow/docs automation, also run:

```bash
python3 -m unittest -q tests.test_bootstrap tests.test_cli_smoke
```

7. Make sure GitHub Actions and CodeQL are green on the branch that will merge to `main`.

## Docs Consistency Check

The repository CI includes a lightweight docs check. Before tagging, either let that workflow pass on the release branch or mirror its intent locally: public docs should link the release docs, localized quickstarts should point back to the English reference plus support/security pages, and stale wording should be cleaned up before the tag is cut.
Also confirm that the public README variants still agree on the top-level product surface: hero banner, language links, primary install guidance, and public support/release links.

## Tagging And Publishing

After the release commit is on `main`, and the same commit range is green on `main` CI / CodeQL:

1. Choose the next version tag, for example `v0.1.0`.
2. Move the `CHANGELOG.md` contents you are shipping into a versioned section, or copy the relevant `Unreleased` notes into the GitHub Release body if you prefer to keep a rolling unreleased section.
3. Create an annotated tag:

```bash
git checkout main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

4. Draft the GitHub Release from that tag.
5. Use the matching `CHANGELOG.md` section as the release notes base.
6. Link the release back to the CI and CodeQL workflows if the release notes mention validation or automation changes.

## After Publishing

- Confirm the GitHub Release points at the correct tag on `main`.
- Check that README links to `CHANGELOG.md`, `RELEASING.md`, `SUPPORT.md`, and `SECURITY.md` still render correctly in the published repo view.
- If the release changed contributor expectations, update the issue templates or PR template in the same release train rather than leaving docs drift for later.
