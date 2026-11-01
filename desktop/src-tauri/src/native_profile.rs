use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

const LEGACY_SERVICE: &str = "com.orionviva.desktop.default-vault";
const CREDENTIAL_ACCOUNT: &str = "default";
const PROFILE_OPTION: &str = "--credential-profile";

struct CredentialScope {
    profile: Option<String>,
    service: String,
}

impl CredentialScope {
    fn parse(arguments: impl IntoIterator<Item = OsString>) -> Result<Self, String> {
        let mut arguments = arguments.into_iter();
        let mut profile = None;
        while let Some(argument) = arguments.next() {
            if argument == OsStr::new(PROFILE_OPTION) {
                if profile.is_some() {
                    return Err("credential profile was specified more than once".into());
                }
                let value = arguments
                    .next()
                    .ok_or("credential profile requires a value")?
                    .into_string()
                    .map_err(|_| "credential profile must be Unicode")?;
                let suffix = value.strip_prefix("synthetic-").unwrap_or("");
                if suffix.len() != 32
                    || !suffix
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                {
                    return Err("credential profile must be synthetic- followed by 32 lowercase hexadecimal digits".into());
                }
                profile = Some(value);
            } else {
                let spelling = argument.to_string_lossy();
                if spelling.starts_with(PROFILE_OPTION)
                    || spelling == "--profile"
                    || spelling.starts_with("--profile=")
                    || spelling.starts_with("--credential_profile")
                    || spelling.starts_with("-credential-profile")
                {
                    return Err(
                        "credential profile requires the exact --credential-profile option".into(),
                    );
                }
            }
        }
        let service = match &profile {
            Some(profile) => format!("com.orionviva.desktop.profile.{profile}.default-vault"),
            None => LEGACY_SERVICE.to_string(),
        };
        Ok(Self { profile, service })
    }

    fn lock_path(&self, app_data: &Path) -> PathBuf {
        match &self.profile {
            Some(profile) => app_data
                .join("profiles")
                .join(profile)
                .join("instance.lock"),
            None => app_data.join("instance.lock"),
        }
    }
}

struct ProfileSelection(OnceLock<CredentialScope>);

impl ProfileSelection {
    const fn new() -> Self {
        Self(OnceLock::new())
    }

    fn initialize(&self, arguments: impl IntoIterator<Item = OsString>) -> Result<(), String> {
        let scope = CredentialScope::parse(arguments)?;
        self.0
            .set(scope)
            .map_err(|_| "credential profile is already initialized".into())
    }

    fn scope(&self) -> Result<&CredentialScope, String> {
        self.0
            .get()
            .ok_or_else(|| "credential profile is not initialized".into())
    }

    fn credential_entry_with<T>(
        &self,
        constructor: impl FnOnce(&str, &str) -> Result<T, String>,
    ) -> Result<T, String> {
        let scope = self.scope()?;
        constructor(&scope.service, CREDENTIAL_ACCOUNT)
    }
}

static SELECTION: ProfileSelection = ProfileSelection::new();

pub fn initialize(arguments: impl IntoIterator<Item = OsString>) -> Result<(), String> {
    SELECTION.initialize(arguments)
}

pub fn credential_entry_with<T>(
    constructor: impl FnOnce(&str, &str) -> Result<T, String>,
) -> Result<T, String> {
    SELECTION.credential_entry_with(constructor)
}

pub fn lock_path(app_data: &Path) -> Result<PathBuf, String> {
    Ok(SELECTION.scope()?.lock_path(app_data))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    const ID: &str = "synthetic-0123456789abcdef0123456789abcdef";
    const OTHER_ID: &str = "synthetic-fedcba9876543210fedcba9876543210";

    fn arguments(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn absent_option_preserves_legacy_namespace_and_lock() {
        let selection = ProfileSelection::new();
        selection
            .initialize(arguments(&["-psn_0_123", "--unrelated"]))
            .unwrap();
        selection
            .credential_entry_with(|service, account| {
                assert_eq!(service, "com.orionviva.desktop.default-vault");
                assert_eq!(account, "default");
                Ok(())
            })
            .unwrap();
        assert_eq!(
            selection.scope().unwrap().lock_path(Path::new("app-data")),
            Path::new("app-data/instance.lock")
        );
    }

    #[test]
    fn selected_profile_routes_every_constructor_to_only_its_namespace() {
        let selection = ProfileSelection::new();
        selection
            .initialize(arguments(&[PROFILE_OPTION, ID]))
            .unwrap();
        let calls = Cell::new(0);
        for _ in 0..4 {
            selection.credential_entry_with(|service, account| {
                calls.set(calls.get() + 1);
                assert_eq!(service, "com.orionviva.desktop.profile.synthetic-0123456789abcdef0123456789abcdef.default-vault");
                assert_ne!(service, "com.orionviva.desktop.default-vault");
                assert_eq!(account, "default");
                Ok(())
            }).unwrap();
        }
        assert_eq!(calls.get(), 4);
        assert_eq!(
            selection.scope().unwrap().lock_path(Path::new("app-data")),
            Path::new("app-data/profiles")
                .join(ID)
                .join("instance.lock")
        );
        let other = CredentialScope::parse(arguments(&[PROFILE_OPTION, OTHER_ID])).unwrap();
        assert_ne!(selection.scope().unwrap().service, other.service);
        assert_ne!(
            selection.scope().unwrap().lock_path(Path::new("app-data")),
            other.lock_path(Path::new("app-data"))
        );
    }

    #[test]
    fn malformed_options_never_reach_constructor() {
        let cases = vec![
            vec![PROFILE_OPTION],
            vec![PROFILE_OPTION, ""],
            vec![PROFILE_OPTION, "default"],
            vec![PROFILE_OPTION, "synthetic-0123456789abcdef0123456789abcdeF"],
            vec![
                PROFILE_OPTION,
                " synthetic-0123456789abcdef0123456789abcdef",
            ],
            vec![
                PROFILE_OPTION,
                "synthetic-0123456789abcdef0123456789abcdef ",
            ],
            vec![
                PROFILE_OPTION,
                "../synthetic-0123456789abcdef0123456789abcdef",
            ],
            vec![
                PROFILE_OPTION,
                "synthetic-0123456789abcdef0123456789abcdeff",
            ],
            vec![PROFILE_OPTION, "synthetic-0123456789abcdef0123456789abcdeé"],
            vec![PROFILE_OPTION, ID, PROFILE_OPTION, OTHER_ID],
            vec!["--credential-profile=synthetic-0123456789abcdef0123456789abcdef"],
            vec!["--credential-profileextra", ID],
            vec!["--profile", ID],
            vec!["--profile=synthetic-0123456789abcdef0123456789abcdef"],
            vec!["--credential_profile", ID],
            vec!["-credential-profile", ID],
        ];
        for case in cases {
            let selection = ProfileSelection::new();
            assert!(
                selection.initialize(arguments(&case)).is_err(),
                "accepted {case:?}"
            );
            assert!(selection
                .credential_entry_with(|_, _| -> Result<(), String> {
                    panic!("invalid profile reached credential constructor")
                })
                .is_err());
        }
    }

    #[cfg(unix)]
    #[test]
    fn non_unicode_profile_never_reaches_constructor() {
        use std::os::unix::ffi::OsStringExt;
        let selection = ProfileSelection::new();
        assert!(selection
            .initialize(vec![
                OsString::from(PROFILE_OPTION),
                OsString::from_vec(vec![0xff])
            ])
            .is_err());
        assert!(selection
            .credential_entry_with(|_, _| -> Result<(), String> {
                panic!("non-Unicode profile reached credential constructor")
            })
            .is_err());
    }

    #[test]
    fn uninitialized_selection_has_no_implicit_default() {
        let selection = ProfileSelection::new();
        assert_eq!(
            selection
                .credential_entry_with(|_, _| -> Result<(), String> {
                    panic!("uninitialized selection reached credential constructor")
                })
                .unwrap_err(),
            "credential profile is not initialized"
        );
    }

    #[test]
    fn initialized_scope_cannot_change_or_fallback_on_constructor_error() {
        let selection = ProfileSelection::new();
        selection
            .initialize(arguments(&[PROFILE_OPTION, ID]))
            .unwrap();
        assert!(selection.initialize(Vec::new()).is_err());
        for outcome in [
            Ok(None::<()>),
            Err("store unavailable".to_string()),
            Err("remembered vault lookup timed out".to_string()),
        ] {
            let calls = Cell::new(0);
            let expected = outcome.clone();
            let result = selection.credential_entry_with(|service, account| {
                calls.set(calls.get() + 1);
                assert_eq!(service, "com.orionviva.desktop.profile.synthetic-0123456789abcdef0123456789abcdef.default-vault");
                assert_eq!(account, "default");
                outcome
            });
            assert_eq!(result, expected);
            assert_eq!(calls.get(), 1);
        }
    }
}
