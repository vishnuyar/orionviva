use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::State;

struct BridgeProcess {
    _child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

struct BridgeState(Mutex<Option<BridgeProcess>>);

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
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "bridge stdin was not available".to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "bridge stdout was not available".to_string())?;

    Ok(BridgeProcess {
        _child: child,
        stdin,
        stdout: BufReader::new(stdout),
    })
}

fn request_bridge(state: &BridgeState, frame: Value) -> Result<Value, String> {
    let request_id = frame
        .get("request_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "bridge request_id is required".to_string())?
        .to_string();
    let encoded = serde_json::to_string(&frame).map_err(|error| error.to_string())?;
    let mut process = state.0.lock().map_err(|_| "bridge state poisoned".to_string())?;
    if process.is_none() {
        *process = Some(spawn_bridge()?);
    }
    let bridge = process.as_mut().expect("bridge process initialized");
    writeln!(bridge.stdin, "{encoded}").map_err(|error| format!("bridge write failed: {error}"))?;
    bridge
        .stdin
        .flush()
        .map_err(|error| format!("bridge flush failed: {error}"))?;

    let mut line = String::new();
    loop {
        line.clear();
        let read = bridge
            .stdout
            .read_line(&mut line)
            .map_err(|error| format!("bridge read failed: {error}"))?;
        if read == 0 {
            *process = None;
            return Err("bridge exited before responding".to_string());
        }
        let response: Value = serde_json::from_str(line.trim())
            .map_err(|error| format!("bridge returned invalid JSON: {error}"))?;
        if response.get("request_id").and_then(Value::as_str) == Some(request_id.as_str())
            && response.get("event").is_none()
        {
            return Ok(response);
        }
    }
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
    serde_json::to_string(&response).map_err(|error| format!("bridge response failed: {error}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BridgeState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![bridge_request])
        .run(tauri::generate_context!())
        .expect("error while running OrionViva");
}

fn main() {
    run();
}
