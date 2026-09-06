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
    assert "child: Arc<Mutex<Option<Child>>>" in source
    assert "fn shutdown_bridge" in source or "impl Drop for BridgeState" in source
    assert ".kill()" in source
    assert ".wait()" in source

    run = _function_body(source, "run")
    assert "RunEvent::Exit" in run
    assert "state.shutdown()" in run, "the native host must stop the sidecar on app exit"


def test_native_host_discards_a_broken_child_and_supports_explicit_recovery():
    source = _source()
    request = _function_body(source, "request_bridge_with")
    restart = _function_body(source, "restart")

    # A dead child can fail on write, flush, read, or invalid output. The host
    # must clear the cached process before the user initiates recovery. It must
    # not automatically replay a request because a write could have reached
    # the sidecar before the failure was observed.
    assert "shutdown_current(&mut process)" in request
    assert "bridge_restart" in source
    assert "shutdown_current(&mut process)" in restart
    assert "ensure_bridge(app, &mut process, spawn, &state.next_generation)" in request
    assert "request_process(&bridge" in request
    assert "can_replay_after_recovery" in request
    assert "claim_read_recovery" in request
    assert "operation_may_have_written" in request


def test_native_host_matches_only_the_current_non_event_response():
    source = _source()
    router = _function_body(source, "route_stdout")
    pending = _function_body(source, "route_pending")

    # Progress frames and frames for other requests may legitimately appear on
    # the stream. Neither can settle this invoke call.
    assert "loop" in router
    assert 'get("request_id")' in router
    assert "calls.get(request_id)" in pending
    assert "calls.remove(request_id)" in pending
    # A progress frame is recognised, handed to the window that asked, and
    # never returned as an answer. Before this it was recognised and dropped,
    # which is a channel that reports nothing.
    assert 'response.get("event").is_some()' in router
    assert "app.emit(JOB_PROGRESS_EVENT" in router
    assert "RoutedFrame::Response" in router


def test_native_host_does_not_leave_the_cached_child_after_eof():
    source = _source()
    router = _function_body(source, "route_stdout")
    recovery = _function_body(source, "request_bridge_with")

    eof = router.find("if read == 0")
    assert eof >= 0, "EOF from the sidecar must be handled explicitly"
    eof_branch = router[eof:router.find("}", eof) + 1]
    assert "interrupt_pending" in eof_branch
    assert "shutdown_current(&mut process)" in recovery


def test_native_host_reaps_an_exited_child_before_starting_a_replacement():
    source = _source()
    ensure = _function_body(source, "ensure_bridge")

    # A sidecar can exit between requests. Its previous PID is reaped before a
    # replacement is spawned so the host never accumulates stale processes.
    assert "current.status()?" in ensure
    assert "process.take()" in ensure
    assert "spawn(app)?" in ensure
    assert "spawned.generation = next_generation.fetch_add" in ensure


def test_native_waiting_occurs_after_releasing_the_process_lifecycle_lock():
    request = _function_body(_source(), "request_bridge_with")
    bridge_scope = request.find("let bridge = {")
    lock_end = request.find("\n        };", bridge_scope)
    wait = request.find("request_process(&bridge")
    assert bridge_scope >= 0 and lock_end > bridge_scope and wait > lock_end
    assert "state.lock()?" in request[bridge_scope:lock_end]
    # The guard is scoped to the bridge clone and is dropped before the wait.
    # Moving request_process inside this block is the counterfactual this gate
    # rejects.
    assert "request_process(&bridge" not in request[bridge_scope:lock_end]


def test_active_identity_is_generation_bound_at_success_and_failure():
    source = _source()
    request = _function_body(source, "request_bridge_with")
    clear = _function_body(source, "clear_active_vault_after_failure")
    assert "generation: bridge.generation" in request
    assert "clear_active_vault_after_failure(&state.active_vault, bridge.generation)" in request
    assert "active.generation == failed_generation" in clear
    # Counterfactual: unconditional clearing must not satisfy this gate.
    assert "active.vault = ActiveVault::None" in clear
