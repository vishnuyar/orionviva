# Installing OrionViva

OrionViva is an early desktop application for macOS, Windows, and Linux. The
desktop interface and its Python financial engine are packaged together; an end
user does not install Python or Node.js separately when using a release build.

## Install a published build

Download the installer for your platform from
[GitHub Releases](https://github.com/vishnuyar/orionviva/releases). Use only an
artifact attached to the intended release and verify its
published signature when signing information is available.

### macOS

1. Download the DMG matching your Mac: Apple silicon (`aarch64`) or Intel
   (`x86_64`).
2. Open the DMG and move OrionViva to Applications.
3. Launch OrionViva from Applications.
4. Complete any macOS trust prompt for the signed application.

OrionViva uses macOS Keychain to protect the default vault's directory and
vaultphrase. macOS may ask for permission to use that credential. Denying
access does not alter the vault, but automatic opening will not work until the
credential can be accessed or is replaced by opening the vault again.

### Windows

1. Download the published NSIS (`.exe`) or MSI installer.
2. Run the installer and review the publisher information shown by Windows.
3. Launch OrionViva from the Start menu.

OrionViva uses Windows Credential Manager to protect the default vault's
directory and vaultphrase. The credential belongs to the signed-in Windows
user. A different Windows account must unlock the vault separately.

### Linux

Published Linux builds are provided as AppImage and Debian packages. The
current automatic protected-credential implementation targets macOS Keychain
and Windows Credential Manager; Linux builds require the vaultphrase after an
application restart.

For an AppImage, mark the downloaded file executable and run it. For a Debian
package, install it with the package-management tool approved for the machine.
Required WebKit and desktop libraries vary by distribution.

## First launch

The first screen offers two paths:

- Open the sample vault to explore invented data without adding personal
  records.
- Choose a folder, enter a vaultphrase, and either open an existing private
  vault or explicitly create a new one.

Creating a vault is never inferred from a missing folder. Select **Make a new
vault in that folder** before using **Make and open vault**.

Keep an independent record of the vaultphrase. Keychain or Credential Manager
provides automatic opening on one device; it is not a portable recovery method.

## Build from source

Maintainers need:

- Git.
- Python 3.11 or newer.
- Node.js and npm.
- Rust and Cargo.
- The [platform dependencies required by Tauri 2](https://v2.tauri.app/start/prerequisites/).

Clone the repository, then from its root create the Python environment:

```sh
python3 -m venv .venv
.venv/bin/pip install -e './core[dev]' -e './merchant[dev]' -e './product[dev,reader]' -r product/requirements-sidecar-build.txt
```

Install desktop dependencies and build the complete native application:

```sh
cd desktop
npm ci
npm run desktop:build
```

The native build first creates the frontend and packaged Python sidecar, then
asks Tauri to produce the platform bundle. Output is written under
`desktop/src-tauri/target/release/bundle/`.

For frontend-only development:

```sh
cd desktop
npm run dev
```

This browser-facing development view does not provide the native file picker,
protected credential store, or packaged sidecar boundary. Use a native build
before accepting platform behavior.

## Optional model configuration

OrionViva can keep documents local without a model provider, but documents that
require model reading will wait. To enable a provider, configure it through
**Trust & settings** and confirm the proposed change. Never place provider API
keys in source control, issue reports, screenshots, or diagnostics.

Repository developers can use `.env.example` as the reference for environment-
based engine configuration. Copy only required values into a git-ignored
`.env`, and provide API keys through the named environment variable.

## Updating and uninstalling

OrionViva currently has no automatic update channel. Install a newer reviewed
release using its platform installer. Updating the application must not require
deleting or replacing the vault.

Before uninstalling, keep the vault directory and vaultphrase if the data must
remain accessible. Removing the application does not make a copied vault
decryptable without its vaultphrase. Removing a saved Keychain or Credential
Manager entry disables automatic opening but does not delete the vault.

## Troubleshooting

- **No window appears:** confirm the installed application is running, then
  quit it completely and relaunch. Record the platform and application version
  before reporting the defect.
- **The default vault stays locked:** enter its vaultphrase again. A successful
  open replaces the protected credential for that vault on this device.
- **The vault is absent:** verify the selected folder. OrionViva will not create
  a replacement unless creation is explicitly selected.
- **A document waits:** open Statements and inspect its visible reading state,
  then confirm model configuration in Trust & settings when model reading is
  intended.
- **A figure looks wrong:** open its evidence and review its date, currency,
  coverage, exclusions, and source before changing any record.

Report security-sensitive problems privately through
[SECURITY.md](../SECURITY.md). For release construction and signing, use
[RELEASING.md](../RELEASING.md).
