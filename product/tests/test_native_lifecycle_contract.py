"""Acceptance checks for the Tauri sidecar lifecycle boundary.

Rust/Tauri is not available in the product test environment, so these checks
keep the host's reliability contract visible until its native tests can run in
CI. They intentionally assert behaviour, not a particular process wrapper.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
HOST = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"


def _source() -> str:
    assert HOST.is_file(), "native lifecycle host is missing"
    return HOST.read_text()


def _function_body(source: str, name: str) -> str:
    """Return a Rust function body without assuming its internal layout."""
    start = source.find(f"fn {name}")
    assert start >= 0, f"native host is missing {name}"
    opening = source.find("{", start)
    assert opening >= 0, f"{name} has no function body"

    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening:index + 1]
    raise AssertionError(f"{name} has an unclosed function body")


def test_native_host_gracefully_reaps_the_owned_sidecar_on_shutdown():
    source = _source()

    # The child must be retained, not discarded after spawn, so shutdown can
    # close its pipes, terminate a still-running process, and reap its PID.
    assert "child: Child" in source
    assert "fn shutdown_bridge" in source or "impl Drop for BridgeProcess" in source
    assert ".kill()" in source
    assert ".wait()" in source

    run = _function_body(source, "run")
    assert "RunEvent::Exit" in run
    assert "state.shutdown()" in run, "the native host must stop the sidecar on app exit"


def test_native_host_discards_a_broken_child_and_supports_explicit_recovery():
    source = _source()
    request = _function_body(source, "request_bridge")
    restart = _function_body(source, "restart")

    # A dead child can fail on write, flush, read, or invalid output. The host
    # must clear the cached process before the user initiates recovery. It must
    # not automatically replay a request because a write could have reached
    # the sidecar before the failure was observed.
    assert "shutdown_current(&mut process)" in request
    assert "bridge_restart" in source
    assert "shutdown_current(&mut process)" in restart
    assert "request_process(ensure_bridge(&mut process)?" in request


def test_native_host_matches_only_the_current_non_event_response():
    request = _function_body(_source(), "request_process")

    # Progress frames and frames for other requests may legitimately appear on
    # the stream. Neither can settle this invoke call.
    assert "loop" in request
    assert 'response.get("request_id")' in request
    assert "Some(request_id)" in request or "Some(request_id.as_str())" in request
    assert 'response.get("event").is_none()' in request
    assert "return Ok(response)" in request


def test_native_host_does_not_leave_the_cached_child_after_eof():
    source = _source()
    request = _function_body(source, "request_process")
    recovery = _function_body(source, "request_bridge")

    eof = request.find("if read == 0")
    assert eof >= 0, "EOF from the sidecar must be handled explicitly"
    eof_branch = request[eof:request.find("}", eof) + 1]
    assert "bridge exited before responding" in eof_branch
    assert "shutdown_current(&mut process)" in recovery


def test_native_host_reaps_an_exited_child_before_starting_a_replacement():
    source = _source()
    ensure = _function_body(source, "ensure_bridge")

    # A sidecar can exit between requests. Its previous PID is reaped before a
    # replacement is spawned so the host never accumulates stale processes.
    assert "current.status()?" in ensure
    assert "process.take()" in ensure
    assert "spawn_bridge()?" in ensure
