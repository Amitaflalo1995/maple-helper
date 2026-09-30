# CI/CD and public releases — design

Date: 2026-09-30 · Status: approved

## Goal

Every push and pull request is linted and tested. Pushing a version tag builds the
Windows app, proves the built executable runs, and publishes a GitHub Release that
players can download. Knowledge-base (KB) updates keep reaching installed apps
across releases. The app tells players when a newer version exists.

## Decisions

| Topic | Decision |
|---|---|
| Distribution | Inno Setup installer (per-user, no admin) + portable zip, both per release |
| Versioning | `maplehelper.__version__` is the source of truth; pushing tag `vX.Y.Z` releases; the tag must match |
| Prereleases | Tags containing `-` (e.g. `v0.3.0-beta.1`) publish as prereleases, which never become "latest" |
| KB | Built in CI by the polite scraper: manual button + monthly schedule |
| App updates | Notify-only: toast once per new version + tray entry, both open the release page |
| Signing | Unsigned for now; a signing step activates when signing secrets exist |
| CI platform | GitHub Actions, `windows-latest` (Qt glyph tests and the app are Windows-only) |

## Invariant: KB assets live on the latest release

`updater.py` reads `releases/latest/download/kb-manifest.json`. Therefore every release
that can become "latest" carries `kb.zip` + `kb-manifest.json`:

- The release workflow copies them forward from the current latest release, and
  rewrites the manifest URL to its own tag.
- The KB refresh workflow uploads them onto the current latest release (`--clobber`).
- There is never a separate KB-only release, except the very first bootstrap release,
  which the first app tag then fills with the installer.

## Workflows

- `test.yml` (reusable): ruff + pytest on Windows. Every other workflow calls it.
- `ci.yml` (push, pull request): tests, then a build job: PyInstaller build, `--selftest`
  of the frozen exe, portable zip and installer, uploaded as workflow artifacts.
  If no published KB exists yet, the build bundles the test fixture KB.
- `release.yml` (tag `v*`): verify tag == `__version__` → tests → fetch the KB from the
  latest release → validate it → build with the KB bundled → self-test → installer
  → silent install/self-test/uninstall → sign if configured → publish the release with
  `SHA256SUMS.txt` and generated notes → re-download the published assets and verify
  their hashes.
- `kb-refresh.yml` (monthly + manual, optional full `refresh`): tests → restore the
  previous KB (the scraper resumes, so only new pages are fetched) → scrape →
  validate → pack → upload to the latest release. Validation failure publishes nothing.

Release and KB workflows share a concurrency group so they never race on assets.

## Tests

- Unit: `brain` (META parsing, stated level, error classification, prompt assembly),
  `store` (settings, profile updates, history), `kb` (lookup, Hebrew prefixes,
  aliases, level digest), `updater` (newer/older/same, hash mismatch, bad zip,
  offline, existing KB preserved), `i18n` (he/en parity, placeholders),
  `app_update` (version compare, prereleases, offline), `kb_release` (validate, pack,
  retarget).
- Existing Qt glyph tests (`test_bidi.py`).
- `tests/conftest.py` points `APPDATA` at a temp dir before importing the app.
- A fixture KB in `tests/fixtures/kb`.
- Frozen smoke test: `MapleHelper.exe --selftest=<file>` imports every runtime module
  (faster_whisper, ctranslate2, keyring, sounddevice, mss, PIL), loads fonts and the
  bundled KB, creates the Qt app offscreen, writes a report, and exits 0/1. No console
  exists in a windowed build, so the result travels by exit code and file.
- CI never calls the network, Claude, or meowdb.com (except the KB workflow's scrape).

## Packaging

- `packaging/maplehelper.spec`: onedir build, windowed, icon, Windows version
  resource from `__version__`, bundles `assets/` and `data/kb/`.
- `packaging/installer.iss`: fixed AppId (in-place upgrades), `{localappdata}\Programs`,
  Start Menu shortcut, optional desktop icon, Hebrew + English UI, closes the running
  app, leaves `%APPDATA%\MapleHelper` on uninstall.
- `packaging/build.ps1`: one script used by CI and locally: build → self-test → zip → installer.
- `tools/kb_release.py`: `validate`, `pack` (stamps the version into `meta.json`, writes
  `kb.zip` + manifest), `retarget` (rewrites the manifest URL for a tag). A tracked
  `data/aliases.json` (hand-curated Hebrew aliases) is merged into the pack when present.

## App update notice

- `maplehelper/app_update.py`: `latest_release()` via the GitHub API, numeric version
  compare, ignores prereleases/drafts, returns None on any failure.
- `GITHUB_REPO` lives in `maplehelper/__init__.py`, shared with `updater.py`.
- Toast gains an `on_click`. The `update_notified` setting records the version already announced.

## Owner setup (needs repo admin)

Branch protection requiring the `CI` checks. Optional signing secrets. See `docs/RELEASING.md`.

## Revision (same day): rebased onto the owner's packaging

While this was being built, `main` gained the owner's own packaging (PyInstaller spec, Inno Setup
installer, silent self-update, `tools/release.py`, nightly `kb-update.yml`). Decision: adopt theirs
and add what was missing, instead of shipping a second, competing pipeline. Changes to the design above:

- **Packaging:** the owner's spec, installer, AppId, exe name (`Maple Helper.exe`) and asset names
  (`MapleHelper-Setup.exe`, unversioned, because the updater looks it up by name) are kept. The spec
  only gained `$MAPLEHELPER_KB`.
- **App updates:** the owner's silent download-and-install replaces the notify-only design.
  The installer now runs only when its SHA-256 matches the release's `SHA256SUMS.txt`
  (it used to be a size check). The notify-only module was dropped.
- **KB:** the owner's nightly `kb-update.yml` (changed pages, Sunday full refresh) replaces the monthly
  workflow, with a validation gate added before publishing. The manifest URL convention stays
  `latest/download/kb.zip`, so carrying the KB forward needs no retargeting, and there is no bootstrap release:
  the first CI release scrapes the KB itself.
- **Self-test:** it replaces the owner's `--selftest`, which always exited 0 and treated "no microphone"
  as an error. It keeps the same CLI (`--selftest <file>`).
- **Fixes found on the way:** `QTimer.singleShot` from worker threads never fires (the KB-reload and
  update toasts never showed); `update_kb` crashed on a manifest without `url` or on a corrupt zip.
- Python 3.13 in CI (matches the verified local build).
- The GitHub conda starter workflow (always failing: no `environment.yml`, Linux) is replaced by `ci.yml`.
