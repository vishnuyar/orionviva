# Releasing OrionViva Desktop

Desktop releases are built by
[the release workflow](.github/workflows/release-desktop.yml) for the targets in
`desktop/src-tauri/release-targets.json`. The workflow creates a draft GitHub
release; publication is a deliberate human step. The application has no
automatic update channel.

## Before tagging

1. Choose a SemVer version and set the same value in:
   - `desktop/package.json`
   - `desktop/src-tauri/Cargo.toml`
   - `desktop/src-tauri/tauri.conf.json`
2. Run the full repository and desktop verification described in the package
   READMEs.
3. From `desktop/`, run `npm run release:validate`. This checks synchronized
   versions, the target matrix, tag shape when supplied, and the deliberate
   absence of a half-configured updater.
4. Review `desktop/src-tauri/release-targets.json`. It is the source of truth for
   supported runners, Rust targets, and bundle formats.
5. Confirm that no generated sidecar, release override, installer, signing
   certificate, key, or local vault is staged for commit.

The release tag must be exactly `desktop-v<VERSION>`, for example
`desktop-v1.2.3`, and must match the three metadata files.

## Release environment

The GitHub environment is named `native-release`. Configure its protection and
required reviewers before using real signing material.

Repository/environment secrets used by the workflow:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- `APPLE_CERTIFICATE` (base64-encoded PKCS #12)
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_KEYCHAIN_PASSWORD`
- `APPLE_ID`
- `APPLE_PASSWORD` (app-specific password)
- `APPLE_TEAM_ID`
- `WINDOWS_CERTIFICATE` (base64-encoded PFX)
- `WINDOWS_CERTIFICATE_PASSWORD`

Repository/environment variables:

- `ORIONVIVA_WINDOWS_CERTIFICATE_THUMBPRINT`
- `ORIONVIVA_WINDOWS_TIMESTAMP_URL` (absolute HTTPS URL)

`GITHUB_TOKEN` is supplied by GitHub Actions and is granted write access only in
the packaging job. Do not copy signing secrets into `.env`, workflow logs, issue
comments, artifacts, or diagnostics.

## Build and validation performed by CI

For every declared target, the workflow:

1. validates metadata and required platform signing inputs;
2. installs pinned workflow actions and project dependencies;
3. builds a target-native packaged Python sidecar;
4. verifies that the staged sidecar exists and reports its build identity;
5. runs the packaged sidecar, opens the sample vault, and reads the live
   surfaces before signing;
6. imports the target signing identity where required;
7. builds the native bundles and uploads both workflow artifacts and draft
   release assets.

The matrix currently produces Linux x86_64 AppImage/deb, Windows x86_64
NSIS/MSI, and macOS arm64/x86_64 app/DMG bundles. Read the target file rather
than copying that list into automation.

## Publish checklist

After pushing the matching tag, leave the release as a draft until all target
jobs complete. Then:

- confirm every expected target and bundle is present once;
- inspect the workflow's packaged-sidecar validation for every target;
- verify signatures/notarization with the platform's native tools;
- install on a clean representative machine, start offline, open the sample
  vault, exercise the main reads and one safe action, quit, reopen, and confirm
  the vault remains readable;
- confirm Trust shows the expected sidecar revision and says that no automatic
  update channel exists;
- scan release notes and generated assets for secrets, local paths, and user
  data;
- publish the draft only after the checks above are recorded.

Do not publish a partial matrix as a normal release. If a platform is
intentionally removed, change and review the target manifest first.

## Failure and rollback

- Before publication, delete or replace bad draft assets and rerun from a fixed
  commit with a new version/tag. Do not move an already published tag to new
  bytes.
- After publication, stop distribution by marking the release affected and
  removing compromised assets if necessary, then ship a new version. Preserve
  the advisory record.
- There is no in-app rollback. Keep the prior reviewed installer available when
  safe, and never instruct a user to delete or overwrite a vault as part of an
  application rollback.
- Vault export and restore write verified copies to new locations. They are
  recovery tools, not a substitute for testing schema compatibility or keeping
  independent backups.
- If signing material may have leaked, halt publication, rotate/revoke it at the
  issuing platform, replace the GitHub secret, and document the affected release
  privately before disclosure.

## Running platform checks without signing

The Quality workflow supports manual dispatch as well as pushes and pull
requests. After the reviewed commit is available remotely, select **Actions →
Quality → Run workflow** and choose that exact branch. This runs the existing
macOS, Windows and Linux desktop matrix without signing credentials or creating
a release. Each target builds its packaged sidecar, runs the sample reads and
same-artifact lifecycle smoke, tests the native host and builds a desktop bundle.
The JSON smoke reports are retained as `quality-sidecar-lifecycle-<runner>`
artifacts. Record the workflow run and commit alongside those reports.

Manual runs also execute the denylist scan. The repository's `DENYLIST` secret
must be configured; a missing list fails the scan instead of silently marking
privacy checks complete. Fork pull requests still do not receive that secret.
A successful Quality run proves the checks that executed on those runners; it
does not replace signed installer or native accessibility evidence. Dispatching
a workflow requires the reviewed changes to be pushed first and is separate
from local implementation or test execution.

## Executable checks before the clean-host walkthrough

Run the commands in this section with the project’s Python 3.12 environment
activated. The release job runs `scripts/validate_sidecar_lifecycle.py` before signing
and retains its JSON report as a workflow artifact. This smoke check copies the
packaged sidecar into a disposable application directory, creates the fictional
sample in a separate temporary profile, closes it, replaces the executable,
reopens the existing vault without permission to create it, removes application
bytes, and reinstalls. It checks unchanged encrypted ledger, authenticated head
and original-document bytes. The entire vault must survive application-directory
removal unchanged. Child processes receive a synthetic home and empty explicit
configuration, without inherited model credentials or proxy settings.

The CI run uses the same artifact for both positions and reports
`same-artifact-smoke`. It does not establish compatibility between releases.
For that narrower compatibility check, supply actual packaged sidecars from the
prior reviewed release and candidate, on their matching host. This runner
requires both artifacts to speak the reviewed protocol 2.1; older protocols need
a separately reviewed adapter before their compatibility can be claimed:

```sh
python scripts/validate_sidecar_lifecycle.py --baseline /path/to/prior-sidecar --candidate /path/to/candidate-sidecar --require-distinct --output sidecar-transition.json
```

The report binds both artifact hashes and all observed revisions. A refusal,
changed canonical data, failed reopen, or non-clean process exit fails the check.
Different artifact bytes alone do not prove different storage schemas were
exercised; record the two release versions with the report. This conservative
check rejects in-place canonical migrations and does not authorize them. It is
packaged-sidecar evidence, not native installation, UI launch, operating-system
uninstallation, or a guarantee that every historic vault can be downgraded.

Verify signed native artifacts on their matching host without launching them:

```sh
python scripts/verify_native_signature.py --artifact /path/to/OrionViva.app --expected-identity APPLE_TEAM_ID --output app-signature.json
python scripts/verify_native_signature.py --artifact /path/to/OrionViva.dmg --expected-identity APPLE_TEAM_ID --output dmg-signature.json
python scripts/verify_native_signature.py --artifact C:/artifacts/OrionViva.msi --expected-identity CERTIFICATE_THUMBPRINT --output msi-signature.json
```

For Windows NSIS, supply its `.exe` instead. The expected publisher identifier
must come from the reviewed release configuration, not from whichever artifact
was downloaded. macOS requires strict code-signature verification, the expected
team, Gatekeeper assessment and a valid stapled notarization ticket. Windows
requires native Authenticode validation and the expected signing certificate.
The JSON report binds the checked bytes and lists the commands' checks. The
script refuses unsupported platforms; there is no configured Linux publisher
signature policy to claim. Linux artifact hashes and trusted release provenance
remain separate checks. These reports are generated by commands, but are not
signed attestations and must not be accepted as proof merely because somebody
supplied a JSON file saying `passed`.

The real installer walkthrough still needs disposable OS accounts or machines
with no private vault, saved keychain entry, reader credentials or user profile.
Use both actual reviewed installers, preserve the sample vault outside the app
installation, and record native installation, offline launch, quit/reopen,
replacement with the candidate, rollback to the prior release, application
uninstallation and vault reopen after reinstall. Do not substitute deletion of a
temporary sidecar directory for the native uninstaller. Record unsupported
rollback honestly. Native keyboard and screen-reader checks also remain part of
that host walkthrough; the scripts above do not execute the GUI or turn missing
host observations into passing evidence.
