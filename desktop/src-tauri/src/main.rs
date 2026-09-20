use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Condvar, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};

#[cfg(any(target_os = "macos", target_os = "windows"))]
use serde::{Deserialize, Serialize};

// The protocol version every frame this host sends is stamped with. The
// sidecar refuses a frame whose major version is not its own, so this moves
// with the sidecar's own constant and never on its own.
const BRIDGE_PROTOCOL: &str = "2.1";

// The window event one progress frame is delivered on. The sidecar produces
// these while a job runs; before this existed they were read off the transport
// and dropped on the floor, which is a channel that reports nothing. The name
// is the shell's half of one constant and moves only when the page's does.
const JOB_PROGRESS_EVENT: &str = "orionviva://job-progress";

const BRIDGE_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
const BRIDGE_SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(25);

fn startup_diagnostic_record(
    operation: &'static str,
    state: &'static str,
    duration: Duration,
    generation: usize,
    termination: &'static str,
) -> Option<Value> {
    if !matches!(
        operation,
        "generation" | "request_wait" | "timeout" | "termination"
    ) || !matches!(state, "completed" | "failed")
        || !matches!(
            termination,
            "started" | "none" | "pending" | "reaped" | "killed_reaped" | "kill_failed"
        )
    {
        return None;
    }
    Some(json!({"kind": "viva.startup.span",
        "operation": operation, "surface": "none",
        "duration_ms": duration.as_millis(), "state": state,
        "generation": generation, "termination": termination}))
}

fn startup_diagnostic(
    operation: &'static str,
    state: &'static str,
    duration: Duration,
    generation: usize,
    termination: &'static str,
) {
    if std::env::var("VIVA_STARTUP_DIAGNOSTICS").as_deref() != Ok("1") {
        return;
    }
    if let Some(record) =
        startup_diagnostic_record(operation, state, duration, generation, termination)
    {
        eprintln!("{record}");
    }
}

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

type PendingCalls = Arc<Mutex<std::collections::HashMap<String, mpsc::Sender<RoutedFrame>>>>;

#[derive(Debug)]
enum RoutedFrame {
    Response(Value),
    Progress,
    Interrupted(String),
}

#[derive(Clone)]
struct BridgeProcess {
    child: Arc<Mutex<Option<Child>>>,
    stdin: Arc<Mutex<Option<ChildStdin>>>,
    pending: PendingCalls,
    closed: Arc<AtomicBool>,
    terminal: Arc<Mutex<bool>>,
    generation: usize,
}

impl BridgeProcess {
    fn status(&self) -> Result<Option<ExitStatus>, String> {
        let mut child = self
            .child
            .lock()
            .map_err(|_| "OrionViva bridge process state is unavailable".to_string())?;
        let Some(child) = child.as_mut() else {
            return Ok(Some(exit_status_for_reaped_process()));
        };
        child
            .try_wait()
            .map_err(|error| format!("unable to inspect OrionViva bridge process: {error}"))
    }

    fn shutdown(&mut self) -> Result<(), String> {
        let mut terminal = self
            .terminal
            .lock()
            .map_err(|_| "OrionViva bridge termination state is unavailable".to_string())?;
        if *terminal {
            return Ok(());
        }
        let started = Instant::now();
        // Closing stdin is the sidecar's graceful shutdown signal: its JSON-lines
        // loop reaches EOF, drops the opened vault, and exits without a new RPC.
        self.closed.store(true, Ordering::SeqCst);
        if let Ok(mut stdin) = self.stdin.lock() {
            stdin.take();
        }
        interrupt_pending(&self.pending, "OrionViva bridge was interrupted");
        let deadline = Instant::now() + BRIDGE_SHUTDOWN_TIMEOUT;

        loop {
            match self.status()? {
                Some(_) => {
                    *terminal = true;
                    startup_diagnostic(
                        "termination",
                        "completed",
                        started.elapsed(),
                        self.generation,
                        "reaped",
                    );
                    return Ok(());
                }
                None if Instant::now() < deadline => {
                    thread::sleep(BRIDGE_SHUTDOWN_POLL_INTERVAL);
                }
                None => break,
            }
        }

        let mut child = self
            .child
            .lock()
            .map_err(|_| "OrionViva bridge process state is unavailable".to_string())?;
        let Some(child) = child.as_mut() else {
            return Ok(());
        };
        match child.kill() {
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

        let result = child
            .wait()
            .map(|_| ())
            .map_err(|error| format!("unable to reap OrionViva bridge process: {error}"));
        if result.is_ok() {
            *terminal = true;
        }
        startup_diagnostic(
            "termination",
            if result.is_ok() {
                "completed"
            } else {
                "failed"
            },
            started.elapsed(),
            self.generation,
            if result.is_ok() {
                "killed_reaped"
            } else {
                "kill_failed"
            },
        );
        result
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum ActiveVault {
    None,
    Sample,
    Private(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ActiveVaultRecord {
    vault: ActiveVault,
    generation: usize,
}

fn clear_active_vault_after_failure(
    active_vault: &Mutex<ActiveVaultRecord>,
    failed_generation: usize,
) -> Result<(), String> {
    let mut active = active_vault
        .lock()
        .map_err(|_| "active vault identity is unavailable".to_string())?;
    if active.generation == failed_generation {
        active.vault = ActiveVault::None;
    }
    Ok(())
}

struct BridgeState {
    process: Mutex<Option<BridgeProcess>>,
    active_vault: Mutex<ActiveVaultRecord>,
    next_generation: AtomicUsize,
    read_recovery_claimed: AtomicBool,
    recovery_gate: RecoveryGate,
}

struct RecoveryGate {
    busy: Mutex<bool>,
    ready: Condvar,
}

impl RecoveryGate {
    fn new() -> Self {
        Self {
            busy: Mutex::new(false),
            ready: Condvar::new(),
        }
    }

    fn wait(&self) -> Result<(), String> {
        let busy = self
            .busy
            .lock()
            .map_err(|_| "OrionViva bridge recovery state is unavailable".to_string())?;
        let (busy, timed_out) = self
            .ready
            .wait_timeout_while(busy, Duration::from_secs(90), |busy| *busy)
            .map_err(|_| "OrionViva bridge recovery state is unavailable".to_string())?;
        if timed_out.timed_out() && *busy {
            return Err("OrionViva bridge recovery did not settle".to_string());
        }
        Ok(())
    }

    fn begin(&self) -> Result<RecoveryPermit<'_>, String> {
        let mut busy = self
            .busy
            .lock()
            .map_err(|_| "OrionViva bridge recovery state is unavailable".to_string())?;
        *busy = true;
        Ok(RecoveryPermit { gate: self })
    }
}

struct RecoveryPermit<'a> {
    gate: &'a RecoveryGate,
}

impl Drop for RecoveryPermit<'_> {
    fn drop(&mut self) {
        if let Ok(mut busy) = self.gate.busy.lock() {
            *busy = false;
            self.gate.ready.notify_all();
        }
    }
}

#[cfg(unix)]
fn exit_status_for_reaped_process() -> ExitStatus {
    use std::os::unix::process::ExitStatusExt;
    ExitStatus::from_raw(0)
}

#[cfg(windows)]
fn exit_status_for_reaped_process() -> ExitStatus {
    use std::os::windows::process::ExitStatusExt;
    ExitStatus::from_raw(0)
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

    fn restart(&self, app: &AppHandle) -> Result<(), String> {
        let mut process = self.lock()?;
        shutdown_current(&mut process)?;
        let mut spawned = spawn_bridge(app)?;
        spawned.generation = self.next_generation.fetch_add(1, Ordering::SeqCst) + 1;
        *process = Some(spawned);
        *self
            .active_vault
            .lock()
            .map_err(|_| "active vault identity is unavailable".to_string())? = ActiveVaultRecord {
            vault: ActiveVault::None,
            generation: 0,
        };
        self.read_recovery_claimed.store(false, Ordering::SeqCst);
        Ok(())
    }
}

impl Drop for BridgeState {
    fn drop(&mut self) {
        if let Ok(process) = self.process.get_mut() {
            if let Err(error) = shutdown_current(process) {
                eprintln!(
                    "unable to shut down OrionViva bridge while dropping host state: {error}"
                );
            }
        }
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

fn interrupt_pending(pending: &PendingCalls, reason: &str) {
    let calls = pending
        .lock()
        .map(|mut calls| calls.drain().map(|(_, sender)| sender).collect::<Vec<_>>())
        .unwrap_or_default();
    for sender in calls {
        let _ = sender.send(RoutedFrame::Interrupted(reason.to_string()));
    }
}

fn route_pending(pending: &PendingCalls, request_id: &str, frame: RoutedFrame) {
    if let Ok(mut calls) = pending.lock() {
        match frame {
            RoutedFrame::Progress => {
                if let Some(sender) = calls.get(request_id) {
                    let _ = sender.send(RoutedFrame::Progress);
                }
            }
            frame => {
                if let Some(sender) = calls.remove(request_id) {
                    let _ = sender.send(frame);
                }
            }
        }
    }
}

fn route_stdout<R: tauri::Runtime>(
    app: AppHandle<R>,
    stdout: ChildStdout,
    mut bridge: BridgeProcess,
) {
    let mut stdout = BufReader::new(stdout);
    let mut line = String::new();
    loop {
        line.clear();
        let read = match stdout.read_line(&mut line) {
            Ok(read) => read,
            Err(error) => {
                interrupt_pending(
                    &bridge.pending,
                    &format!("unable to read OrionViva bridge response: {error}"),
                );
                if let Err(error) = bridge.shutdown() {
                    eprintln!("unable to stop OrionViva bridge after output failure: {error}");
                }
                return;
            }
        };
        if read == 0 {
            interrupt_pending(
                &bridge.pending,
                "OrionViva bridge closed its output before responding",
            );
            if let Err(error) = bridge.shutdown() {
                eprintln!("unable to stop OrionViva bridge after output closure: {error}");
            }
            return;
        }
        let response: Value = match serde_json::from_str(line.trim()) {
            Ok(response) => response,
            Err(error) => {
                interrupt_pending(
                    &bridge.pending,
                    &format!("OrionViva bridge returned invalid JSON: {error}"),
                );
                if let Err(error) = bridge.shutdown() {
                    eprintln!("unable to stop OrionViva bridge after invalid output: {error}");
                }
                return;
            }
        };
        let Some(request_id) = response
            .get("request_id")
            .and_then(Value::as_str)
            .map(str::to_string)
        else {
            interrupt_pending(
                &bridge.pending,
                "OrionViva bridge returned a frame without a request identity",
            );
            if let Err(error) = bridge.shutdown() {
                eprintln!("unable to stop OrionViva bridge after uncorrelated output: {error}");
            }
            return;
        };
        if response.get("event").is_some() {
            if let Err(error) = app.emit(JOB_PROGRESS_EVENT, &response) {
                eprintln!("unable to deliver OrionViva job progress: {error}");
            }
            route_pending(&bridge.pending, &request_id, RoutedFrame::Progress);
            continue;
        }
        route_pending(
            &bridge.pending,
            &request_id,
            RoutedFrame::Response(response),
        );
    }
}

fn spawn_bridge(app: &AppHandle) -> Result<BridgeProcess, String> {
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

    let pending = Arc::new(Mutex::new(std::collections::HashMap::new()));
    let closed = Arc::new(AtomicBool::new(false));
    let process = BridgeProcess {
        child: Arc::new(Mutex::new(Some(child))),
        stdin: Arc::new(Mutex::new(Some(stdin))),
        pending: Arc::clone(&pending),
        closed: Arc::clone(&closed),
        terminal: Arc::new(Mutex::new(false)),
        generation: 0,
    };
    let app = app.clone();
    let reader_bridge = process.clone();
    thread::spawn(move || route_stdout(app, stdout, reader_bridge));
    Ok(process)
}

fn shutdown_current(process: &mut Option<BridgeProcess>) -> Result<(), String> {
    let Some(mut current) = process.take() else {
        return Ok(());
    };
    current.shutdown()
}

fn ensure_bridge<R: tauri::Runtime>(
    app: &AppHandle<R>,
    process: &mut Option<BridgeProcess>,
    spawn: impl Fn(&AppHandle<R>) -> Result<BridgeProcess, String>,
    next_generation: &AtomicUsize,
) -> Result<BridgeProcess, String> {
    let stale_status = match process.as_mut() {
        Some(current) => current.status()?,
        None => None,
    };
    let closed = process
        .as_ref()
        .is_some_and(|current| current.closed.load(Ordering::SeqCst));
    if closed || stale_status.is_some() {
        shutdown_current(process)?;
        if let Some(status) = stale_status {
            eprintln!(
                "OrionViva bridge was stale ({}); starting a fresh process",
                describe_exit_status(status)
            );
        }
    }

    if process.is_none() {
        let mut spawned = spawn(app)?;
        spawned.generation = next_generation.fetch_add(1, Ordering::SeqCst) + 1;
        startup_diagnostic(
            "generation",
            "completed",
            Duration::ZERO,
            spawned.generation,
            "started",
        );
        *process = Some(spawned);
    }
    process
        .as_ref()
        .cloned()
        .ok_or_else(|| "OrionViva bridge did not initialize".to_string())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct DeadlinePolicy {
    first: Duration,
    silence: Duration,
    cap: Duration,
}

fn deadline_policy(operation: Option<&str>) -> DeadlinePolicy {
    let operation = operation.unwrap_or_default();
    if matches!(operation, "viva.vault.export" | "viva.vault.restore") {
        return DeadlinePolicy {
            first: Duration::from_secs(60),
            silence: Duration::from_secs(120),
            cap: Duration::from_secs(600),
        };
    }
    if is_long_job(operation) {
        return DeadlinePolicy {
            first: Duration::from_secs(60),
            silence: Duration::from_secs(120),
            cap: Duration::from_secs(1800),
        };
    }
    let timeout = if operation == "viva.conversation.ask"
        || operation == "viva.conversation.answer"
        || operation == "viva.conversation.confirm"
    {
        Duration::from_secs(120)
    } else if matches!(operation, "bridge.open_vault" | "bridge.open_demo_vault") {
        Duration::from_secs(60)
    } else if is_read(operation) {
        Duration::from_secs(15)
    } else {
        Duration::from_secs(30)
    };
    DeadlinePolicy {
        first: timeout,
        silence: timeout,
        cap: timeout,
    }
}

fn is_long_job(operation: &str) -> bool {
    matches!(
        operation,
        "viva.documents.upload" | "viva.documents.recover" | "viva.documents.rescan" | "viva.maintenance.run"
    )
}

fn is_read(operation: &str) -> bool {
    matches!(
        operation,
        "bridge.handshake"
            | "viva.surface.read"
            | "viva.surface.capabilities"
            | "viva.lifecycle.read"
            | "viva.settings.read"
    )
}

fn operation_may_have_written(operation: Option<&str>) -> bool {
    !matches!(operation, Some(operation) if is_read(operation))
}

fn wait_for_response(
    receiver: mpsc::Receiver<RoutedFrame>,
    policy: DeadlinePolicy,
) -> Result<Value, String> {
    let started = Instant::now();
    let mut wait = policy.first;
    loop {
        let cap_left = policy.cap.saturating_sub(started.elapsed());
        if cap_left.is_zero() {
            return Err("OrionViva bridge request reached its maximum running time".to_string());
        }
        match receiver.recv_timeout(wait.min(cap_left)) {
            Ok(RoutedFrame::Response(response)) => return Ok(response),
            Ok(RoutedFrame::Progress) => wait = policy.silence,
            Ok(RoutedFrame::Interrupted(reason)) => return Err(reason),
            Err(mpsc::RecvTimeoutError::Timeout) => {
                return Err("OrionViva bridge request timed out".to_string())
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err("OrionViva bridge response channel closed".to_string())
            }
        }
    }
}

fn request_process(
    bridge: &BridgeProcess,
    request_id: &str,
    encoded: &str,
    policy: DeadlinePolicy,
) -> Result<Value, String> {
    let queued = Instant::now();
    if bridge.closed.load(Ordering::SeqCst) {
        return Err("OrionViva bridge is not running".to_string());
    }
    let (sender, receiver) = mpsc::channel();
    {
        let mut pending = bridge
            .pending
            .lock()
            .map_err(|_| "OrionViva bridge response router is unavailable".to_string())?;
        if pending.contains_key(request_id) {
            return Err("OrionViva bridge request identity is already pending".to_string());
        }
        pending.insert(request_id.to_string(), sender);
    }
    let write_result = (|| {
        let mut stdin = bridge
            .stdin
            .lock()
            .map_err(|_| "OrionViva bridge input is unavailable".to_string())?;
        let stdin = stdin
            .as_mut()
            .ok_or_else(|| "OrionViva bridge stdin is closed".to_string())?;
        writeln!(stdin, "{encoded}")
            .map_err(|error| format!("unable to write to OrionViva bridge: {error}"))?;
        stdin
            .flush()
            .map_err(|error| format!("unable to flush OrionViva bridge request: {error}"))
    })();
    if let Err(error) = write_result {
        if let Ok(mut pending) = bridge.pending.lock() {
            pending.remove(request_id);
        }
        return Err(error);
    }
    let result = wait_for_response(receiver, policy);
    // This is total host-side request wait. The serial sidecar does not yet
    // announce when a queued frame begins executing, so calling it queue time
    // would turn execution time into a misleading diagnosis.
    startup_diagnostic(
        "request_wait",
        if result.is_ok() {
            "completed"
        } else {
            "failed"
        },
        queued.elapsed(),
        bridge.generation,
        "none",
    );
    if result
        .as_ref()
        .err()
        .is_some_and(|error| error.contains("time"))
    {
        startup_diagnostic(
            "timeout",
            "completed",
            queued.elapsed(),
            bridge.generation,
            "pending",
        );
    }
    if result.is_err() {
        if let Ok(mut pending) = bridge.pending.lock() {
            pending.remove(request_id);
        }
    }
    result
}

fn reopen_remembered_vault(bridge: &BridgeProcess, expected_directory: &str) -> Result<(), String> {
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
    let response = request_process(
        bridge,
        request_id,
        &encoded,
        deadline_policy(Some("bridge.open_vault")),
    )?;
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(())
    } else {
        Err("the device-protected default vault could not be unlocked".to_string())
    }
}

fn request_bridge_with<R: tauri::Runtime>(
    app: &AppHandle<R>,
    state: &BridgeState,
    frame: Value,
    spawn: impl Fn(&AppHandle<R>) -> Result<BridgeProcess, String> + Copy,
    policy: impl Fn(Option<&str>) -> DeadlinePolicy + Copy,
    before_failed_identity_clear: impl Fn(),
) -> Result<Value, String> {
    state.recovery_gate.wait()?;
    let request_id = frame
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "bridge request_id is required".to_string())?
        .to_string();
    let encoded = serde_json::to_string(&frame)
        .map_err(|error| format!("unable to encode OrionViva bridge request: {error}"))?;
    let operation = frame.get("operation").and_then(Value::as_str);
    let recovery = if operation_can_reopen_vault_and_replay(operation) {
        Some(
            state
                .active_vault
                .lock()
                .map_err(|_| "active vault identity is unavailable".to_string())?
                .vault
                .clone(),
        )
    } else {
        None
    };
    let mut _recovery_permit = None;
    for attempt in 0..2 {
        if attempt == 0 {
            state.recovery_gate.wait()?;
        }
        let bridge = {
            let mut process = state.lock()?;
            ensure_bridge(app, &mut process, spawn, &state.next_generation)?
        };
        if attempt == 0 {
            state.recovery_gate.wait()?;
        }
        if attempt == 1 {
            let reopened = match recovery.as_ref() {
                Some(ActiveVault::Sample) => reopen_sample_vault(&bridge),
                Some(ActiveVault::Private(directory)) => {
                    reopen_remembered_vault(&bridge, directory)
                }
                _ => return Err("the previous vault cannot be recovered safely".to_string()),
            };
            if let Err(error) = reopened {
                let mut process = state.lock()?;
                let _ = shutdown_current(&mut process);
                return Err(format!("{error}. The bridge was reset safely"));
            }
        }
        let result = request_process(&bridge, &request_id, &encoded, policy(operation));
        match result {
            Ok(response) => {
                let current = state.lock()?;
                let terminal = bridge
                    .terminal
                    .lock()
                    .map_err(|_| "OrionViva bridge termination state is unavailable".to_string())?;
                if !current.as_ref().is_some_and(|live| {
                    live.generation == bridge.generation
                        && Arc::ptr_eq(&live.child, &bridge.child)
                        && !*terminal
                        && !live.closed.load(Ordering::SeqCst)
                }) {
                    let uncertainty = if operation_may_have_written(operation) {
                        " Outcome unknown; check the vault before trying again."
                    } else {
                        ""
                    };
                    return Err(format!(
                        "OrionViva bridge response belongs to an interrupted generation.{uncertainty}"
                    ));
                }
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
                            ActiveVaultRecord {
                                vault: next_active,
                                generation: bridge.generation,
                            };
                        state.read_recovery_claimed.store(false, Ordering::SeqCst);
                    } else if attempt == 1 {
                        if let Some(recovered) = recovery.clone() {
                            *state.active_vault.lock().map_err(|_| {
                                "active vault identity is unavailable".to_string()
                            })? = ActiveVaultRecord {
                                vault: recovered,
                                generation: bridge.generation,
                            };
                        }
                    }
                }
                drop(terminal);
                drop(current);
                return Ok(response);
            }
            Err(error) => {
                let (cleanup_error, will_recover) = {
                    let mut process = state.lock()?;
                    let is_current = process
                        .as_ref()
                        .map(|current| Arc::ptr_eq(&current.child, &bridge.child))
                        .unwrap_or(false);
                    let cleanup_error = if is_current {
                        shutdown_current(&mut process).err()
                    } else {
                        None
                    };
                    let will_recover = cleanup_error.is_none()
                        && attempt == 0
                        && can_replay_after_recovery(operation, recovery.as_ref())
                        && claim_read_recovery(&state.read_recovery_claimed);
                    if will_recover {
                        _recovery_permit = Some(state.recovery_gate.begin()?);
                    }
                    (cleanup_error, will_recover)
                };
                // A late failure belongs to the process that received the
                // request. If another request has already recovered onto a
                // fresh process, this failure must not erase that newer
                // process's exact-vault identity.
                before_failed_identity_clear();
                clear_active_vault_after_failure(&state.active_vault, bridge.generation)?;
                if will_recover {
                    continue;
                }
                let uncertainty = if operation_may_have_written(operation) {
                    " Outcome unknown; check the vault before trying again."
                } else {
                    ""
                };
                return Err(match cleanup_error {
                    Some(cleanup) => format!(
                        "{error}; bridge recovery cleanup also failed: {cleanup}.{uncertainty} Restart OrionViva before retrying"
                    ),
                    None => format!("{error}.{uncertainty} The bridge was reset safely"),
                });
            }
        }
    }

    Err("OrionViva bridge recovery attempts were exhausted".to_string())
}

fn request_bridge(app: &AppHandle, state: &BridgeState, frame: Value) -> Result<Value, String> {
    request_bridge_with(app, state, frame, spawn_bridge, deadline_policy, || {})
}

// Restarting the process discards the in-memory vault key. A surface read may
// be replayed only after the protected credential has reopened the same vault.
fn operation_can_reopen_vault_and_replay(operation: Option<&str>) -> bool {
    operation == Some("viva.surface.read")
}

fn recovery_is_exact(active: &ActiveVault) -> bool {
    matches!(active, ActiveVault::Sample | ActiveVault::Private(_))
}

fn can_replay_after_recovery(operation: Option<&str>, active: Option<&ActiveVault>) -> bool {
    operation_can_reopen_vault_and_replay(operation) && active.is_some_and(recovery_is_exact)
}

fn claim_read_recovery(claimed: &AtomicBool) -> bool {
    claimed
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_ok()
}

fn reopen_sample_vault(bridge: &BridgeProcess) -> Result<(), String> {
    let request_id = "native-sample-vault-recovery";
    let encoded = serde_json::to_string(&json!({
        "protocol": BRIDGE_PROTOCOL,
        "request_id": request_id,
        "operation": "bridge.open_demo_vault",
        "payload": {}
    }))
    .map_err(|error| format!("unable to encode sample-vault recovery: {error}"))?;
    let response = request_process(
        bridge,
        request_id,
        &encoded,
        deadline_policy(Some("bridge.open_demo_vault")),
    )?;
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        Ok(())
    } else {
        Err("the sample vault could not be reconstructed".to_string())
    }
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
        can_replay_after_recovery, claim_read_recovery, deadline_policy,
        operation_can_reopen_vault_and_replay, operation_may_have_written,
        protected_default_matches_active, recovery_directory_for, recovery_is_exact, route_pending,
        startup_diagnostic_record, wait_for_response, ActiveVault, ActiveVaultRecord,
        BridgeProcess, BridgeState, DeadlinePolicy, PendingCalls, RecoveryGate, RoutedFrame,
    };
    use std::process::{Command, Stdio};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::{mpsc, Arc, Mutex};
    use std::thread;
    use std::time::{Duration, Instant};

    #[cfg(unix)]
    static LIFECYCLE_FAKE_SPAWNS: AtomicUsize = AtomicUsize::new(0);
    #[cfg(unix)]
    static LIFECYCLE_FAKE_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn startup_diagnostic_record_enforces_its_privacy_allowlist() {
        let record = startup_diagnostic_record(
            "request_wait",
            "completed",
            Duration::from_millis(17),
            3,
            "none",
        )
        .unwrap();
        let fields = record.as_object().unwrap();
        assert_eq!(fields.len(), 7);
        for field in [
            "kind",
            "operation",
            "surface",
            "duration_ms",
            "state",
            "generation",
            "termination",
        ] {
            assert!(fields.contains_key(field));
        }
        assert!(startup_diagnostic_record(
            "/private/vault",
            "completed",
            Duration::ZERO,
            3,
            "none",
        )
        .is_none());
        assert!(startup_diagnostic_record(
            "request_wait",
            "merchant name",
            Duration::ZERO,
            3,
            "none",
        )
        .is_none());
        assert!(startup_diagnostic_record(
            "request_wait",
            "completed",
            Duration::ZERO,
            3,
            "/private/vault",
        )
        .is_none());
    }

    #[cfg(unix)]
    fn lifecycle_test_policy(_operation: Option<&str>) -> DeadlinePolicy {
        DeadlinePolicy {
            first: Duration::from_millis(20),
            silence: Duration::from_millis(20),
            cap: Duration::from_millis(20),
        }
    }

    #[cfg(unix)]
    fn peer_deadline_policy(operation: Option<&str>) -> DeadlinePolicy {
        if operation == Some("viva.surface.read") {
            DeadlinePolicy {
                first: Duration::from_secs(5),
                silence: Duration::from_secs(5),
                cap: Duration::from_secs(5),
            }
        } else {
            lifecycle_test_policy(operation)
        }
    }

    #[cfg(unix)]
    fn spawn_lifecycle_fake<R: tauri::Runtime>(
        _app: &tauri::AppHandle<R>,
    ) -> Result<BridgeProcess, String> {
        let spawn = LIFECYCLE_FAKE_SPAWNS.fetch_add(1, Ordering::SeqCst);
        let script = if spawn == 0 {
            // Consume requests but never answer. EOF from supervisor shutdown
            // exits the loop immediately, so termination itself is observed.
            "while IFS= read -r line; do :; done"
        } else {
            "while IFS= read -r line; do printf '{\"request_id\":\"second\",\"ok\":true}\\n'; done"
        };
        let mut child = Command::new("sh")
            .args(["-c", script])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|error| error.to_string())?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "fake stdin missing".to_string())?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "fake stdout missing".to_string())?;
        let pending = Arc::new(Mutex::new(std::collections::HashMap::new()));
        let closed = Arc::new(AtomicBool::new(false));
        let process = BridgeProcess {
            child: Arc::new(Mutex::new(Some(child))),
            stdin: Arc::new(Mutex::new(Some(stdin))),
            pending: Arc::clone(&pending),
            closed: Arc::clone(&closed),
            terminal: Arc::new(Mutex::new(false)),
            generation: 0,
        };
        thread::spawn(move || {
            let mut stdout = std::io::BufReader::new(stdout);
            let mut line = String::new();
            while std::io::BufRead::read_line(&mut stdout, &mut line).unwrap_or(0) > 0 {
                if let Ok(response) = serde_json::from_str::<serde_json::Value>(line.trim()) {
                    if let Some(request_id) = response
                        .get("request_id")
                        .and_then(serde_json::Value::as_str)
                        .map(str::to_string)
                    {
                        super::route_pending(
                            &pending,
                            &request_id,
                            RoutedFrame::Response(response),
                        );
                    }
                }
                line.clear();
            }
            closed.store(true, Ordering::SeqCst);
        });
        Ok(process)
    }

    #[cfg(unix)]
    fn spawn_recovery_fake<R: tauri::Runtime>(
        app: &tauri::AppHandle<R>,
    ) -> Result<BridgeProcess, String> {
        let spawn = LIFECYCLE_FAKE_SPAWNS.fetch_add(1, Ordering::SeqCst);
        let script = if spawn == 0 {
            "while IFS= read -r line; do :; done"
        } else {
            "opened=0; while IFS= read -r line; do id=$(printf '%s\n' \"$line\" | sed -n 's/.*\"request_id\":\"\\([^\"]*\\)\".*/\\1/p'); case \"$line\" in *bridge.open_demo_vault*) sleep 0.2; opened=1;; esac; printf '{\"request_id\":\"%s\",\"ok\":%s}\n' \"$id\" \"$([ \"$opened\" -eq 1 ] && printf true || printf false)\"; done"
        };
        let mut child = Command::new("sh")
            .args(["-c", script])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|error| error.to_string())?;
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let bridge = BridgeProcess {
            child: Arc::new(Mutex::new(Some(child))),
            stdin: Arc::new(Mutex::new(Some(stdin))),
            pending: Arc::new(Mutex::new(std::collections::HashMap::new())),
            closed: Arc::new(AtomicBool::new(false)),
            terminal: Arc::new(Mutex::new(false)),
            generation: 0,
        };
        let reader_bridge = bridge.clone();
        let app = app.clone();
        thread::spawn(move || super::route_stdout(app, stdout, reader_bridge));
        Ok(bridge)
    }

    #[cfg(unix)]
    fn spawn_opt_in_packaged<R: tauri::Runtime>(
        app: &tauri::AppHandle<R>,
    ) -> Result<BridgeProcess, String> {
        let binary =
            std::env::var("ORIONVIVA_PACKAGED_SIDECAR").map_err(|error| error.to_string())?;
        let mut child = Command::new(binary)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| error.to_string())?;
        let stdin = child.stdin.take().ok_or("packaged stdin missing")?;
        let stdout = child.stdout.take().ok_or("packaged stdout missing")?;
        let bridge = BridgeProcess {
            child: Arc::new(Mutex::new(Some(child))),
            stdin: Arc::new(Mutex::new(Some(stdin))),
            pending: Arc::new(Mutex::new(std::collections::HashMap::new())),
            closed: Arc::new(AtomicBool::new(false)),
            terminal: Arc::new(Mutex::new(false)),
            generation: 0,
        };
        let routed = bridge.clone();
        let app = app.clone();
        thread::spawn(move || super::route_stdout(app, stdout, routed));
        Ok(bridge)
    }

    #[cfg(unix)]
    fn packaged_cpu_deadline(_operation: Option<&str>) -> DeadlinePolicy {
        DeadlinePolicy {
            first: Duration::from_millis(100),
            silence: Duration::from_millis(100),
            cap: Duration::from_millis(100),
        }
    }

    #[cfg(unix)]
    #[test]
    fn packaged_cpu_bound_open_timeout_settles_peer_and_reaps_generation() {
        let (Ok(binary), Ok(vault)) = (
            std::env::var("ORIONVIVA_PACKAGED_SIDECAR"),
            std::env::var("ORIONVIVA_PACKAGED_SLOW_VAULT"),
        ) else {
            return;
        };
        assert!(std::path::Path::new(&binary).is_file());
        assert!(std::path::Path::new(&vault).join("events.jsonl").is_file());
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let app_handle = app.handle().clone();
        let state = BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::None,
                generation: 0,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        struct StopStateOnDrop<'a>(&'a BridgeState);
        impl Drop for StopStateOnDrop<'_> {
            fn drop(&mut self) {
                if let Ok(mut process) = self.0.process.lock() {
                    let _ = super::shutdown_current(&mut process);
                }
            }
        }
        let _stop = StopStateOnDrop(&state);
        let handshake = serde_json::json!({
            "protocol": super::BRIDGE_PROTOCOL, "request_id": "packaged-ready",
            "operation": "bridge.handshake", "payload": {}
        });
        let response = super::request_bridge_with(
            &app_handle,
            &state,
            handshake,
            spawn_opt_in_packaged,
            super::deadline_policy,
            || {},
        )
        .unwrap();
        assert_eq!(
            response.get("ok").and_then(serde_json::Value::as_bool),
            Some(true)
        );
        let first = state.process.lock().unwrap().as_ref().unwrap().clone();
        thread::scope(|scope| {
            let owner = scope.spawn(|| {
                super::request_bridge_with(
                    &app_handle,
                    &state,
                    serde_json::json!({
                        "protocol": super::BRIDGE_PROTOCOL, "request_id": "slow-open",
                        "operation": "bridge.open_vault",
                        "payload": {"vault_directory": vault,
                                    "passphrase": "synthetic-packaged-passphrase",
                                    "create": false}
                    }),
                    spawn_opt_in_packaged,
                    packaged_cpu_deadline,
                    || {},
                )
            });
            let deadline = Instant::now() + Duration::from_secs(2);
            while !first.pending.lock().unwrap().contains_key("slow-open") {
                assert!(Instant::now() < deadline);
                thread::sleep(Duration::from_millis(1));
            }
            let peer_frame = serde_json::json!({
                "protocol": super::BRIDGE_PROTOCOL, "request_id": "queued-peer",
                "operation": "bridge.handshake", "payload": {}
            })
            .to_string();
            let peer_bridge = first.clone();
            let peer = scope.spawn(move || {
                super::request_process(
                    &peer_bridge,
                    "queued-peer",
                    &peer_frame,
                    super::deadline_policy(Some("bridge.handshake")),
                )
            });
            while !first.pending.lock().unwrap().contains_key("queued-peer") {
                assert!(Instant::now() < deadline);
                thread::sleep(Duration::from_millis(1));
            }
            let failure = owner.join().unwrap().unwrap_err();
            assert!(failure.contains("timed out") || failure.contains("maximum running time"));
            assert!(failure.contains("Outcome unknown"));
            assert!(peer.join().unwrap().unwrap_err().contains("interrupted"));
        });
        assert!(first.status().unwrap().is_some());
        assert!(*first.terminal.lock().unwrap());
        assert!(state.process.lock().unwrap().is_none());
        let response = super::request_bridge_with(
            &app_handle,
            &state,
            serde_json::json!({
                "protocol": super::BRIDGE_PROTOCOL, "request_id": "replacement-ready",
                "operation": "bridge.handshake", "payload": {}
            }),
            spawn_opt_in_packaged,
            super::deadline_policy,
            || {},
        )
        .unwrap();
        assert_eq!(
            response.get("ok").and_then(serde_json::Value::as_bool),
            Some(true)
        );
        assert_eq!(state.next_generation.load(Ordering::SeqCst), 2);
        let mut process = state.process.lock().unwrap();
        super::shutdown_current(&mut process).unwrap();
    }

    #[test]
    fn only_idempotent_reads_are_candidates_for_one_replay() {
        assert!(operation_can_reopen_vault_and_replay(Some(
            "viva.surface.read"
        )));
        assert!(!operation_can_reopen_vault_and_replay(Some(
            "viva.documents.upload"
        )));
        assert!(!operation_can_reopen_vault_and_replay(Some(
            "bridge.open_vault"
        )));
        assert!(!can_replay_after_recovery(
            Some("bridge.open_vault"),
            Some(&ActiveVault::Sample)
        ));
        assert!(!can_replay_after_recovery(
            Some("viva.documents.upload"),
            Some(&ActiveVault::Sample)
        ));
        assert!(can_replay_after_recovery(
            Some("viva.surface.read"),
            Some(&ActiveVault::Sample)
        ));
        assert!(operation_may_have_written(Some("bridge.open_vault")));
        assert!(operation_may_have_written(Some("viva.documents.upload")));
        assert!(!operation_may_have_written(Some("viva.surface.read")));
        let claimed = AtomicBool::new(false);
        assert!(claim_read_recovery(&claimed));
        assert!(!claim_read_recovery(&claimed));
    }

    #[test]
    fn protected_recovery_is_bound_to_the_exact_active_private_vault() {
        let vault_b = ActiveVault::Private("/vault/b".to_string());
        assert!(protected_default_matches_active(&vault_b, "/vault/b"));
        assert!(!protected_default_matches_active(&vault_b, "/vault/a"));
        assert_eq!(recovery_directory_for(&vault_b), Some("/vault/b"));
        assert!(recovery_is_exact(&vault_b));
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
        assert!(recovery_is_exact(&ActiveVault::Sample));
        assert!(!recovery_is_exact(&ActiveVault::None));
    }

    #[test]
    fn deadline_classes_match_the_native_policy() {
        assert_eq!(
            deadline_policy(Some("viva.surface.read")).cap,
            Duration::from_secs(15)
        );
        assert_eq!(
            deadline_policy(Some("viva.settings.confirm")).cap,
            Duration::from_secs(30)
        );
        assert_eq!(
            deadline_policy(Some("bridge.open_vault")).cap,
            Duration::from_secs(60)
        );
        assert_eq!(
            deadline_policy(Some("viva.conversation.ask")).cap,
            Duration::from_secs(120)
        );
        assert_eq!(
            deadline_policy(Some("viva.vault.export")).cap,
            Duration::from_secs(600)
        );
        let recovery = deadline_policy(Some("viva.documents.recover"));
        assert_eq!(recovery.cap, Duration::from_secs(1800));
        assert!(operation_may_have_written(Some("viva.documents.recover")));
        let job = deadline_policy(Some("viva.documents.upload"));
        assert_eq!(job.first, Duration::from_secs(60));
        assert_eq!(job.silence, Duration::from_secs(120));
        assert_eq!(job.cap, Duration::from_secs(1800));
    }

    #[test]
    fn progress_is_correlated_and_extends_a_job_wait() {
        let pending: PendingCalls = Arc::new(Mutex::new(std::collections::HashMap::new()));
        let (first_sender, first_receiver) = mpsc::channel();
        let (second_sender, second_receiver) = mpsc::channel();
        pending
            .lock()
            .unwrap()
            .insert("one".to_string(), first_sender);
        pending
            .lock()
            .unwrap()
            .insert("two".to_string(), second_sender);
        route_pending(&pending, "one", RoutedFrame::Progress);
        route_pending(
            &pending,
            "one",
            RoutedFrame::Response(serde_json::json!({"request_id": "one"})),
        );
        let response = wait_for_response(
            first_receiver,
            super::DeadlinePolicy {
                first: Duration::from_millis(5),
                silence: Duration::from_millis(5),
                cap: Duration::from_millis(20),
            },
        )
        .unwrap();
        assert_eq!(response["request_id"], "one");
        assert!(second_receiver.try_recv().is_err());
        assert!(pending.lock().unwrap().contains_key("two"));
    }

    #[test]
    fn a_hung_request_releases_its_waiter_at_the_deadline() {
        let (_sender, receiver) = mpsc::channel();
        let started = Instant::now();
        let result = wait_for_response(
            receiver,
            super::DeadlinePolicy {
                first: Duration::from_millis(5),
                silence: Duration::from_millis(5),
                cap: Duration::from_millis(5),
            },
        );
        assert!(result.unwrap_err().contains("time"));
        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[cfg(unix)]
    #[test]
    fn a_hung_real_request_is_terminated_and_the_next_request_reaches_a_fresh_sidecar() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let state = BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::None,
                generation: 0,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        let first = serde_json::json!({
            "request_id": "first",
            "operation": "bridge.handshake",
            "payload": {}
        });
        let failure = super::request_bridge_with(
            app.handle(),
            &state,
            first,
            spawn_lifecycle_fake,
            lifecycle_test_policy,
            || {},
        )
        .unwrap_err();
        assert!(failure.contains("timed out"));
        assert!(
            state.process.lock().unwrap().is_none(),
            "hung sidecar was not terminated"
        );

        let second = serde_json::json!({
            "request_id": "second",
            "operation": "bridge.handshake",
            "payload": {}
        });
        let response = super::request_bridge_with(
            app.handle(),
            &state,
            second,
            spawn_lifecycle_fake,
            lifecycle_test_policy,
            || {},
        )
        .unwrap();
        assert_eq!(
            response.get("ok").and_then(serde_json::Value::as_bool),
            Some(true)
        );
        assert_eq!(LIFECYCLE_FAKE_SPAWNS.load(Ordering::SeqCst), 2);
    }

    #[cfg(unix)]
    #[test]
    fn explicit_shutdown_of_one_hung_generation_settles_peers_and_reaps_it() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let mut bridge = spawn_lifecycle_fake(app.handle()).unwrap();
        bridge.generation = 41;
        let peer_bridge = bridge.clone();
        let peer = thread::spawn(move || {
            super::request_process(
                &peer_bridge,
                "peer",
                "{\"request_id\":\"peer\"}",
                DeadlinePolicy {
                    first: Duration::from_secs(5),
                    silence: Duration::from_secs(5),
                    cap: Duration::from_secs(5),
                },
            )
        });
        thread::sleep(Duration::from_millis(10));
        let timed_out = super::request_process(
            &bridge,
            "owner",
            "{\"request_id\":\"owner\"}",
            lifecycle_test_policy(None),
        );
        assert!(timed_out.unwrap_err().contains("time"));
        bridge.shutdown().unwrap();
        assert!(peer.join().unwrap().unwrap_err().contains("interrupted"));
        assert!(bridge.pending.lock().unwrap().is_empty());
        assert!(bridge.status().unwrap().is_some(), "sidecar was not reaped");
    }

    #[cfg(unix)]
    #[test]
    fn output_eof_terminates_a_live_generation_and_settles_its_peer() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let mut child = Command::new("sh")
            .args(["-c", "sleep 0.1; exec 1>&-; exec sleep 3"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let pending = Arc::new(Mutex::new(std::collections::HashMap::new()));
        let closed = Arc::new(AtomicBool::new(false));
        let bridge = BridgeProcess {
            child: Arc::new(Mutex::new(Some(child))),
            stdin: Arc::new(Mutex::new(Some(stdin))),
            pending,
            closed,
            terminal: Arc::new(Mutex::new(false)),
            generation: 23,
        };
        let peer_bridge = bridge.clone();
        let peer = thread::spawn(move || {
            super::request_process(
                &peer_bridge,
                "waiting-peer",
                "{\"request_id\":\"waiting-peer\"}",
                DeadlinePolicy {
                    first: Duration::from_secs(5),
                    silence: Duration::from_secs(5),
                    cap: Duration::from_secs(5),
                },
            )
        });
        let reader_bridge = bridge.clone();
        let reader =
            thread::spawn(move || super::route_stdout(app.handle().clone(), stdout, reader_bridge));
        let peer_result = peer.join().unwrap().unwrap_err();
        assert!(peer_result.contains("closed its output") || peer_result.contains("interrupted"));
        reader.join().unwrap();
        assert!(bridge.closed.load(Ordering::SeqCst));
        assert!(*bridge.terminal.lock().unwrap());
        assert!(bridge.status().unwrap().is_some());
        let mut duplicate = bridge.clone();
        duplicate.shutdown().unwrap();
        assert!(bridge.pending.lock().unwrap().is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn child_crash_settles_all_inflight_peers_on_that_generation() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let mut child = Command::new("sh")
            .args(["-c", "sleep 0.1; IFS= read -r line; exit 7"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .unwrap();
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let bridge = BridgeProcess {
            child: Arc::new(Mutex::new(Some(child))),
            stdin: Arc::new(Mutex::new(Some(stdin))),
            pending: Arc::new(Mutex::new(std::collections::HashMap::new())),
            closed: Arc::new(AtomicBool::new(false)),
            terminal: Arc::new(Mutex::new(false)),
            generation: 24,
        };
        let reader_bridge = bridge.clone();
        let reader =
            thread::spawn(move || super::route_stdout(app.handle().clone(), stdout, reader_bridge));
        let peers = thread::scope(|scope| {
            let requests = ["crash-a", "crash-b"];
            let tasks = requests.map(|request_id| {
                let peer = bridge.clone();
                scope.spawn(move || {
                    super::request_process(
                        &peer,
                        request_id,
                        &format!("{{\"request_id\":\"{request_id}\"}}"),
                        DeadlinePolicy {
                            first: Duration::from_secs(5),
                            silence: Duration::from_secs(5),
                            cap: Duration::from_secs(5),
                        },
                    )
                })
            });
            tasks.map(|task| task.join().unwrap().unwrap_err())
        });
        reader.join().unwrap();
        assert!(peers
            .iter()
            .all(|error| { error.contains("closed its output") || error.contains("interrupted") }));
        assert!(bridge.closed.load(Ordering::SeqCst));
        assert!(*bridge.terminal.lock().unwrap());
        assert!(bridge.pending.lock().unwrap().is_empty());
        assert_eq!(bridge.status().unwrap().unwrap().code(), Some(7));
    }

    #[cfg(unix)]
    #[test]
    fn one_timeout_automatically_settles_a_blocked_jobs_read_on_the_same_generation() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let state = BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::None,
                generation: 0,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        let jobs = serde_json::json!({
            "request_id": "blocked-jobs",
            "operation": "viva.surface.read",
            "payload": {"surface": "jobs", "parameters": {}}
        });
        let app_handle = app.handle().clone();
        let peer =
            thread::scope(|scope| {
                let jobs = scope.spawn(|| {
                    super::request_bridge_with(
                        &app_handle,
                        &state,
                        jobs,
                        spawn_lifecycle_fake,
                        peer_deadline_policy,
                        || {},
                    )
                });
                let deadline = Instant::now() + Duration::from_secs(1);
                while state.process.lock().unwrap().as_ref().is_none_or(|bridge| {
                    !bridge.pending.lock().unwrap().contains_key("blocked-jobs")
                }) {
                    assert!(Instant::now() < deadline);
                    thread::sleep(Duration::from_millis(1));
                }
                let old = state.process.lock().unwrap().as_ref().unwrap().clone();
                let owner = serde_json::json!({
                    "request_id": "timed-out-active",
                    "operation": "bridge.handshake",
                    "payload": {}
                });
                let failure = super::request_bridge_with(
                    &app_handle,
                    &state,
                    owner,
                    spawn_lifecycle_fake,
                    peer_deadline_policy,
                    || {},
                )
                .unwrap_err();
                assert!(failure.contains("timed out"));
                (jobs.join().unwrap().unwrap_err(), old)
            });
        assert!(peer.0.contains("interrupted"));
        assert!(peer.1.status().unwrap().is_some());
        assert!(state.process.lock().unwrap().is_none());
        assert_eq!(LIFECYCLE_FAKE_SPAWNS.load(Ordering::SeqCst), 1);
    }

    #[cfg(unix)]
    #[test]
    fn timed_out_write_reports_unknown_outcome_without_spawning_a_replay() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let state = BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::Sample,
                generation: 1,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        let failure = super::request_bridge_with(
            app.handle(),
            &state,
            serde_json::json!({
                "request_id": "uncertain-upload",
                "operation": "viva.documents.upload",
                "payload": {"path": "synthetic.pdf"}
            }),
            spawn_lifecycle_fake,
            lifecycle_test_policy,
            || {},
        )
        .unwrap_err();
        assert!(failure.contains("Outcome unknown"));
        assert_eq!(LIFECYCLE_FAKE_SPAWNS.load(Ordering::SeqCst), 1);
        assert!(state.process.lock().unwrap().is_none());
    }

    #[cfg(unix)]
    #[test]
    fn replacement_waits_for_one_exact_reopen_before_priority_and_jobs_reads() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let app_handle = app.handle().clone();
        let mut first = spawn_recovery_fake(&app_handle).unwrap();
        first.generation = 1;
        let state = BridgeState {
            process: Mutex::new(Some(first)),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::Sample,
                generation: 1,
            }),
            next_generation: AtomicUsize::new(1),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        thread::scope(|scope| {
            let (claimed_tx, claimed_rx) = mpsc::channel();
            let (release_tx, release_rx) = mpsc::channel();
            let state_ref = &state;
            let handle_ref = &app_handle;
            let jobs = scope.spawn(move || {
                super::request_bridge_with(
                    handle_ref,
                    state_ref,
                    serde_json::json!({
                        "request_id": "old-jobs",
                        "operation": "viva.surface.read",
                        "payload": {"surface": "jobs", "parameters": {}}
                    }),
                    spawn_recovery_fake,
                    peer_deadline_policy,
                    || {
                        claimed_tx.send(()).unwrap();
                        release_rx.recv().unwrap();
                    },
                )
            });
            let deadline = Instant::now() + Duration::from_secs(1);
            while state
                .process
                .lock()
                .unwrap()
                .as_ref()
                .is_none_or(|bridge| !bridge.pending.lock().unwrap().contains_key("old-jobs"))
            {
                assert!(Instant::now() < deadline);
                thread::sleep(Duration::from_millis(1));
            }
            let owner_failure = super::request_bridge_with(
                &app_handle,
                &state,
                serde_json::json!({
                    "request_id": "owner-timeout",
                    "operation": "bridge.handshake",
                    "payload": {}
                }),
                spawn_recovery_fake,
                peer_deadline_policy,
                || {},
            )
            .unwrap_err();
            assert!(owner_failure.contains("timed out"));
            claimed_rx.recv_timeout(Duration::from_secs(1)).unwrap();
            let priority = scope.spawn(move || {
                super::request_bridge_with(
                    handle_ref,
                    state_ref,
                    serde_json::json!({
                        "request_id": "new-priority",
                        "operation": "viva.surface.read",
                        "payload": {"surface": "overview_accounts", "parameters": {}}
                    }),
                    spawn_recovery_fake,
                    peer_deadline_policy,
                    || {},
                )
            });
            thread::sleep(Duration::from_millis(50));
            assert!(!priority.is_finished());
            release_tx.send(()).unwrap();
            let priority = priority.join().unwrap().unwrap();
            assert_eq!(
                priority.get("ok").and_then(serde_json::Value::as_bool),
                Some(true)
            );
            let secondary = super::request_bridge_with(
                &app_handle,
                &state,
                serde_json::json!({
                    "request_id": "new-secondary",
                    "operation": "viva.surface.read",
                    "payload": {"surface": "activity", "parameters": {}}
                }),
                spawn_recovery_fake,
                peer_deadline_policy,
                || {},
            )
            .unwrap();
            assert_eq!(
                secondary.get("ok").and_then(serde_json::Value::as_bool),
                Some(true)
            );
            assert_eq!(
                jobs.join()
                    .unwrap()
                    .unwrap()
                    .get("ok")
                    .and_then(serde_json::Value::as_bool),
                Some(true)
            );
        });
        assert_eq!(LIFECYCLE_FAKE_SPAWNS.load(Ordering::SeqCst), 2);
        assert_eq!(state.active_vault.lock().unwrap().generation, 2);
        state.shutdown().unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn old_supervisor_failure_cannot_clear_identity_recovered_in_the_cleanup_gap() {
        let _serial = LIFECYCLE_FAKE_LOCK.lock().unwrap();
        LIFECYCLE_FAKE_SPAWNS.store(0, Ordering::SeqCst);
        let app = tauri::test::mock_builder()
            .build(tauri::test::mock_context(tauri::test::noop_assets()))
            .unwrap();
        let state = BridgeState {
            process: Mutex::new(None),
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::Private("/old".to_string()),
                generation: 1,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
        };
        let request = serde_json::json!({
            "request_id": "old-open",
            "operation": "bridge.open_vault",
            "payload": { "vault_directory": "/old", "passphrase": "unused", "create": false }
        });
        let failure = super::request_bridge_with(
            app.handle(),
            &state,
            request,
            spawn_lifecycle_fake,
            lifecycle_test_policy,
            || {
                *state.active_vault.lock().unwrap() = ActiveVaultRecord {
                    vault: ActiveVault::Private("/exact/recovered".to_string()),
                    generation: 2,
                };
            },
        )
        .unwrap_err();
        assert!(failure.contains("Outcome unknown"));
        assert_eq!(
            state.active_vault.lock().unwrap().clone(),
            ActiveVaultRecord {
                vault: ActiveVault::Private("/exact/recovered".to_string()),
                generation: 2,
            }
        );
    }

    #[test]
    fn a_late_failed_peer_cannot_erase_recovered_exact_vault_state() {
        let active = Arc::new(Mutex::new(ActiveVaultRecord {
            vault: ActiveVault::Private("/old".to_string()),
            generation: 1,
        }));
        let recovered = Arc::clone(&active);
        let late = Arc::clone(&active);
        let (recovery_done, observe_recovery) = mpsc::channel();
        let recovery = thread::spawn(move || {
            *recovered.lock().unwrap() = ActiveVaultRecord {
                vault: ActiveVault::Private("/exact/recovered".to_string()),
                generation: 2,
            };
            recovery_done.send(()).unwrap();
        });
        let late_failure = thread::spawn(move || {
            observe_recovery.recv().unwrap();
            super::clear_active_vault_after_failure(&late, 1).unwrap();
        });
        recovery.join().unwrap();
        late_failure.join().unwrap();
        assert_eq!(
            active.lock().unwrap().vault,
            ActiveVault::Private("/exact/recovered".to_string())
        );
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
fn bridge_restart(app: AppHandle, state: State<'_, BridgeState>) -> Result<(), String> {
    state.restart(&app)
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
            active_vault: Mutex::new(ActiveVaultRecord {
                vault: ActiveVault::None,
                generation: 0,
            }),
            next_generation: AtomicUsize::new(0),
            read_recovery_claimed: AtomicBool::new(false),
            recovery_gate: RecoveryGate::new(),
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
