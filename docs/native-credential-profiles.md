# Native credential profiles

The installed native host accepts `--credential-profile <id>`, where `<id>` is
`synthetic-` followed by exactly 32 lowercase hexadecimal digits. This explicit
option selects an immutable operating-system credential namespace for synthetic
qualification. It is a nonsecret selector, not authentication.

Without the option, the host keeps the existing credential service
`com.orionviva.desktop.default-vault`, account `default`, and
`<app_data_dir>/instance.lock`. With the option, the service is
`com.orionviva.desktop.profile.<id>.default-vault`, the account stays `default`,
and the instance lock is `<app_data_dir>/profiles/<id>/instance.lock`.
Every remembered-vault read and write uses that selection, including automatic
opening, recovery and browser-host requests. A missing entry or an error never
causes a lookup in the default namespace. The existing OS credential protection,
stored format, bounded read and read concurrency guard remain in place.

The host validates and freezes the selection in `run`, before constructing the
application. Missing, malformed, duplicate and alias options fail startup;
`--credential-profile=<id>` is also refused. There is no environment override
and an uninitialized selection cannot silently become the default profile.

This option does not redirect configuration, the home directory, temporary
files or vault files. Qualification must also supply its explicitly isolated
filesystem environment. Reuse the same nonsecret identifier to exercise genuine
synthetic remember-and-relaunch behavior; generate a fresh identifier for a
fresh namespace. A fresh identifier does not prove absence: OS errors still
propagate, and actual keychain and delivered application lifecycle behavior
require separate runtime evidence. Unit tests use constructor spies and never
read the user's default credential.
