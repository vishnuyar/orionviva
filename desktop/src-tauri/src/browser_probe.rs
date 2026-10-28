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

fn campaign_sources(source: &Path) -> HashMap<String, (String, PathBuf)> {
    let root = source.join("product/viva/sample_data/five-year-life-v1");
    assert_eq!(
        root.canonicalize().unwrap(),
        root,
        "corpus root must be canonical"
    );
    assert!(!root.symlink_metadata().unwrap().file_type().is_symlink());
    let manifest = root.join("manifest.json");
    assert!(!manifest
        .symlink_metadata()
        .unwrap()
        .file_type()
        .is_symlink());
    assert_eq!(
        campaign_sha256(&manifest).unwrap(),
        "97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800"
    );
    let manifest: Value = serde_json::from_slice(&std::fs::read(manifest).unwrap()).unwrap();
    let documents = manifest["documents"].as_array().unwrap();
    assert_eq!(documents.len(), 794);
    let mut sources = HashMap::new();
    for document in documents {
        let name = document["file"].as_str().unwrap();
        assert!(
            name.ends_with(".pdf") && !name.contains(['/', '\\']) && name != "." && name != ".."
        );
        let path = root.join(name);
        assert!(!path.symlink_metadata().unwrap().file_type().is_symlink());
        assert!(path.is_file() && path.canonicalize().unwrap() == path);
        let digest = document["sha256"].as_str().unwrap();
        assert_eq!(digest.len(), 64);
        assert!(digest
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)));
        assert!(sources.insert(name.into(), (digest.into(), path)).is_none());
    }
    sources
}

#[test]
fn campaign_html_selection_requires_exact_manifest_name_and_current_source_bytes() {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap();
    let sources = campaign_sources(&source);
    let name = "D0001-payroll-PAY-Microsoft-2021-01-31.pdf";
    let (digest, path) = sources.get(name).unwrap();
    let request = json!({"name":name,"sha256":digest});
    assert_eq!(
        campaign_selected_source(&sources, &request).unwrap(),
        json!(path.to_string_lossy())
    );
    assert!(
        campaign_selected_source(&sources, &json!({"name":name,"sha256":"0".repeat(64)})).is_err()
    );
    assert!(campaign_selected_source(
        &sources,
        &json!({"name":format!("../{name}"),"sha256":digest})
    )
    .is_err());
    assert!(
        campaign_selected_source(&sources, &json!({"name":name,"sha256":digest,"path":path}))
            .is_err()
    );
    assert!(
        campaign_selected_source(&sources, &json!({"name":"unknown.pdf","sha256":digest})).is_err()
    );
    let mut mismatched = sources.clone();
    mismatched.insert(name.into(), ("0".repeat(64), path.clone()));
    assert!(
        campaign_selected_source(&mismatched, &json!({"name":name,"sha256":"0".repeat(64)}))
            .is_err()
    );
    assert!(campaign_sha256(&source.join("missing-campaign-file.pdf")).is_err());
    assert!(BrowserState::default().campaign_sources.is_none());
}

#[test]
#[ignore = "run npm run test:browser-host with a local Chrome driver and Python environment"]
fn production_browser_routes_with_synthetic_vault() {
    run_browser_probe(false);
}

#[test]
#[ignore = "manually driven synthetic campaign: browser file chooser, explicit private sidecar, stop file required"]
fn production_browser_routes_with_persona_campaign() {
    run_browser_probe(true);
}

fn run_browser_probe(campaign: bool) {
    let root = PathBuf::from(
        std::env::var("ORIONVIVA_BROWSER_PROBE_ROOT").expect("synthetic test root required"),
    );
    if campaign {
        assert!(cfg!(target_os = "macos"), "campaign chooser requires macOS");
        assert!(root.is_absolute() && root.is_dir());
        assert_eq!(
            root.canonicalize().unwrap(),
            root,
            "use a canonical private root"
        );
        assert!(!root.join("stop").exists() && !root.join("ready.json").exists());
        #[cfg(unix)]
        {
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let metadata = std::fs::metadata(&root).unwrap();
            let home =
                std::fs::metadata(std::env::var("HOME").expect("host HOME required")).unwrap();
            assert_eq!(
                metadata.uid(),
                home.uid(),
                "campaign root must be owned by this user"
            );
            assert_eq!(
                metadata.permissions().mode() & 0o777,
                0o700,
                "campaign root must be private"
            );
        }
    } else {
        assert!(
            root.starts_with(std::env::temp_dir())
                || root.starts_with("/private/tmp")
                || root.starts_with("/tmp")
        );
    }
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
        test_selections: (!campaign).then(|| {
            (
                root.join("vault").to_string_lossy().into_owned(),
                root.join("synthetic.txt").to_string_lossy().into_owned(),
                root.join("copy.orionvault").to_string_lossy().into_owned(),
            )
        }),
        campaign_sources: campaign.then(|| campaign_sources(&source)),
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
    let command = if campaign {
        let sidecar = PathBuf::from(
            std::env::var("ORIONVIVA_SIDECAR").expect("explicit campaign sidecar required"),
        );
        let sidecar = sidecar.canonicalize().unwrap();
        assert!(
            sidecar.starts_with(&root) && sidecar.is_file(),
            "campaign sidecar must be inside its private root"
        );
        #[cfg(unix)]
        {
            use std::os::unix::fs::{MetadataExt, PermissionsExt};
            let metadata = std::fs::metadata(&sidecar).unwrap();
            assert_eq!(metadata.uid(), std::fs::metadata(&root).unwrap().uid());
            assert_eq!(
                metadata.permissions().mode() & 0o077,
                0,
                "campaign sidecar must be private"
            );
            assert_ne!(
                metadata.permissions().mode() & 0o100,
                0,
                "campaign sidecar must be executable"
            );
        }
        let mut command = std::process::Command::new(sidecar);
        // The Witness-owned wrapper establishes source, isolation and metering.
        // Provider credentials are never accepted by the Rust host or test files.
        command.env_clear();
        command
    } else {
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
        command
    };
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
    let deadline = (!campaign).then(|| std::time::Instant::now() + Duration::from_secs(180));
    while !root.join("stop").exists()
        && deadline.is_none_or(|deadline| std::time::Instant::now() < deadline)
    {
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
