use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio};
use std::sync::{Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::{Manager, RunEvent, State};

const BRIDGE_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
const BRIDGE_SHUTDOWN_POLL_INTERVAL: Duration = Duration::from_millis(25);

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

struct BridgeState(Mutex<Option<BridgeProcess>>);

impl BridgeState {
    fn lock(&self) -> Result<MutexGuard<'_, Option<BridgeProcess>>, String> {
        self.0
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

fn spawn_bridge() -> Result<BridgeProcess, String> {
    // Development uses the repository's Python module. Packaging can provide
    // an executable path through ORIONVIVA_SIDECAR without changing the UI.
    let mut command = if let Ok(path) = std::env::var("ORIONVIVA_SIDECAR") {
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
        if response.get("request_id").and_then(Value::as_str) == Some(request_id)
            && response.get("event").is_none()
        {
            return Ok(response);
        }
    }
}

fn request_bridge(state: &BridgeState, frame: Value) -> Result<Value, String> {
    let request_id = frame
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "bridge request_id is required".to_string())?
        .to_string();
    let encoded = serde_json::to_string(&frame)
        .map_err(|error| format!("unable to encode OrionViva bridge request: {error}"))?;
    let may_recover = matches!(
        frame.get("operation").and_then(Value::as_str),
        Some("bridge.open_vault" | "viva.surface.read")
    );
    let mut process = state.lock()?;

    for attempt in 0..2 {
        let result = request_process(ensure_bridge(&mut process)?, &request_id, &encoded);
        match result {
            Ok(response) => return Ok(response),
            Err(error) => {
                let cleanup_error = shutdown_current(&mut process).err();
                if cleanup_error.is_none() && may_recover && attempt == 0 {
                    continue;
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

#[tauri::command]
fn bridge_request(state: State<'_, BridgeState>, frame: String) -> Result<String, String> {
    let mut request: Value = serde_json::from_str(&frame)
        .map_err(|error| format!("invalid bridge request: {error}"))?;
    let object = request
        .as_object_mut()
        .ok_or_else(|| "bridge request must be an object".to_string())?;
    object.entry("protocol").or_insert_with(|| json!("1.0"));
    let response = request_bridge(&state, request)?;
    serde_json::to_string(&response)
        .map_err(|error| format!("unable to encode OrionViva bridge response: {error}"))
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
        .manage(BridgeState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            bridge_request,
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
