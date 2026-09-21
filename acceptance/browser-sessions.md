# Supplemental browser-session acceptance

Use disposable synthetic vaults and files. Run shared product scenarios in the
browser; reserve desktop observation for the named native boundary. These checks
supplement the numbered catalog and do not claim independent evaluator coverage.

| Journey | Pass condition | Surface |
|---|---|---|
| Launch browser | Open in browser opens the shared interface; the desktop stops accepting product actions. | Browser, plus native launch/handoff |
| Create and reopen | Create an empty private vault, import a selected synthetic file, restart and reopen it; the document remains present. | Browser; native host restart |
| Existing vault | Open a desktop-created synthetic vault; browser and subsequent desktop view agree. | Browser; native handoff |
| File/folder dialog | Choosing a folder/file opens the OS dialog, cancellation is quiet, and selecting one file creates its receipt without changing the original. | Native dialog, browser outcome |
| Reload during work | Reload during an admitted request; access reconnects or gives explicit recovery. No request identity collision terminates the engine and no write is automatically repeated. | Browser |
| Duplicate tab then reload | Duplicate an active tab, then reload the duplicate. It cannot take control or expose the vault. The original remains usable. | Browser |
| Vault switch | Delay a mutation for one vault, switch vaults, then deliver it. The host rejects it and the new vault remains unchanged. | Browser with controlled request delay |
| Revoke during work | Stop browser access while a request or picker is active. New calls fail immediately and late private responses are withheld; desktop waits for admitted work to settle. | Browser; native stop control |
| Host shutdown | Quit the app. Browser access ends with actionable recovery and no false success. | Browser; native exit |
| Wrong origin | Another origin or forged Host cannot claim or use a session, even if it can reach the local port. | Browser plus host security integration |
| Protected remembering | A browser-opened private vault is remembered only through supported OS storage; the browser never persists its vaultphrase. | Native credentials, browser copy |

`desktop/scripts/test-browser-host.mjs` drives the built browser interface through
the production Rust HTTP handlers and a synthetic Python engine. Its picker is a
test-only selection and its credential store is disabled. Record that distinction;
actual OS dialogs, signed installation and other platforms still need their own
native-boundary evidence.
