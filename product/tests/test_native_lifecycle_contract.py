"""Acceptance checks for the Tauri sidecar lifecycle boundary.

Rust/Tauri is not available in the product test environment, so these checks
keep the host's reliability contract visible until its native tests can run in
CI. They intentionally assert behaviour, not a particular process wrapper.
"""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).parents[2]
HOST = ROOT / "desktop" / "src-tauri" / "src" / "main.rs"


def _source() -> str:
    assert HOST.is_file(), "native lifecycle host is missing"
    return HOST.read_text()


def _block_end(source: str, opening: int) -> int:
    assert opening >= 0 and source[opening] == "{", "missing lexical block"
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise AssertionError("unclosed lexical block")


def _function_body(source: str, name: str) -> str:
    """Require the named owner, never a prefix match or missing helper."""
    matches = list(re.finditer(r"\bfn\s+" + re.escape(name) + r"(?=\s*[<(])", source))
    assert len(matches) == 1, f"native host must declare exactly one {name}"
    opening = source.find("{", matches[0].end())
    assert opening >= 0, f"{name} has no function body"
    return source[opening:_block_end(source, opening)]


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source)


def _request_owner(source: str) -> str:
    wrapper = _compact(_function_body(source, "request_bridge_with"))
    assert wrapper == (
        "{request_bridge_with_owner(app,state,frame,spawn,policy,"
        "before_failed_identity_clear,None,)}"
    ), "compatibility wrapper must delegate without a bulk ticket"
    return _function_body(source, "request_bridge_with_owner")


def _assert_write_uncertainty(branch: str, label: str) -> None:
    compact = _compact(branch)
    declaration = (
        'letuncertainty=ifoperation_may_have_written(operation){'
        '"Outcomeunknown;checkthevaultbeforetryingagain."}else{""};'
    )
    position = compact.find(declaration)
    assert position >= 0, f"{label} must declare its own write uncertainty"
    assert "{uncertainty}" in compact[position + len(declaration):], (
        f"{label} must include its uncertainty in the returned error"
    )


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
    request = _request_owner(source)
    restart = _function_body(source, "restart")
    compact = _compact(request)

    # Inspect the actual owner; an uncertain write must never be replayed.
    assert "shutdown_current(&mut process)" in request
    assert "bridge_restart" in source
    assert "shutdown_current(&mut process)" in restart
    assert "ensure_bridge(app, &mut process, spawn, &state.next_generation)" in request
    assert "request_process_owned(&bridge,&request_id,&encoded,policy(operation),ticket.clone(),)" in compact
    assert "letcleanup_error=ifis_current{shutdown_current(&mutprocess).err()}else{None};" in compact
    assert "Arc::ptr_eq(&current.child,&bridge.child)" in compact
    assert "letwill_recover=cleanup_error.is_none()&&attempt==0&&can_replay_after_recovery(operation,recovery.as_ref())&&claim_read_recovery(&state.read_recovery_claimed);" in compact
    # Each actual result arm owns its warning; a token in the other arm cannot
    # satisfy the stale-success or failed-request uncertainty contract.
    success_start = request.find("Ok(response) => {")
    assert success_start >= 0, "successful response arm is required"
    success_open = request.find("{", success_start)
    success_end = _block_end(request, success_open)
    success = request[success_open:success_end]
    stale_condition = success.find("if !current.as_ref().is_some_and(")
    assert stale_condition >= 0, "stale-generation success guard is required"
    stale_body = success.find("}) {", stale_condition)
    assert stale_body >= 0, "stale-generation success body is unreadable"
    stale_open = stale_body + 3
    stale = success[stale_open:_block_end(success, stale_open)]
    _assert_write_uncertainty(stale, "stale-generation success")
    assert 'interruptedgeneration.{uncertainty}' in _compact(stale)

    failure_start = request.find("Err(error) => {", success_end)
    assert failure_start >= 0, "failed response arm is required"
    failure_open = request.find("{", failure_start)
    failure = request[failure_open:_block_end(request, failure_open)]
    _assert_write_uncertainty(failure, "failed request")
    assert 'returnErr(matchcleanup_error{' in _compact(failure)
    assert "ifwill_recover{continue;}" in compact
    assert _compact(_function_body(source, "operation_can_reopen_vault_and_replay")) == (
        '{operation==Some("viva.surface.read")}'
    )
    assert _compact(_function_body(source, "can_replay_after_recovery")) == (
        "{operation_can_reopen_vault_and_replay(operation)&&active.is_some_and(recovery_is_exact)}"
    )


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
    recovery = _request_owner(source)
    finish = _function_body(source, "finish_router_failure")

    eof = router.find("if read == 0")
    assert eof >= 0, "EOF from the sidecar must be handled explicitly"
    opening = router.find("{", eof)
    eof_branch = _compact(router[opening:_block_end(router, opening)])
    assert "finish_router_failure(stdout,bridge," in eof_branch
    assert "return;" in eof_branch
    assert "shutdown_current(&mut process)" in recovery

    condition = "if bridge.begin_bulk_drain().unwrap_or(false)"
    start = finish.find(condition)
    assert start >= 0, "router failure must retain bulk drain ownership"
    assert _compact(finish[:start]) == "{", "bulk drain precedes interruption"
    opening = finish.find("{", start)
    end = _block_end(finish, opening)
    bulk = finish[opening:end]
    consume = bulk.find("std::io::copy(&mut stdout, &mut std::io::sink())")
    drop = bulk.find("drop(stdout)")
    shutdown = bulk.find("bridge.shutdown()")
    assert 0 <= consume < drop < shutdown, "bulk stdout must drain and drop before shutdown waits"
    assert "interrupt_pending" not in bulk, "bulk receipts drain before ordinary interruption"
    ordinary_opening = finish.find("{", end)
    assert _compact(finish[end:ordinary_opening]) == "else", "ordinary failure branch is required"
    ordinary = finish[ordinary_opening:_block_end(finish, ordinary_opening)]
    assert 0 <= ordinary.find("interrupt_pending(&bridge.pending, reason)") < ordinary.find("bridge.shutdown()")


def test_native_host_reaps_an_exited_child_before_starting_a_replacement():
    source = _source()
    ensure = _function_body(source, "ensure_bridge")

    # A sidecar can exit between requests. Its previous PID is reaped before a
    # replacement is spawned so the host never accumulates stale processes.
    assert "current.status()?" in ensure
    assert "shutdown_current(process)?" in ensure
    assert "process.take()" in _function_body(source, "shutdown_current")
    assert "spawn(app)?" in ensure
    assert "spawned.generation = next_generation.fetch_add" in ensure


def test_native_waiting_occurs_after_releasing_the_process_lifecycle_lock():
    request = _request_owner(_source())
    bridge_scope = request.find("let bridge = {")
    assert bridge_scope >= 0, "owned bridge clone scope is required"
    opening = request.find("{", bridge_scope)
    lock_end = _block_end(request, opening)
    assert "state.lock()?" in request[opening:lock_end]
    assert "ensure_bridge(app, &mut process, spawn, &state.next_generation)" in request[opening:lock_end]
    waits = list(re.finditer(r"\brequest_process_owned\s*\(", request))
    assert waits, "owned response wait must remain visible"
    assert all(wait.start() > lock_end for wait in waits), "response wait holds the lifecycle lock"
    for response_wait in ("request_process", "reopen_sample_vault", "reopen_remembered_vault"):
        assert not re.search(r"\b" + response_wait + r"\s*\(", request[opening:lock_end])


def test_active_identity_is_generation_bound_at_success_and_failure():
    source = _source()
    request = _request_owner(source)
    clear = _function_body(source, "clear_active_vault_after_failure")
    compact = _compact(request)
    assert compact.count("generation:bridge.generation,") == 2
    assert "live.generation==bridge.generation&&Arc::ptr_eq(&live.child,&bridge.child)&&!*terminal&&!live.closed.load(Ordering::SeqCst)" in compact
    assert "clear_active_vault_after_failure(&state.active_vault,bridge.generation)?;" in compact
    assert "before_failed_identity_clear();" in compact
    condition = clear.find("if active.generation == failed_generation")
    assert condition >= 0, "failure clearing must compare the failed generation"
    opening = clear.find("{", condition)
    guarded = clear[opening:_block_end(clear, opening)]
    assert "active.vault = ActiveVault::None" in guarded
    assert clear.count("active.vault = ActiveVault::None") == 1
