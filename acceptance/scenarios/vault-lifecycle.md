# Vault lifecycle and onboarding

## VAULT-001 — First launch is usable

**Prerequisite:** No remembered OrionViva vault exists for this operating-system user.

**Actions:** Launch the installed application and inspect the first screen.

**Pass:** The application explains the available next actions, and both creating
a private vault and opening the sample experience are clearly actionable.

## VAULT-002 — Create an empty private vault

**Actions:** Create a vault in a new local directory with a valid vaultphrase,
then open Statements.

**Pass:** The vault stays open and Statements shows a clear empty state with an
action for adding documents. It does not silently return to “No vault open.”

## VAULT-003 — Remember the default vault securely

**Prerequisite:** A private vault has been opened successfully.

**Actions:** Close the application completely and launch it again as the same
operating-system user.

**Pass:** On macOS and Windows, the same vault opens by default without asking
for the vaultphrase again. The interface does not display the vaultphrase. On a
platform without protected credential storage, the application asks the user
to unlock instead of storing the vaultphrase insecurely.

## VAULT-004 — Locked remembered vault keeps its location

**Prerequisite:** A remembered private vault cannot be unlocked automatically.

**Actions:** Launch the application.

**Pass:** The unlock screen identifies or preselects the remembered vault
directory, does not reveal its vaultphrase, and explains that unlocking is
required.

## VAULT-005 — Switch to another private vault

**Prerequisite:** Two private test vaults exist.

**Actions:** Open the first vault, then deliberately open the second. Restart
the application.

**Pass:** The second vault is the active and remembered default. No surface or
recovery action switches back to the first vault.

## VAULT-006 — Sample mode never replaces or reveals the private default

**Prerequisite:** A private vault is remembered.

**Actions:** Open the sample experience and navigate through its surfaces.

**Pass:** Sample data remains active for the session. A sample read failure does
not open the private vault, and the sample does not change the remembered
private default.

## VAULT-007 — Close vault is deliberate and clear

**Prerequisite:** A vault is open.

**Actions:** Use the product's close or change-vault action.

**Pass:** Financial surfaces stop showing the closed vault, the next available
actions are clear, and no private figures remain visible in the closed state.

## VAULT-008 — Export and restore preserve custody

**Prerequisite:** Use only a synthetic test vault with known contents.

**Actions:** Export or back up the vault through the supported flow, restore it
to a separate location, and unlock it with the correct vaultphrase.

**Pass:** Restoration is verified without modifying the source vault, the
restored picture matches the source, and an incorrect vaultphrase does not
expose data or damage either copy.

