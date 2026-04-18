# Support

## Where To Ask

- Release notes and rollout changes: check [`CHANGELOG.md`](CHANGELOG.md) and [`RELEASING.md`](RELEASING.md) first.
- Usage questions: start from the issue chooser and use the closest template, then include the command you ran, the expected result, and the actual result.
- Bug reports: use the bug-report template and include exact verification steps plus a sanitized reproduction.
- Feature ideas: use the feature-request template and describe the workflow problem first, then the proposed command or behavior.

## What Helps Most

Please include:

- OS and shell
- Python version
- relevant `ccsw` command
- whether you used `bootstrap.sh` or `python3 ccsw.py ...`
- sanitized stderr/stdout
- whether the issue reproduces in an isolated temp home

## Before Opening An Issue

Try these first:

```bash
bash bootstrap.sh --dry-run
python3 ccsw.py -h
python3 ccsw.py list
python3 ccsw.py show
python3 -m unittest discover -s tests -q
```

For CLI-chain regressions, also run:

```bash
python3 -m unittest -q tests.test_bootstrap tests.test_cli_smoke
```

For docs or release-related confusion, also check:

- [`README.md`](README.md) or [`README_EN.md`](README_EN.md)
- [`CHANGELOG.md`](CHANGELOG.md)
- [`RELEASING.md`](RELEASING.md)
