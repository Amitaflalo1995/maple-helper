# Releasing Maple Helper

Everything runs in GitHub Actions. You decide *when*; CI does the rest.

| Workflow | Runs on | Does |
|---|---|---|
| **CI** (`ci.yml`) | every push to `main`, every PR | lint + tests, then a full Windows build: frozen-exe self-test, portable zip, installer install → self-test → uninstall. The build is downloadable from the run page (14 days). |
| **Release** (`release.yml`) | pushing a tag `vX.Y.Z` | the same checks with the real knowledge base bundled, then publishes the GitHub Release. Installed apps update themselves to it. |
| **Update knowledge base** (`kb-update.yml`) | nightly (changed pages), full refresh on Sundays, or the *Run workflow* button | scrapes NiaMeowDB politely, **validates**, and replaces `kb.zip` + `kb-manifest.json` on the latest release when content changed. |

## Cut a release

1. Bump `__version__` in `maplehelper/__init__.py`, commit, and merge to `main`.
2. Tag the merged commit and push the tag:
   ```powershell
   git switch main; git pull
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. Watch **Actions → Release**. When it's green, the release is live. Every installed copy downloads
   it in the background, checks its SHA-256 against `SHA256SUMS.txt`, and installs it when the player
   closes the app.

The release fails, and publishes nothing, when:
- the tag doesn't match `__version__`, or the tagged commit isn't on `main`,
- any lint rule, test, frozen-exe self-test or installer round trip fails,
- the knowledge base fails validation.

To retry after fixing: delete the tag (`git push --delete origin v0.2.0; git tag -d v0.2.0`), then tag again.

**Prereleases:** `v0.3.0-beta.1` (with `__version__ = "0.3.0"`) publishes a prerelease. GitHub never
marks it "latest", so the auto-updater and KB updates ignore it. Share its link with testers.

**First release:** with no earlier release to carry the KB forward from, the Release workflow scrapes
NiaMeowDB itself (about an hour), validates the result, and bundles it. `tools/release.py` on a PC with
`data/kb` also still works, and now publishes `SHA256SUMS.txt` too.

## What every release carries, and why

| Asset | Read by |
|---|---|
| `MapleHelper-Setup.exe` (unversioned name) | players, and the in-app auto-updater (`updater.download_app_update`) |
| `SHA256SUMS.txt` | the auto-updater: **no matching hash, no update** |
| `kb.zip` + `kb-manifest.json` | installed apps' KB updates (`releases/latest/download/kb-manifest.json`) |
| `MapleHelper-X.Y.Z-portable.zip` | players who don't want an installer |

Apps read these from whatever release is **latest**, so never publish a release by hand without them.
The Release workflow carries the current KB forward automatically.

## Roll back a bad release

The auto-updater only moves *forward* (it installs a release only when its version is higher). So
marking an older release "latest" stops new downloads of the bad one, but it **doesn't** downgrade
players who already have it. Fix forward:

1. On GitHub, edit the previous good release and tick **Set as the latest release** (this stops the spread right away).
2. Fix, bump to a **new** version (e.g. `0.2.1`), and release. Everyone, including players on the bad version, updates to it.

## Knowledge base

- Validation rejects a KB that has fewer than 500 entities, is missing one of the 11 categories, has
  index entries without pages, or lost more than 10% of the previous entity count. A rejected KB is
  never published, and players keep the previous one. The failed run shows why.
- Only real content changes are published (the scraper counts changed pages), so players don't
  re-download identical data.

## Owner setup (needs repository admin)

1. **Branch protection** on `main` (Settings → Branches): require a pull request and the status
   checks **`Test / Lint & test`** and **`Build & smoke test`** from CI.
2. **Code signing (optional; removes the SmartScreen warning, and recommended now that updates
   install silently):** add a repository secret `MAPLEHELPER_SIGN` holding a sign command with a
   `{file}` placeholder. The build then signs `Maple Helper.exe` and the installer. For example:
   `signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p <password> "{file}"`.
   Options for open-source apps: [SignPath Foundation](https://signpath.org) (free for OSS) or Azure Trusted Signing.

## Build locally

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
pwsh packaging\build.ps1 -KbDir tests\fixtures\kb -SkipInstaller   # fast; no Inno Setup needed
pwsh packaging\build.ps1 -RequireKb                                # with data\kb + Inno Setup 6
```

Output goes to `dist\release\`. Any build can check itself with
`"dist\Maple Helper\Maple Helper.exe" --selftest report.txt` (exit code 0 = healthy; the report says why not).
`-TestInstaller` really installs and uninstalls the app, so it only runs in CI unless you add `-Force`.

## README snippet

```markdown
[![CI](https://github.com/Amitaflalo1995/maple-helper/actions/workflows/ci.yml/badge.svg)](https://github.com/Amitaflalo1995/maple-helper/actions/workflows/ci.yml)

**[Download Maple Helper](https://github.com/Amitaflalo1995/maple-helper/releases/latest/download/MapleHelper-Setup.exe)** (Windows 10/11). It updates itself.
```
