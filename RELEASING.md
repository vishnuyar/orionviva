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
