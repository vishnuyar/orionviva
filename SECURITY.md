# Security Policy

OrionViva handles financial documents, credentials, and an encrypted personal
vault. Please report a suspected vulnerability privately and do not include
sensitive details in a public issue, discussion, commit, or pull request.

## Reporting a vulnerability

Use this repository's **Security** tab and choose **Report a vulnerability** to
open a private report with the maintainers. If private vulnerability reporting
is unavailable, open a public issue containing no vulnerability details and ask
for a private maintainer contact channel.

Include, where possible:

- the affected commit or desktop version and operating system;
- the trust boundary involved: vault, raw document store, model egress,
  sidecar protocol, desktop host, packaging, or update/release process;
- reproducible steps using synthetic data;
- the impact and whether exploitation requires local access, a crafted
  document, a configured model, or a modified package;
- logs or diagnostics only after checking that they contain no financial data,
  passphrase, API key, document content, or user path.

Please do not test against another person's data or account, run denial-of-
service tests against public infrastructure, publish an exploit before a fix is
available, or upload real financial documents as evidence. The maintainers will
acknowledge the report, establish a private coordination path, and share status
as investigation and remediation progress.

## Supported code

Security fixes target the current default branch and the most recent published
desktop release. Older source snapshots and installers may not receive a patch;
the advisory will say which versions are affected and where the fix landed.

## Security boundaries worth knowing

- The vault is encrypted locally and its event log is tamper-evident. The
  project does not currently claim independent external anchoring or issuer
  signatures on imported documents.
- Model access is optional. Once a person explicitly configures and confirms a
  provider, relevant content may leave the device; outbound calls are recorded.
- There is no automatic update channel. A new version is installed manually
  from a reviewed release.
- Losing the vault passphrase currently loses access to the vault. Do not send a
  passphrase or key with a report.

For the detailed threat model, see
[Threat Model and Ingestion Security](docs/threat-model-and-ingestion-security.md).
