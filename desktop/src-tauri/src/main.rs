use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::{Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

#[cfg(any(target_os = "macos", target_os = "windows"))]
use serde::{Deserialize, Serialize};

// The protocol version every frame this host sends is stamped with. The
// sidecar refuses a frame whose major version is not its own, so this moves
// with the sidecar's own constant and never on its own.
const BRIDGE_PROTOCOL: &str = "2.0";

// The window event one progress frame is delivered on. The sidecar produces
// these while a job runs; before this existed they were read off the transport
// and dropped on the floor, which is a channel that reports nothing. The name
// is the shell's half of one constant and moves only when the page's does.
const JOB_PROGRESS_EVENT: &str = "orionviva://job-progress";

const BRIDGE_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
const BRIDGE_SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(25);

#[cfg(any(target_os = "macos", target_os = "windows"))]
const VAULT_CREDENTIAL_SERVICE: &str = "com.orionviva.desktop.default-vault";
#[cfg(any(target_os = "macos", target_os = "windows"))]
const VAULT_CREDENTIAL_ACCOUNT: &str = "default";

#[cfg(any(target_os = "macos", target_os = "windows"))]
#[derive(Serialize, Deserialize)]
struct RememberedVault {
    directory: String,
    passphrase: String,
}

#[derive(serde::Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
enum RememberedVaultOpen {
    Absent,
    Opened { directory: String },
    Locked { directory: String },
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn credential_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(VAULT_CREDENTIAL_SERVICE, VAULT_CREDENTIAL_ACCOUNT)
        .map_err(|error| format!("unable to access the operating-system credential store: {error}"))
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn store_remembered_vault(directory: &str, passphrase: &str) -> Result<(), String> {
    let encoded = serde_json::to_string(&RememberedVault {
        directory: directory.to_string(),
        passphrase: passphrase.to_string(),
    })
    .map_err(|error| format!("unable to encode the remembered vault: {error}"))?;
    credential_entry()?.set_password(&encoded).map_err(|error| {
        format!("unable to protect the remembered vault with this device: {error}")
    })
}

#[cfg(any(target_os = "macos", target_os = "windows"))]
fn load_remembered_vault() -> Result<Option<RememberedVault>, String> {
    let encoded = match credential_entry()?.get_password() {
        Ok(encoded) => encoded,
        Err(keyring::Error::NoEntry) => return Ok(None),
        Err(error) => {
            return Err(format!(
                "unable to read the remembered vault from this device: {error}"
            ))
        }
    };
    serde_json::from_str(&encoded)
        .map(Some)
        .map_err(|_| "the protected remembered-vault entry is unreadable".to_string())
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn store_remembered_vault(_directory: &str, _passphrase: &str) -> Result<(), String> {
    Err("remembered vaults require macOS Keychain or Windows Credential Manager".to_string())
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn load_remembered_vault() -> Result<Option<RememberedVaultFallback>, String> {
    Ok(None)
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
struct RememberedVaultFallback {
    directory: String,
    passphrase: String,
}

struct BridgeProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: BufReader<ChildStdout>,
}

impl BridgeProcess {
    fn status(&mut self) -> Result<Option<ExitStatus>, String> {
        self.child
            .try_wait()
            .map_err(|error| format!("unable to inspect OrionViva bridge process: {error}"))
    }

    fn ensure_running(&mut self) -> Result<(), String> {
        match self.status()? {
            Some(status) => Err(format!(
                "OrionViva bridge process exited unexpectedly ({})",
                describe_exit_status(status)
            )),
            None => Ok(()),
        }
    }

    fn shutdown(&mut self) -> Result<(), String> {
        // Closing stdin is the sidecar's graceful shutdown signal: its JSON-lines
        // loop reaches EOF, drops the opened vault, and exits without a new RPC.
        self.stdin.take();
        let deadline = Instant::now() + BRIDGE_SHUTDOWN_TIMEOUT;

        loop {
            match self.status()? {
                Some(_) => return Ok(()),
                None if Instant::now() < deadline => {
                    thread::sleep(BRIDGE_SHUTDOWN_POLL_INTERVAL);
                }
                None => break,
            }
        }

        match self.child.kill() {
            Ok(()) => {}
            Err(error) if error.kind() == ErrorKind::InvalidInput => {
                // The process exited between the final status check and kill.
            }
            Err(error) => {
                return Err(format!(
                    "OrionViva bridge did not stop within {} ms and could not be terminated: {error}",
                    BRIDGE_SHUTDOWN_TIMEOUT.as_millis()
                ));
            }
        }

        self.child
            .wait()
            .map(|_| ())
            .map_err(|error| format!("unable to reap OrionViva bridge process: {error}"))
    }
}

impl Drop for BridgeProcess {
    fn drop(&mut self) {
        if let Err(error) = self.shutdown() {
            eprintln!("{error}");
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ActiveVault {
    None,
    Sample,
    Private(String),
}

struct BridgeState {
    process: Mutex<Option<BridgeProcess>>,
    active_vault: Mutex<ActiveVault>,
}

impl BridgeState {
    fn lock(&self) -> Result<MutexGuard<'_, Option<BridgeProcess>>, String> {
        self.process
            .lock()
            .map_err(|_| "OrionViva bridge lifecycle state is unavailable".to_string())
    }

    fn shutdown(&self) -> Result<(), String> {
        let mut process = self.lock()?;
        shutdown_current(&mut process)
    }

    fn restart(&self) -> Result<(), String> {
        let mut process = self.lock()?;
        shutdown_current(&mut process)?;
        *process = Some(spawn_bridge()?);
        Ok(())
    }
}

fn describe_exit_status(status: ExitStatus) -> String {
    status
        .code()
        .map(|code| format!("exit code {code}"))
        .unwrap_or_else(|| "terminated by signal".to_string())
}

fn force_stop_child(child: &mut Child) {
    if child.try_wait().ok().flatten().is_none() {
        let _ = child.kill();
    }
    let _ = child.wait();
}

// The bridge a packaged build runs: the executable Tauri stages beside this
// one. It is asked for by name because `externalBin` stages it under its own
// name with the target triple stripped, so this constant and that entry in
// tauri.conf.json move together or not at all.
//
// A build that never looked here fell through to the development `python3`,
// whose working directory is a path baked in at compile time. That path exists
// on the machine that built the app and nowhere else, and the interpreter it
// found was whatever `python3` means to a Finder-launched process — 3.9 on a
// stock Mac, which cannot import the product runtime at all. The sidecar died
// before reading a frame, and every open answered with a bridge that was
// already gone.
const BUNDLED_SIDECAR: &str = "viva-desktop-bridge";

fn bundled_sidecar() -> Option<PathBuf> {
    let beside = std::env::current_exe()
        .ok()?
        .parent()?
        .join(format!("{BUNDLED_SIDECAR}{}", std::env::consts::EXE_SUFFIX));
    beside.is_file().then_some(beside)
}

fn spawn_bridge() -> Result<BridgeProcess, String> {
    // An explicit path wins, so a developer can point the host at a bridge of
    // their own. Otherwise the bundled executable, which is what every
    // installed copy runs. Only a build with neither — a checkout being worked
    // on — falls back to the repository's Python module.
    let mut command = if let Ok(path) = std::env::var("ORIONVIVA_SIDECAR") {
        Command::new(path)
    } else if let Some(path) = bundled_sidecar() {
        Command::new(path)
    } else {
        let mut command = Command::new("python3");
        command.args(["-m", "viva.desktop_bridge"]);
        let product_root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../product");
        command.current_dir(product_root);
        command
    };

    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    let mut child = command
        .spawn()
        .map_err(|error| format!("unable to start OrionViva bridge: {error}"))?;
    let stdin = match child.stdin.take() {
        Some(stdin) => stdin,
        None => {
            force_stop_child(&mut child);
            return Err("OrionViva bridge started without a writable stdin pipe".to_string());
        }
    };
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            drop(stdin);
            force_stop_child(&mut child);
            return Err("OrionViva bridge started without a readable stdout pipe".to_string());
        }
    };

    Ok(BridgeProcess {
        child,
        stdin: Some(stdin),
        stdout: BufReader::new(stdout),
    })
}

fn shutdown_current(process: &mut Option<BridgeProcess>) -> Result<(), String> {
    let Some(mut current) = process.take() else {
        return Ok(());
    };
    current.shutdown()
}

fn ensure_bridge(process: &mut Option<BridgeProcess>) -> Result<&mut BridgeProcess, String> {
    let stale_status = match process.as_mut() {
        Some(current) => current.status()?,
        None => None,
    };

    if let Some(status) = stale_status {
        // Drop and reap the exited handle before creating a replacement. This
        // keeps at most one sidecar owned by the host at any point in time.
        process.take();
        eprintln!(
            "OrionViva bridge was stale ({}); starting a fresh process",
            describe_exit_status(status)
        );
    }

    if process.is_none() {
        *process = Some(spawn_bridge()?);
    }
    process
        .as_mut()
        .ok_or_else(|| "OrionViva bridge did not initialize".to_string())
}

fn request_process(
    app: &AppHandle,
    bridge: &mut BridgeProcess,
    request_id: &str,
    encoded: &str,
) -> Result<Value, String> {
    bridge.ensure_running()?;
    let stdin = bridge
        .stdin
        .as_mut()
        .ok_or_else(|| "OrionViva bridge stdin is closed".to_string())?;
    writeln!(stdin, "{encoded}")
        .map_err(|error| format!("unable to write to OrionViva bridge: {error}"))?;
    stdin
        .flush()
        .map_err(|error| format!("unable to flush OrionViva bridge request: {error}"))?;

    let mut line = String::new();
    loop {
        line.clear();
        let read = bridge
            .stdout
            .read_line(&mut line)
            .map_err(|error| format!("unable to read OrionViva bridge response: {error}"))?;
        if read == 0 {
            let status = bridge.status()?.map(describe_exit_status);
            return Err(match status {
                Some(status) => format!("OrionViva bridge exited before responding ({status})"),
                None => "OrionViva bridge closed its output before responding".to_string(),
            });
        }
        let response: Value = serde_json::from_str(line.trim())
            .map_err(|error| format!("OrionViva bridge returned invalid JSON: {error}"))?;
        if response.get("event").is_some() {
            // A progress frame is not an answer to this request and never
            // returns from here; it is handed to the window that asked, so
            // the page can say what the job is doing while it is still doing
            // it. A window that has gone is not an error worth failing the
            // request over — the work is still running and its answer is
            // still coming.
            if let Err(error) = app.emit(JOB_PROGRESS_EVENT, &response) {
                eprintln!("unable to deliver OrionViva job progress: {error}");
            }
            continue;
        }
        if response.get("request_id").and_then(Value::as_str) == Some(request_id) {
            return Ok(response);
        }
    }
}

fn reopen_remembered_vault(
    app: &AppHandle,
    process: &mut Option<BridgeProcess>,
    expected_directory: &str,
) -> Result<(), String> {
    let remembered = load_remembered_vault()?
        .ok_or_else(|| "no device-protected default vault is available".to_string())?;
    if !protected_default_matches_active(
        &ActiveVault::Private(expected_directory.to_string()),
        &remembered.directory,
    ) {
        return Err("the protected default does not identify the active vault".to_string());
    }
    let request_id = "native-remembered-vault-recovery";
    let encoded = serde_json::to_string(&json!({
        "protocol": BRIDGE_PROTOCOL,
        "request_id": request_id,
        "operation": "bridge.open_vault",
        "payload": {
            "vault_directory": remembered.directory,
            "passphrase": remembered.passphrase,
            "create": false
        }
    }))
    .map_err(|error| format!("unable to encode remembered-vault recovery: {error}"))?;
    let response = request_process(app, ensure_bridge(process)?, request_id, &encoded)?;
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(())
    } else {
        Err("the device-protected default vault could not be unlocked".to_string())
    }
}

fn request_bridge(app: &AppHandle, state: &BridgeState, frame: Value) -> Result<Value, String> {
    let request_id = frame
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "bridge request_id is required".to_string())?
        .to_string();
    let encoded = serde_json::to_string(&frame)
        .map_err(|error| format!("unable to encode OrionViva bridge request: {error}"))?;
    let operation = frame.get("operation").and_then(Value::as_str);
    let may_recover = operation_can_restart_and_replay(operation);
    let may_reopen_vault = operation_can_reopen_vault_and_replay(operation);
    let recovery_directory = if may_reopen_vault {
        let active = state
            .active_vault
            .lock()
            .map_err(|_| "active vault identity is unavailable".to_string())?;
        recovery_directory_for(&active).map(str::to_string)
    } else {
        None
    };
    let mut process = state.lock()?;

    for attempt in 0..2 {
        let result = request_process(app, ensure_bridge(&mut process)?, &request_id, &encoded);
        match result {
            Ok(response) => {
                if response.get("ok").and_then(Value::as_bool) == Some(true) {
                    let next_active = match operation {
                        Some("bridge.open_vault") => frame
                            .pointer("/payload/vault_directory")
                            .and_then(Value::as_str)
                            .map(|directory| ActiveVault::Private(directory.trim().to_string())),
                        Some("bridge.open_demo_vault") => Some(ActiveVault::Sample),
                        _ => None,
                    };
                    if let Some(next_active) = next_active {
                        *state
                            .active_vault
                            .lock()
                            .map_err(|_| "active vault identity is unavailable".to_string())? =
                            next_active;
                    }
                }
                return Ok(response);
            }
            Err(error) => {
                let cleanup_error = shutdown_current(&mut process).err();
                if cleanup_error.is_none() && attempt == 0 {
                    if may_recover {
                        continue;
                    }
                    if let Some(directory) = recovery_directory.as_deref() {
                        if reopen_remembered_vault(app, &mut process, directory).is_ok() {
                            continue;
                        }
                    }
                }
                return Err(match cleanup_error {
                    Some(cleanup) => format!(
                        "{error}; bridge recovery cleanup also failed: {cleanup}. Restart OrionViva before retrying"
                    ),
                    None => format!(
                        "{error}. The bridge was reset safely; retry after reopening the vault"
                    ),
                });
            }
        }
    }

    Err("OrionViva bridge recovery attempts were exhausted".to_string())
}

// Restarting the process discards the in-memory vault key. Only operations
// that establish a vault may therefore be replayed into a fresh process. A
// surface read used to be replayed here as well; the fresh bridge correctly
// answered that no vault was open, and the shell then replaced a visible
// financial picture with that answer. A surface read may be replayed only
// after the protected default credential has first reopened the same vault.
fn operation_can_restart_and_replay(operation: Option<&str>) -> bool {
    matches!(
        operation,
        Some("bridge.open_vault" | "bridge.open_demo_vault")
    )
}

fn operation_can_reopen_vault_and_replay(operation: Option<&str>) -> bool {
    operation == Some("viva.surface.read")
}

fn recovery_directory_for(active: &ActiveVault) -> Option<&str> {
    match active {
        ActiveVault::Private(directory) => Some(directory),
        ActiveVault::None | ActiveVault::Sample => None,
    }
}

fn protected_default_matches_active(active: &ActiveVault, remembered_directory: &str) -> bool {
    recovery_directory_for(active) == Some(remembered_directory)
}

#[cfg(test)]
mod tests {
    use super::{
        operation_can_reopen_vault_and_replay, operation_can_restart_and_replay,
        protected_default_matches_active, recovery_directory_for, ActiveVault,
    };

    #[test]
    fn only_vault_openers_are_safe_to_replay_after_bridge_loss() {
        assert!(operation_can_restart_and_replay(Some("bridge.open_vault")));
        assert!(operation_can_restart_and_replay(Some(
            "bridge.open_demo_vault"
        )));
        assert!(!operation_can_restart_and_replay(Some("viva.surface.read")));
        assert!(!operation_can_restart_and_replay(Some(
            "viva.documents.upload"
        )));
        assert!(!operation_can_restart_and_replay(None));
        assert!(operation_can_reopen_vault_and_replay(Some(
            "viva.surface.read"
        )));
        assert!(!operation_can_reopen_vault_and_replay(Some(
            "viva.documents.upload"
        )));
    }

    #[test]
    fn protected_recovery_is_bound_to_the_exact_active_private_vault() {
        let vault_b = ActiveVault::Private("/vault/b".to_string());
        assert!(protected_default_matches_active(&vault_b, "/vault/b"));
        assert!(!protected_default_matches_active(&vault_b, "/vault/a"));
        assert_eq!(recovery_directory_for(&vault_b), Some("/vault/b"));
    }

    #[test]
    fn sample_and_unopened_sessions_never_recover_a_private_default() {
        assert!(!protected_default_matches_active(
            &ActiveVault::Sample,
            "/vault/a"
        ));
        assert!(!protected_default_matches_active(
            &ActiveVault::None,
            "/vault/a"
        ));
        assert_eq!(recovery_directory_for(&ActiveVault::Sample), None);
    }
}

#[tauri::command]
fn bridge_request(
    app: AppHandle,
    state: State<'_, BridgeState>,
    frame: String,
) -> Result<String, String> {
    let mut request: Value =
        serde_json::from_str(&frame).map_err(|error| format!("invalid bridge request: {error}"))?;
    let object = request
        .as_object_mut()
        .ok_or_else(|| "bridge request must be an object".to_string())?;
    object
        .entry("protocol")
        .or_insert_with(|| json!(BRIDGE_PROTOCOL));
    let response = request_bridge(&app, &state, request)?;
    serde_json::to_string(&response)
        .map_err(|error| format!("unable to encode OrionViva bridge response: {error}"))
}

#[tauri::command]
fn remember_vault(vault_directory: String, passphrase: String) -> Result<(), String> {
    if vault_directory.trim().is_empty() || passphrase.is_empty() {
        return Err("a vault directory and vaultphrase are required".to_string());
    }
    store_remembered_vault(vault_directory.trim(), &passphrase)
}

#[tauri::command]
fn open_remembered_vault(
    app: AppHandle,
    state: State<'_, BridgeState>,
) -> Result<RememberedVaultOpen, String> {
    let Some(remembered) = load_remembered_vault()? else {
        return Ok(RememberedVaultOpen::Absent);
    };
    let directory = remembered.directory;
    let frame = json!({
        "protocol": BRIDGE_PROTOCOL,
        "request_id": "native-remembered-vault-open",
        "operation": "bridge.open_vault",
        "payload": {
            "vault_directory": directory,
            "passphrase": remembered.passphrase,
            "create": false
        }
    });
    match request_bridge(&app, &state, frame) {
        Ok(response) if response.get("ok").and_then(Value::as_bool) == Some(true) => {
            Ok(RememberedVaultOpen::Opened { directory })
        }
        Ok(_) | Err(_) => Ok(RememberedVaultOpen::Locked { directory }),
    }
}

#[tauri::command]
fn bridge_restart(state: State<'_, BridgeState>) -> Result<(), String> {
    state.restart()
}

#[tauri::command]
fn bridge_shutdown(state: State<'_, BridgeState>) -> Result<(), String> {
    state.shutdown()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVault::None),
        })
        .invoke_handler(tauri::generate_handler![
            bridge_request,
            remember_vault,
            open_remembered_vault,
            bridge_restart,
            bridge_shutdown
        ])
        .build(tauri::generate_context!())
        .expect("error while building OrionViva");

    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            let state = app_handle.state::<BridgeState>();
            if let Err(error) = state.shutdown() {
                eprintln!("unable to shut down OrionViva bridge cleanly: {error}");
            }
        }
    });
}

fn main() {
    run();
}
