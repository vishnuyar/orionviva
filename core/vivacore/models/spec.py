"""ModelSpec — how to call one pinned model. Shared by the product and the bench.

A spec names the adapter, the pinned model version, where to reach it, its
limits, and (for cost accounting) its prices. API keys are not part of it: a
spec carries the name of an environment variable, and the key is read from the
environment at call time.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..errors import ConfigError


@dataclass(frozen=True)
class ModelSpec:
    name: str
    adapter: str                      # "anthropic" | "openai-compatible"
    model: str                        # pinned model identifier
    base_url: str | None = None       # required for openai-compatible
    api_key_env: str | None = None    # env var holding the key (None = keyless, e.g. a local server)
    temperature: float = 0.2
    max_tokens: int = 8192
    cost_per_mtok_in: float = 0.0     # USD per million input tokens (0 for local)
    cost_per_mtok_out: float = 0.0
    timeout_s: float = 300.0
    json_mode: bool = False           # ask the provider for guaranteed-valid JSON
    # How many times to continue across provider truncation. The shared default
    # suits document extraction, where a long transaction list genuinely gets
    # cut off and stitching the tail back on is the repair. A call whose output
    # is short and bounded sets this to 0, so truncation is reported rather than
    # repaired.
    max_continuations: int | None = None   # None = the shared default
    notes: str = ""
    unix_socket_path: str | None = None

    def __post_init__(self) -> None:
        self.validate_local_transport()

    def validate_local_transport(self) -> None:
        """Reject ambiguous local destinations before constructing or dispatching."""
        path = self.unix_socket_path
        if path is None:
            return
        if self.adapter != "openai-compatible":
            raise ConfigError("UNIX sockets require the openai-compatible adapter.")
        if (not isinstance(path, str) or not path.startswith("/")
                or any(part in ("", ".", "..") for part in path.split("/")[1:])
                or any(ord(char) < 32 or ord(char) == 127 for char in path)):
            raise ConfigError("UNIX socket paths must be absolute and canonical.")
        try:
            encoded = os.fsencode(path)
        except UnicodeError as exc:
            raise ConfigError("UNIX socket paths must have a filesystem encoding.") from exc
        if len(encoded) > 103:
            raise ConfigError("UNIX socket paths must fit within 103 filesystem bytes.")
        if not isinstance(self.base_url, str):
            raise ConfigError("UNIX sockets require an explicit logical HTTP base URL.")
        try:
            url = urlsplit(self.base_url)
            valid_url = (bool(self.base_url) and self.base_url.startswith("http://")
                         and url.scheme == "http" and bool(url.hostname)
                         and url.username is None and url.password is None
                         and "?" not in self.base_url and "#" not in self.base_url
                         and not any(char.isspace() or ord(char) < 32 or ord(char) == 127
                                     for char in self.base_url)
                         and "\\" not in self.base_url)
            url.port
        except (ValueError, TypeError) as exc:
            raise ConfigError("UNIX sockets require an explicit logical HTTP base URL.") from exc
        if not valid_url:
            raise ConfigError(
                "UNIX sockets require an explicit logical HTTP base URL "
                "without credentials, query or fragment.")
        current = ""
        for part in path.split("/")[1:]:
            current += "/" + part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                break
            except OSError as exc:
                raise ConfigError("UNIX socket path components cannot be inspected.") from exc
            if stat.S_ISLNK(info.st_mode):
                raise ConfigError("UNIX socket paths cannot contain symlinks.")
            if current != path and not stat.S_ISDIR(info.st_mode):
                raise ConfigError("UNIX socket ancestors must be directories.")
            if current == path and not stat.S_ISSOCK(info.st_mode):
                raise ConfigError("The UNIX socket destination must be a socket.")

    def endpoint_identity(self) -> str:
        """Bind admission to the exact configured destination without publishing it."""
        version = "model-endpoint-v1"
        payload = [version, "unix" if self.unix_socket_path is not None else "tcp",
                   self.unix_socket_path, self.base_url, self.adapter]
        encoded = json.dumps(payload, ensure_ascii=True,
                             separators=(",", ":")).encode("utf-8")
        return version + ":" + hashlib.sha256(encoded).hexdigest()

    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise ConfigError(
                f"Model '{self.name}' needs the environment variable "
                f"{self.api_key_env} to be set (keys never live in config files)."
            )
        return key
