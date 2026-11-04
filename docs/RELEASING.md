# Releasing

A release is a version number, a tag and a GitHub Release. Plugin installs only update when the version number goes up, so every change that users should receive needs a bump.

## Steps
1. **Branch** from `main`.
2. **Bump the version in three places, together.** `tests/test_plugin.py` fails if they differ:
   - `HARNESS_VERSION` in `scripts/common.py`
   - `version` in `.claude-plugin/plugin.json`
   - the plugin's `version` in `.claude-plugin/marketplace.json`
3. **Update `CHANGELOG.md`.** Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty `## [Unreleased]` above it, and fix the compare links at the bottom. The release workflow publishes exactly this section as the release notes.
4. **Open a pull request to `main`.** Merge only when CI is green on macOS, Windows and Linux.
5. **Tag the merge commit** and push the tag:
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
6. **GitHub Release.** Pushing the tag runs `.github/workflows/release.yml`. It checks that the tag equals the version in `plugin.json`, extracts the `## [X.Y.Z]` section of `CHANGELOG.md` and creates the GitHub Release with it as the body. If the tag and the version differ, or the section is missing, the workflow fails and nothing is published: delete the tag, fix, and tag again.

## Choosing the number (below 1.0)
- Patch (`0.1.1` to `0.1.2`): fixes and small panel changes.
- Minor (`0.1.x` to `0.2.0`): new features, new sources, anything that changes behaviour.
- Never reuse a published tag. If a release is wrong, ship a new patch.

## After the release
Users update with `claude plugin marketplace update 100founts` and `claude plugin update job-harness@100founts` (or the desktop app's plugin list). Clone users run `git pull`.
