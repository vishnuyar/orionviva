"""The document reader the environment builds.

One setting decides whether a document is read or parked, and every entry point
that ingests documents asks the same function for its reader. With nothing
configured, nothing leaves the machine: the document is captured and parked,
unread.
"""

from viva.ingest.reader import build_reader


def test_reader_factory_gates_on_env(monkeypatch):
    for k in ("VIVA_MODEL_ADAPTER", "VIVA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    read_fn, live = build_reader()
    assert live is False                       # no model configured -> parks

    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "anthropic")
    monkeypatch.setenv("VIVA_MODEL", "claude-pinned-2026")
    monkeypatch.setenv("VIVA_MODEL_KEY_ENV", "SOME_KEY")
    read_fn, live = build_reader()
    assert live is True and callable(read_fn)   # built, but no call made here


def test_a_parked_document_carries_the_reason_it_was_not_read(monkeypatch):
    """Parking is honest about itself: the result names why there is no reading,
    so a document that never left the machine is not mistaken for one that was
    read and yielded nothing."""
    for k in ("VIVA_MODEL_ADAPTER", "VIVA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    read_fn, _live = build_reader()
    result = read_fn(b"", "doc")
    assert result.facts is None and "no model configured" in result.error
