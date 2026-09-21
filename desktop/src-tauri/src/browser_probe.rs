use super::*;
use std::borrow::Cow;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use tauri::utils::assets::{AssetKey, AssetsIter, CspHash};

struct Files(HashMap<String, Vec<u8>>);
impl<R: tauri::Runtime> tauri::Assets<R> for Files {
    fn get(&self, key: &AssetKey) -> Option<Cow<'_, [u8]>> {
        self.0
            .get(key.as_ref())
            .map(|bytes| Cow::Borrowed(bytes.as_slice()))
    }
    fn iter(&self) -> Box<AssetsIter<'_>> {
        Box::new(
            self.0
                .iter()
                .map(|(key, bytes)| (Cow::Borrowed(key.as_str()), Cow::Borrowed(bytes.as_slice()))),
        )
    }
    fn csp_hashes(&self, _: &AssetKey) -> Box<dyn Iterator<Item = CspHash<'_>> + '_> {
        Box::new(std::iter::empty())
    }
}
fn assets(root: &Path, directory: &Path, files: &mut HashMap<String, Vec<u8>>) {
    for entry in std::fs::read_dir(directory).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            assets(root, &path, files);
        } else {
            files.insert(
                format!("/{}", path.strip_prefix(root).unwrap().to_string_lossy()),
                std::fs::read(path).unwrap(),
            );
        }
    }
}

#[test]
#[ignore = "run npm run test:browser-host with a local Chrome driver and Python environment"]
fn production_browser_routes_with_synthetic_vault() {
    let root = PathBuf::from(
        std::env::var("ORIONVIVA_BROWSER_PROBE_ROOT").expect("synthetic test root required"),
    );
    assert!(
        root.starts_with(std::env::temp_dir())
            || root.starts_with("/private/tmp")
            || root.starts_with("/tmp")
    );
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let dist = source.join("desktop/dist");
    let mut files = HashMap::new();
    assets(&dist, &dist, &mut files);
    assert!(files.contains_key("/loopback.html"));
    let browser = BrowserState {
        remember: false,
        test_selections: Some((
            root.join("vault").to_string_lossy().into_owned(),
            root.join("synthetic.txt").to_string_lossy().into_owned(),
        )),
        ..BrowserState::default()
    };
    let state = crate::BridgeState {
        process: Mutex::new(None),
        active_vault: Mutex::new(crate::ActiveVaultRecord {
            vault: crate::ActiveVault::None,
            generation: 0,
        }),
        next_generation: std::sync::atomic::AtomicUsize::new(0),
        read_recovery_claimed: std::sync::atomic::AtomicBool::new(false),
        recovery_gate: crate::RecoveryGate::new(),
    };
    let app = tauri::test::mock_builder()
        .manage(browser)
        .manage(state)
        .build(tauri::test::mock_context(Files(files)))
        .unwrap();
    let python = source.join(".venv/bin/python");
    let mut command = std::process::Command::new(python);
    command
        .args(["-m", "viva.desktop_bridge"])
        .current_dir(source.join("product"))
        .env_clear()
        .env("VIVA_ENV_FILE", root.join("empty.env"))
        .env(
            "PYTHONPATH",
            std::env::join_paths([
                root.clone(),
                source.join("product"),
                source.join("core"),
                source.join("merchant"),
                source.join("bench"),
            ])
            .unwrap(),
        )
        .env("VIVA_DEMO_HOME", root.join("sample"));
    let bridge = crate::spawn_bridge_command(app.handle(), command).unwrap();
    *app.state::<crate::BridgeState>().process.lock().unwrap() = Some(bridge);
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    let launch = app.state::<BrowserState>().activate().unwrap();
    let handle = app.handle().clone();
    std::thread::spawn(move || serve(handle, listener, port));
    let ready = root.join("ready.json");
    let contents = json!({"url": format!("http://127.0.0.1:{port}/loopback.html#launch={launch}")})
        .to_string();
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options
        .open(&ready)
        .unwrap()
        .write_all(contents.as_bytes())
        .unwrap();
    let deadline = std::time::Instant::now() + Duration::from_secs(180);
    while !root.join("stop").exists() && std::time::Instant::now() < deadline {
        if root.join("revoke").exists() {
            app.state::<BrowserState>().revoke().unwrap();
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    app.state::<crate::BridgeState>().shutdown().unwrap();
    assert!(
        root.join("stop").exists(),
        "browser test driver did not complete"
    );
}
