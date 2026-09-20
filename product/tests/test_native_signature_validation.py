"""Execute native-verification command contracts against failing tool outcomes."""
import json

import pytest

from scripts import verify_native_signature as signature


def test_macos_calls_each_native_gate_and_checks_identity(tmp_path, monkeypatch):
    artifact = tmp_path / "Synthetic.app"
    artifact.mkdir()
    (artifact / "binary").write_bytes(b"synthetic")
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return "TeamIdentifier=SYNTHETIC\n" if "--display" in command else ""
    monkeypatch.setattr(signature.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(signature, "run", run)
    assert signature.verify(artifact, "SYNTHETIC")["status"] == "passed"
    assert len(commands) == 4
    assert "--strict" in commands[0] and "--assess" in commands[2]
    assert commands[3][1:3] == ["stapler", "validate"]
    with pytest.raises(RuntimeError, match="team"):
        signature.verify(artifact, "ANOTHER")


@pytest.mark.parametrize("failed_gate", [0, 1, 2, 3])
def test_any_failed_mac_tool_prevents_pass(tmp_path, monkeypatch, failed_gate):
    artifact = tmp_path / "Synthetic.dmg"
    artifact.write_bytes(b"synthetic")
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if len(calls) - 1 == failed_gate:
            raise RuntimeError("native tool refused")
        return "TeamIdentifier=SYNTHETIC\n" if "--display" in command else ""
    monkeypatch.setattr(signature.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(signature, "run", run)
    with pytest.raises(RuntimeError):
        signature.verify(artifact, "SYNTHETIC")
    assert len(calls) == failed_gate + 1


@pytest.mark.parametrize("status,thumbprint", [("NotSigned", "ABC"), ("Valid", "DEF"), ("HashMismatch", "ABC")])
def test_windows_rejects_bad_signature_or_publisher(tmp_path, monkeypatch, status, thumbprint):
    artifact = tmp_path / "Synthetic.exe"
    artifact.write_bytes(b"synthetic")
    monkeypatch.setattr(signature.platform, "system", lambda: "Windows")
    monkeypatch.setattr(signature, "run", lambda *args, **kwargs: json.dumps(dict(status=status, thumbprint=thumbprint)))
    with pytest.raises(RuntimeError):
        signature.verify(artifact, "ABC")


def test_windows_paths_are_data_and_valid_signature_is_bound(tmp_path, monkeypatch):
    artifact = tmp_path / "Synthetic 'quoted'.msi"
    artifact.write_bytes(b"synthetic")
    def run(command, *, environment):
        assert str(artifact) not in command[-1]
        assert environment["ORIONVIVA_SIGNATURE_ARTIFACT"] == str(artifact)
        return '{"status":"Valid","thumbprint":"ABC"}'
    monkeypatch.setattr(signature.platform, "system", lambda: "Windows")
    monkeypatch.setattr(signature, "run", run)
    assert signature.verify(artifact, "abc")["checks"] == ["authenticode-valid", "expected-certificate-thumbprint"]


def test_unsigned_platform_and_changing_artifact_do_not_pass(tmp_path, monkeypatch):
    artifact = tmp_path / "Synthetic.exe"
    artifact.write_bytes(b"synthetic")
    monkeypatch.setattr(signature.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="no native"):
        signature.verify(artifact, "ABC")
    monkeypatch.setattr(signature.platform, "system", lambda: "Windows")
    def run(*args, **kwargs):
        artifact.write_bytes(b"different")
        return '{"status":"Valid","thumbprint":"ABC"}'
    monkeypatch.setattr(signature, "run", run)
    with pytest.raises(RuntimeError, match="changed"):
        signature.verify(artifact, "ABC")


@pytest.mark.parametrize("inside", [False, True])
def test_report_cannot_destroy_artifact_or_bundle_member(tmp_path, monkeypatch, inside):
    artifact = tmp_path / "Synthetic.app"
    artifact.mkdir()
    member = artifact / "binary"
    member.write_bytes(b"preserve")
    output = member if inside else artifact
    monkeypatch.setattr("sys.argv", ["check", "--artifact", str(artifact), "--expected-identity", "SYNTHETIC", "--output", str(output)])
    with pytest.raises(SystemExit):
        signature.main()
    assert member.read_bytes() == b"preserve"
