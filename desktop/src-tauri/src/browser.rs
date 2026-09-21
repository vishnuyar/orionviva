use serde_json::{json, Value};
use std::collections::VecDeque;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_dialog::DialogExt;

const MAX_BODY: usize = 2 * 1024 * 1024;
const MAX_HEADERS: usize = 16 * 1024;
const CSP: &str = "default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'";

#[derive(Default)]
pub struct Session {
    pub active: bool,
    revoked: bool,
    launch: String,
    token: String,
    page: String,
    operations: usize,
    bridge_operations: usize,
    switching: bool,
    vault_epoch: u64,
    sequence: u64,
    events: VecDeque<(u64, Value)>,
}

pub struct BrowserState {
    pub vault_closed: std::sync::atomic::AtomicBool,
    pub session: Arc<Mutex<Session>>,
    port: Mutex<Option<u16>>,
    remember: bool,
    #[cfg(test)]
    test_selections: Option<(String, String)>,
}

impl Default for BrowserState {
    fn default() -> Self {
        Self {
            vault_closed: std::sync::atomic::AtomicBool::new(false),
            session: Arc::new(Mutex::new(Session::default())),
            port: Mutex::new(None),
            remember: cfg!(any(target_os = "macos", target_os = "windows")),
            #[cfg(test)]
            test_selections: None,
        }
    }
}

pub struct Permit(Arc<Mutex<Session>>, bool);
impl Drop for Permit {
    fn drop(&mut self) {
        if let Ok(mut session) = self.0.lock() {
            session.operations -= 1;
            if self.1 {
                session.switching = false;
            }
            if session.operations == 0 && session.revoked {
                *session = Session::default();
            }
        }
    }
}

struct VaultPermit {
    session: Arc<Mutex<Session>>,
    epoch: u64,
    switching: bool,
}
impl Drop for VaultPermit {
    fn drop(&mut self) {
        if let Ok(mut session) = self.session.lock() {
            session.bridge_operations -= 1;
            if self.switching {
                session.switching = false;
            }
        }
    }
}

fn secret() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes)
        .map_err(|_| "Secure browser access could not be created".to_string())?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

impl BrowserState {
    pub fn enter_close(&self) -> Result<Permit, String> {
        let mut session = self.session.lock().map_err(|_| "Browser unavailable")?;
        if session.active || session.operations != 0 || session.switching {
            return Err("OrionViva is still finishing a request".into());
        }
        session.switching = true;
        session.operations += 1;
        Ok(Permit(self.session.clone(), true))
    }

    pub fn enter(&self, token: Option<&str>) -> Result<Permit, String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        let allowed = match token {
            Some(token) => session.active && !session.token.is_empty() && token == session.token,
            None => !session.active && !session.switching,
        };
        if !allowed {
            return Err(
                "This window no longer controls OrionViva. Return to the app to continue.".into(),
            );
        }
        session.operations += 1;
        Ok(Permit(self.session.clone(), false))
    }

    pub fn progress(&self, frame: &Value) {
        if let Ok(mut session) = self.session.lock() {
            if !session.active {
                return;
            }
            session.sequence += 1;
            let sequence = session.sequence;
            session.events.push_back((sequence, frame.clone()));
            while session.events.len() > 2048 {
                session.events.pop_front();
            }
        }
    }

    fn events(&self, after: u64, epoch: u64) -> Result<Value, String> {
        let session = self.session.lock().map_err(|_| "Browser unavailable")?;
        let lost = epoch == session.vault_epoch
            && session
                .events
                .front()
                .is_some_and(|(seq, _)| after.saturating_add(1) < *seq);
        Ok(
            json!({"vault_epoch": session.vault_epoch, "sequence": session.sequence,
            "lost": lost, "frames": session.events.iter().filter(|(seq, _)| *seq > after)
                .map(|(_, frame)| frame).collect::<Vec<_>>() }),
        )
    }

    fn enter_vault(&self, expected: u64, switching: bool) -> Result<VaultPermit, String> {
        let mut session = self.session.lock().map_err(|_| "Browser unavailable")?;
        if expected != session.vault_epoch
            || session.switching
            || (switching && session.bridge_operations != 0)
        {
            return Err(
                "The vault changed or is still finishing a request. Reopen it before trying again."
                    .into(),
            );
        }
        session.bridge_operations += 1;
        if switching {
            session.vault_epoch += 1;
            session.switching = true;
            session.events.clear();
        }
        Ok(VaultPermit {
            session: self.session.clone(),
            epoch: session.vault_epoch,
            switching,
        })
    }

    fn activate(&self) -> Result<String, String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        if session.operations != 0 {
            return Err(
                "OrionViva is finishing a request. Try opening the browser again when it finishes."
                    .into(),
            );
        }
        if session.active {
            return Err(
                "Browser access is already active. Stop it before opening another window.".into(),
            );
        }
        let launch = secret()?;
        *session = Session {
            active: true,
            launch: launch.clone(),
            ..Session::default()
        };
        Ok(launch)
    }

    fn claim(&self, launch: &str, page: &str) -> Result<String, String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        if !session.active
            || page.is_empty()
            || page.len() > 128
            || launch.is_empty()
            || session.launch != launch
        {
            return Err("Browser launch has expired".into());
        }
        let token = secret()?;
        session.launch.clear();
        session.token = token.clone();
        session.page = page.to_string();
        Ok(token)
    }

    fn enter_page(&self, token: &str, page: &str) -> Result<Permit, String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        if !session.active
            || token.is_empty()
            || token != session.token
            || page.is_empty()
            || page != session.page
        {
            return Err("Browser access has ended".into());
        }
        session.operations += 1;
        Ok(Permit(self.session.clone(), false))
    }

    fn resume(&self, token: &str, page: &str) -> Result<(), String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        if !session.active
            || token.is_empty()
            || token != session.token
            || !session.page.is_empty()
            || page.is_empty()
            || page.len() > 128
        {
            return Err("Another browser tab is active, or browser access has ended".into());
        }
        session.page = page.to_string();
        Ok(())
    }

    fn release(&self, token: &str, page: &str) {
        if let Ok(mut session) = self.session.lock() {
            if !token.is_empty()
                && token == session.token
                && !page.is_empty()
                && page == session.page
            {
                session.page.clear();
            }
        }
    }

    fn finish(&self) -> Result<(), String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        if session.operations != 0 {
            return Err("OrionViva is finishing a request. Wait for it to finish before returning to desktop.".into());
        }
        *session = Session::default();
        Ok(())
    }
    fn revoke(&self) -> Result<(), String> {
        let mut session = self
            .session
            .lock()
            .map_err(|_| "Browser session unavailable")?;
        session.launch.clear();
        session.token.clear();
        session.page.clear();
        session.events.clear();
        session.revoked = true;
        if session.operations == 0 {
            *session = Session::default();
        }
        Ok(())
    }
}

#[tauri::command]
pub fn browser_status(state: tauri::State<'_, BrowserState>) -> bool {
    state
        .session
        .lock()
        .map(|session| session.active)
        .unwrap_or(true)
}

#[tauri::command]
pub async fn browser_start(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || start(&app))
        .await
        .map_err(|_| "Browser launch failed".to_string())?
}

fn start(app: &AppHandle) -> Result<(), String> {
    if app.asset_resolver().get("loopback.html".into()).is_none() {
        return Err("This build is missing its browser interface. Build or reinstall OrionViva before trying again.".into());
    }
    let state = app.state::<BrowserState>();
    let mut port = state
        .port
        .lock()
        .map_err(|_| "Browser service unavailable")?;
    let listener = if port.is_none() {
        Some(
            TcpListener::bind(("127.0.0.1", 0))
                .map_err(|_| "The local browser connection could not be opened")?,
        )
    } else {
        None
    };
    let launch = state.activate()?;
    if let Some(listener) = listener {
        let bound_port = listener
            .local_addr()
            .map_err(|_| "Browser address unavailable")?
            .port();
        *port = Some(bound_port);
        let app = app.clone();
        std::thread::spawn(move || serve(app, listener, bound_port));
    }
    let url = format!(
        "http://127.0.0.1:{}/loopback.html#launch={launch}",
        port.unwrap()
    );
    if open_browser(&url).is_err() {
        let _ = state.finish();
        return Err(
            "The browser could not be opened. Check your default browser and try again.".into(),
        );
    }
    let _ = app.emit("orionviva://browser-mode", true);
    Ok(())
}

#[tauri::command]
pub fn browser_stop(app: AppHandle, state: tauri::State<'_, BrowserState>) -> Result<(), String> {
    state.revoke()?;
    let active = state
        .session
        .lock()
        .map_err(|_| "Browser unavailable")?
        .active;
    let _ = app.emit("orionviva://browser-mode", active);
    Ok(())
}

#[tauri::command]
pub fn browser_return(app: AppHandle, state: tauri::State<'_, BrowserState>) -> Result<(), String> {
    state.finish()?;
    let _ = app.emit("orionviva://browser-mode", false);
    Ok(())
}

fn open_browser(url: &str) -> std::io::Result<()> {
    #[cfg(target_os = "macos")]
    let mut command = std::process::Command::new("/usr/bin/open");
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut c = std::process::Command::new("rundll32.exe");
        c.arg("url.dll,FileProtocolHandler");
        c
    };
    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let mut command = std::process::Command::new("xdg-open");
    command
        .arg(url)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    if command.status()?.success() {
        Ok(())
    } else {
        Err(std::io::Error::other("browser launch failed"))
    }
}

struct Request {
    method: String,
    path: String,
    host: String,
    origin: Option<String>,
    authorization: String,
    page: String,
    body: Vec<u8>,
}

fn read_request(stream: &mut TcpStream) -> Result<Request, ()> {
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .map_err(|_| ())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(5)))
        .map_err(|_| ())?;
    let mut bytes = Vec::new();
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    loop {
        if bytes.len() >= MAX_HEADERS || std::time::Instant::now() > deadline {
            return Err(());
        }
        let mut chunk = [0u8; 1024];
        let count = stream.read(&mut chunk).map_err(|_| ())?;
        if count == 0 {
            return Err(());
        }
        bytes.extend_from_slice(&chunk[..count]);
        let mut headers = [httparse::EMPTY_HEADER; 48];
        let mut parsed = httparse::Request::new(&mut headers);
        let httparse::Status::Complete(offset) = parsed.parse(&bytes).map_err(|_| ())? else {
            continue;
        };
        let header = |name: &str| -> Result<Option<String>, ()> {
            let values: Vec<_> = parsed
                .headers
                .iter()
                .filter(|h| h.name.eq_ignore_ascii_case(name))
                .collect();
            if values.len() > 1 {
                return Err(());
            }
            values
                .first()
                .map(|h| {
                    std::str::from_utf8(h.value)
                        .map(str::to_string)
                        .map_err(|_| ())
                })
                .transpose()
        };
        if header("transfer-encoding")?.is_some() {
            return Err(());
        }
        let length = header("content-length")?
            .unwrap_or_else(|| "0".into())
            .parse::<usize>()
            .map_err(|_| ())?;
        if length > MAX_BODY {
            return Err(());
        }
        let mut request = Request {
            method: parsed.method.ok_or(())?.into(),
            path: parsed.path.ok_or(())?.into(),
            host: header("host")?.ok_or(())?,
            origin: header("origin")?,
            authorization: header("authorization")?.unwrap_or_default(),
            page: header("x-orionviva-page")?.unwrap_or_default(),
            body: Vec::new(),
        };
        while bytes.len() < offset + length {
            if std::time::Instant::now() > deadline {
                return Err(());
            }
            let count = stream.read(&mut chunk).map_err(|_| ())?;
            if count == 0 {
                return Err(());
            }
            bytes.extend_from_slice(&chunk[..count]);
        }
        if bytes.len() != offset + length {
            return Err(());
        }
        request.body.extend_from_slice(&bytes[offset..]);
        return Ok(request);
    }
}

fn respond(stream: &mut TcpStream, status: u16, content_type: &str, body: &[u8]) {
    let header = format!("HTTP/1.1 {status} Response\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nContent-Security-Policy: {CSP}\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\nCross-Origin-Resource-Policy: same-origin\r\nConnection: close\r\n\r\n", body.len());
    let _ = stream
        .write_all(header.as_bytes())
        .and_then(|_| stream.write_all(body));
}

fn valid_boundary(request: &Request, port: u16) -> bool {
    let host = format!("127.0.0.1:{port}");
    request.host == host
        && request
            .origin
            .as_ref()
            .is_none_or(|origin| origin == &format!("http://{host}"))
        && (request.method != "POST" || request.origin.is_some())
}

fn serve<R: tauri::Runtime>(app: AppHandle<R>, listener: TcpListener, port: u16) {
    let connections = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    for stream in listener.incoming() {
        let Ok(mut stream) = stream else { break };
        if connections.fetch_add(1, std::sync::atomic::Ordering::SeqCst) >= 24 {
            connections.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
            respond(&mut stream, 503, "text/plain", b"Busy");
            continue;
        }
        let app = app.clone();
        let connections = connections.clone();
        std::thread::spawn(move || {
            handle(&app, &mut stream, port);
            connections.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
        });
    }
}

fn handle<R: tauri::Runtime>(app: &AppHandle<R>, stream: &mut TcpStream, port: u16) {
    let Ok(request) = read_request(stream) else {
        respond(stream, 400, "text/plain", b"Invalid request");
        return;
    };
    if !valid_boundary(&request, port) {
        respond(stream, 403, "text/plain", b"Forbidden");
        return;
    }
    if request.method == "GET"
        && (request.path == "/loopback.html" || request.path.starts_with("/assets/"))
    {
        if request.path.contains("..")
            || request.path.contains('%')
            || request.path.contains('\\')
            || request.path.contains('?')
        {
            respond(stream, 404, "text/plain", b"Not found");
            return;
        }
        if let Some(asset) = app
            .asset_resolver()
            .get(request.path.trim_start_matches('/').into())
        {
            respond(stream, 200, &asset.mime_type, &asset.bytes);
        } else {
            respond(stream, 404, "text/plain", b"Not found");
        }
        return;
    }
    if request.method != "POST" {
        respond(stream, 405, "text/plain", b"Method not allowed");
        return;
    }
    let Ok(body) = serde_json::from_slice::<Value>(&request.body) else {
        respond(stream, 400, "text/plain", b"Invalid request");
        return;
    };
    let state = app.state::<BrowserState>();
    if request.path == "/__orionviva/claim" {
        match state.claim(
            body.get("launch")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            body.get("page").and_then(Value::as_str).unwrap_or_default(),
        ) {
            Ok(token) => respond(
                stream,
                200,
                "application/json",
                json!({"token": token}).to_string().as_bytes(),
            ),
            Err(_) => respond(stream, 403, "text/plain", b"Browser launch has expired"),
        }
        return;
    }
    if request.path == "/__orionviva/release" {
        state.release(
            body.get("token")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            body.get("page").and_then(Value::as_str).unwrap_or_default(),
        );
        respond(stream, 200, "application/json", b"null");
        return;
    }
    let token = request
        .authorization
        .strip_prefix("Bearer ")
        .unwrap_or_default();
    if request.path == "/__orionviva/resume" {
        let status = if state.resume(token, &request.page).is_ok() {
            200
        } else {
            409
        };
        respond(stream, status, "application/json", b"null");
        return;
    }
    let Ok(_permit) = state.enter_page(token, &request.page) else {
        respond(stream, 403, "text/plain", b"Browser access has ended");
        return;
    };
    let vault_permit = if matches!(
        request.path.as_str(),
        "/__orionviva/bridge" | "/__orionviva/current" | "/__orionviva/close"
    ) {
        let switching = request.path.ends_with("/close")
            || matches!(
                body.pointer("/frame/operation").and_then(Value::as_str),
                Some("bridge.open_vault" | "bridge.open_demo_vault")
            );
        match body
            .get("vault_epoch")
            .and_then(Value::as_u64)
            .and_then(|expected| state.enter_vault(expected, switching).ok())
        {
            Some(permit) => Some(permit),
            None => {
                respond(
                    stream,
                    409,
                    "application/json",
                    json!({"error": if request.path.ends_with("/current") { "vault_busy" } else { "vault_changed" }, "vault_epoch": state.session.lock().unwrap().vault_epoch}).to_string().as_bytes(),
                );
                return;
            }
        }
    } else {
        None
    };
    let result = dispatch(app, &request.path, body);
    let epoch = vault_permit.as_ref().map(|permit| permit.epoch);
    drop(vault_permit);
    if state.enter_page(token, &request.page).is_err() {
        respond(stream, 403, "text/plain", b"Browser access has ended");
        return;
    }
    match result {
        Ok(result) => {
            let result = if let Some(epoch) = epoch {
                json!({"response": result, "vault_epoch": epoch})
            } else {
                result
            };
            respond(
                stream,
                200,
                "application/json",
                result.to_string().as_bytes(),
            );
        }
        Err(error) => {
            let uncertain = error.contains("timed out")
                || error.contains("maximum running time")
                || error.contains("interrupted")
                || error.contains("Outcome unknown");
            respond(stream, 502, "application/json", json!({"vault_epoch": epoch, "error": if uncertain { "outcome_unknown" } else { "request_failed" }}).to_string().as_bytes());
        }
    }
}

fn dispatch<R: tauri::Runtime>(
    app: &AppHandle<R>,
    path: &str,
    body: Value,
) -> Result<Value, String> {
    match path {
        "/__orionviva/close" => {
            super::close_active_vault(app)?;
            Ok(Value::Null)
        }
        "/__orionviva/bridge" => super::request_bridge(
            app,
            &app.state::<super::BridgeState>(),
            body.get("frame").cloned().ok_or("Frame required")?,
        ),
        "/__orionviva/current" => {
            let active = app.state::<super::BridgeState>();
            let active = active
                .active_vault
                .lock()
                .map_err(|_| "Vault unavailable")?;
            Ok(match &active.vault {
                super::ActiveVault::Private(directory) => {
                    json!({"state": "opened", "directory": directory})
                }
                _ => json!({"state": "absent"}),
            })
        }
        "/__orionviva/remember" => {
            if !app.state::<BrowserState>().remember {
                return Err("Remembering is unavailable".into());
            }
            let state = app.state::<BrowserState>();
            let _vault = state.enter_vault(
                body.get("vault_epoch")
                    .and_then(Value::as_u64)
                    .ok_or("Vault required")?,
                false,
            )?;
            let directory = body
                .get("directory")
                .and_then(Value::as_str)
                .filter(|s| !s.trim().is_empty())
                .ok_or("Directory required")?;
            let passphrase = body
                .get("passphrase")
                .and_then(Value::as_str)
                .filter(|s| !s.is_empty())
                .ok_or("Vaultphrase required")?;
            super::store_remembered_vault(directory, passphrase)?;
            Ok(Value::Null)
        }
        "/__orionviva/capabilities" => {
            let state = app.state::<BrowserState>();
            let session = state.session.lock().map_err(|_| "Browser unavailable")?;
            Ok(
                json!({"remember": state.remember, "vault_epoch": session.vault_epoch, "sequence": session.sequence}),
            )
        }
        "/__orionviva/pick-folder" | "/__orionviva/pick-file" => {
            #[cfg(test)]
            if let Some((folder, file)) = &app.state::<BrowserState>().test_selections {
                return Ok(json!(if path.ends_with("pick-folder") {
                    folder
                } else {
                    file
                }));
            }
            let picker = app.dialog().file();
            let selected = if path.ends_with("pick-folder") {
                picker
                    .set_title("Choose an OrionViva vault folder")
                    .blocking_pick_folder()
            } else {
                picker
                    .set_title("Choose a file for OrionViva")
                    .blocking_pick_file()
            };
            let selected = selected
                .map(|p| {
                    p.into_path()
                        .map(|p| p.to_string_lossy().into_owned())
                        .map_err(|_| "Local file required".to_string())
                })
                .transpose()?;
            Ok(json!(selected))
        }
        "/__orionviva/events" => {
            let state = app.state::<BrowserState>();
            let after = body.get("after").and_then(Value::as_u64).unwrap_or(0);
            state.events(
                after,
                body.get("vault_epoch")
                    .and_then(Value::as_u64)
                    .ok_or("Epoch required")?,
            )
        }
        _ => Err("Unknown browser operation".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_desktop_close_excludes_peer_requests_and_handoff() {
        let state = BrowserState::default();
        let request = state.enter(None).unwrap();
        assert!(state.enter_close().is_err());
        drop(request);
        let closing = state.enter_close().unwrap();
        assert!(state.enter(None).is_err());
        assert!(state.activate().is_err());
        drop(closing);
        assert!(state.enter(None).is_ok());
    }
    #[test]
    fn progress_cursor_distinguishes_overflow_from_a_new_vault_or_reload() {
        let state = BrowserState::default();
        state.activate().unwrap();
        for _ in 0..2050 {
            state.progress(&json!({"request_id": "page:job"}));
        }
        assert_eq!(state.events(0, 0).unwrap()["lost"], true);
        let baseline = state.session.lock().unwrap().sequence;
        assert_eq!(state.events(baseline, 0).unwrap()["lost"], false);
        drop(state.enter_vault(0, true).unwrap());
        state.progress(&json!({"request_id": "page:new-job"}));
        let result = state.events(0, 0).unwrap();
        assert_eq!(result["lost"], false);
        assert_eq!(result["vault_epoch"], 1);
        assert_eq!(result["frames"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn session_claim_is_single_use_and_revocation_rejects_old_tokens() {
        let state = BrowserState::default();
        let launch = state.activate().unwrap();
        assert!(state.enter(None).is_err());
        assert!(state.enter(Some("")).is_err());
        assert!(state.claim("wrong", "page").is_err());
        let token = state.claim(&launch, "page").unwrap();
        assert!(state.claim(&launch, "page").is_err());
        let permit = state.enter(Some(&token)).unwrap();
        assert!(state.finish().is_err());
        drop(permit);
        state.finish().unwrap();
        assert!(state.enter(Some(&token)).is_err());
        assert!(state.enter(None).is_ok());
    }
    #[test]
    fn desktop_requests_prevent_handoff_until_settled() {
        let state = BrowserState::default();
        let permit = state.enter(None).unwrap();
        assert!(state.activate().is_err());
        drop(permit);
        assert!(state.activate().is_ok());
    }
    #[test]
    fn request_boundary_rejects_dns_rebinding_missing_and_foreign_origins() {
        let mut request = Request {
            method: "POST".into(),
            path: "/__orionviva/bridge".into(),
            host: "127.0.0.1:1234".into(),
            origin: Some("http://127.0.0.1:1234".into()),
            authorization: String::new(),
            page: String::new(),
            body: vec![],
        };
        assert!(valid_boundary(&request, 1234));
        request.origin = None;
        assert!(!valid_boundary(&request, 1234));
        request.origin = Some("https://example.invalid".into());
        assert!(!valid_boundary(&request, 1234));
        request.origin = Some("http://127.0.0.1:1234".into());
        request.host = "example.invalid:1234".into();
        assert!(!valid_boundary(&request, 1234));
    }
    #[test]
    fn progress_is_cleared_when_control_returns_to_desktop() {
        let state = BrowserState::default();
        state.activate().unwrap();
        state.progress(&json!({"event": "progress", "request_id": "one"}));
        assert_eq!(state.session.lock().unwrap().events.len(), 1);
        state.finish().unwrap();
        assert!(state.session.lock().unwrap().events.is_empty());
    }
    #[test]
    fn duplicate_tab_reload_cannot_claim_an_owned_page() {
        let state = BrowserState::default();
        let launch = state.activate().unwrap();
        let token = state.claim(&launch, "original").unwrap();
        assert!(state.enter_page(&token, "duplicate").is_err());
        assert!(state.resume(&token, "duplicate").is_err());
        state.release(&token, "duplicate");
        assert!(state.resume(&token, "duplicate").is_err());
        state.release(&token, "original");
        state.resume(&token, "reloaded").unwrap();
        assert!(state.enter_page(&token, "original").is_err());
        assert!(state.enter_page(&token, "reloaded").is_ok());
    }

    #[test]
    fn revocation_is_immediate_while_admitted_work_drains() {
        let state = BrowserState::default();
        let launch = state.activate().unwrap();
        let token = state.claim(&launch, "original").unwrap();
        let request = state.enter_page(&token, "original").unwrap();
        state.revoke().unwrap();
        assert!(state.enter_page(&token, "original").is_err());
        assert!(state.enter(None).is_err());
        assert!(state.activate().is_err());
        drop(request);
        assert!(state.enter(None).is_ok());
        assert!(state.enter_page(&token, "original").is_err());
    }

    #[test]
    fn delayed_mutation_cannot_cross_a_vault_switch() {
        let state = BrowserState::default();
        let old_read = state.enter_vault(0, false).unwrap();
        assert!(state.enter_vault(0, true).is_err());
        drop(old_read);
        let switch = state.enter_vault(0, true).unwrap();
        assert!(state.enter_vault(0, false).is_err());
        assert!(state.enter_vault(1, false).is_err());
        drop(switch);
        assert!(state.enter_vault(0, false).is_err());
        assert!(state.enter_vault(1, false).is_ok());
    }
}

#[cfg(test)]
#[path = "browser_probe.rs"]
mod browser_probe;
