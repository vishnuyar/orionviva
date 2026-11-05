"""Source-only, explicitly owned SQL sample candidates; never ordinary vaults."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time

VERSION = "sample-sql-candidate-v1"
SELECTION = "mixed-seven-v1"
BACKEND = "sql-application-complete"
_WORKER_SECONDS = 90
_REQUEST_LIMIT = 4096
_REPORT_LIMIT = 256 * 1024
_SECRET = ContextVar("owned_sql_sample_credential", default=None)
_LAUNCH_STATE = ContextVar("sql_sample_dispatch_preflight", default=None)
_SOURCE_ROOT = Path(__file__).resolve().parents[3]
_SELECTED = ((0,"D0001","pay_stub"),(6,"D0007","brokerage_statement"),
             (9,"D0010","term_deposit_statement"),(11,"D0012","mortgage_statement"),
             (12,"D0013","checking_statement"),(155,"D0156","property_tax_receipt"),
             (310,"D0311","refinance_settlement"))
_INSTRUMENTS = frozenset({"term_deposit_statement","mortgage_statement","property_tax_receipt","refinance_settlement"})
_HEADER_KEYS = {"version","selection","backend","instance_id","source","runtime","documents","state","sql_head","application_terminal"}
_REPORT_KEYS = {"version","selection","backend","authority_format","source","runtime","documents","counts","sql_head","application_terminal","source_checks","financial_holds","financial_failures","phases","admissions"}


class SQLSampleBackendError(ValueError):
    def __init__(self, message, *, instance=None, result=None):
        super().__init__(message)
        self.instance = None if instance is None else str(instance)
        self.result = {} if result is None else result


def _require(condition, message="SQL sample candidate contract refused"):
    if not condition:
        raise SQLSampleBackendError(message)


@contextmanager
def _credential_scope(passphrase):
    _require(type(passphrase) is str and 20 <= len(passphrase) <= 256
             and all(33 <= ord(ch) <= 126 for ch in passphrase), "explicit bounded RAM credential required")
    token = _SECRET.set(passphrase)
    try:
        yield
    finally:
        _SECRET.reset(token)


def _credential():
    value = _SECRET.get()
    _require(type(value) is str, "caller must own the disposable credential in RAM")
    return value


def _source_host_guard(instance=None):
    _require(not getattr(sys, "frozen", False), "SQL sample candidate is source-only")
    for name in os.environ:
        upper = name.upper()
        _require(not (upper.startswith(("OPENAI_","ANTHROPIC_","GEMINI_","AZURE_OPENAI_","ORIONVIVA_MODEL_","OPENROUTER_","DEEPSEEK_"))
                      or upper.endswith(("_API_KEY","_AUTH_TOKEN","_ACCESS_TOKEN"))
                      or "MODEL_PROVIDER" in upper or "MODEL_SETTINGS" in upper
                      or upper in {"GOOGLE_APPLICATION_CREDENTIALS","MODEL_API_KEY","PYTEST_PLUGINS"}),
                 "provider or model configuration is forbidden")
    if "VIVA_ENV_FILE" in os.environ:
        _require(instance is not None and os.environ["VIVA_ENV_FILE"] == str(instance / "empty.env"),
                 "foreign dotenv configuration is forbidden")
        _ordinary(instance / "empty.env", directory=False)
        _require((instance / "empty.env").stat().st_size == 0)


def _ordinary(path, *, directory=True, private=True):
    _require(path.is_absolute() and path.resolve(strict=True) == path, "canonical ordinary path required")
    info = path.lstat()
    _require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid()
             and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)), "ordinary owned path required")
    _require(not private or not info.st_mode & 0o077, "private candidate path required")
    return path


def _instance_path(value):
    _require(type(value) in {str, Path} or isinstance(value, Path), "candidate path required")
    path = Path(value)
    _require(path.is_absolute() and path.resolve(strict=True) == path)
    _require(re.fullmatch("[0-9a-f]{32}", path.name) is not None)
    _require(path.parent.name == "v1" and path.parent.parent.name == "sql-sample-candidates")
    for member in (path, path.parent, path.parent.parent, path.parent.parent.parent):
        _ordinary(member)
    return path


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def _write_json(path, value):
    data = _encoded(value)
    _require(len(data) <= _REPORT_LIMIT, "candidate report exceeds bound")
    temporary = path.with_name(path.name + ".next-" + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        parent = os.open(path.parent,os.O_RDONLY|os.O_NOFOLLOW)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path):
    _ordinary(path,directory=False)
    _require(path.stat().st_size <= _REPORT_LIMIT, "candidate report exceeds bound")
    with path.open("rb") as stream:
        data = stream.read(_REPORT_LIMIT+1)
    _require(len(data) <= _REPORT_LIMIT)
    def closed(pairs):
        result = {}
        for key,value in pairs:
            _require(key not in result)
            result[key]=value
        return result
    return json.loads(data,object_pairs_hook=closed)



def _validate_framework_base(raw_base, resolved_base, executable):
    _require(all(isinstance(path,Path) and path.is_absolute() for path in (raw_base,resolved_base,executable)),
             "absolute interpreter framework paths required")
    version=f"{sys.version_info.major}.{sys.version_info.minor}"
    anchor=executable.parent.parent
    _require(executable.parent.name=="bin" and anchor.name==version
             and anchor.parent.name=="Versions" and anchor.parent.parent.name=="Python.framework",
             "versioned executable framework anchor required")
    _require(resolved_base==anchor,"interpreter base differs from actual executable framework")
    return anchor


def _canonical_framework_base():
    raw=Path(sys.base_prefix)
    _require(raw.is_absolute(),"absolute interpreter framework base required")
    try:
        base=_validate_framework_base(raw,raw.resolve(strict=True),Path(sys.executable).resolve(strict=True))
        _require(base.is_dir(),"framework base is not a directory")
        return base
    except OSError as error:
        raise SQLSampleBackendError("interpreter framework base is unavailable") from error


def _source_paths():
    roots = [_SOURCE_ROOT/name for name in ("product","core","merchant","bench")]
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    environment = Path(sys.executable).absolute().parent.parent / "lib" / version / "site-packages"
    standard = _canonical_framework_base() / "lib" / version
    for path in roots + [environment,standard,standard/"lib-dynload"]:
        _require(path.is_dir() and path.resolve(strict=True)==path, "fixed source/runtime root unavailable")
    return roots + [environment,standard,standard/"lib-dynload"]



def _validate_runtime_alias(binding, standard):
    _require(type(binding) is dict and set(binding)=={
        "alias_path","raw_link","resolved_target","target_kind","target_sha256"}, "closed native alias binding required")
    version=f"{sys.version_info.major}.{sys.version_info.minor}"
    base=_canonical_framework_base()
    _require(base.is_absolute() and base.name==version and base.parent.name=="Versions"
             and base.parent.parent.name=="Python.framework", "trusted framework layout required")
    _require(standard==base/"lib"/("python"+version), "trusted stdlib root required")
    slots={str(standard/("config-"+version+"-darwin")/("libpython"+version+suffix))
           for suffix in (".a",".dylib")}
    _require(type(binding["alias_path"]) is str and binding["alias_path"] in slots,
             "unknown native runtime alias refused")
    _require(type(binding["raw_link"]) is str and 0<len(binding["raw_link"])<=4096
             and "\0" not in binding["raw_link"], "invalid native link spelling")
    _require(binding["resolved_target"]==str(base/"Python") and binding["target_kind"]=="regular",
             "native alias target outside trusted closure")
    _require(type(binding["target_sha256"]) is str
             and re.fullmatch("[0-9a-f]{64}",binding["target_sha256"]) is not None,
             "native alias target digest required")
    return binding


def _runtime_alias_binding(path, standard):
    version=f"{sys.version_info.major}.{sys.version_info.minor}"
    expected=_canonical_framework_base()/"Python"
    # Validate the closed slot before inspecting any supplied link or target.
    draft=dict(alias_path=str(path),raw_link="pending",resolved_target=str(expected),
               target_kind="regular",target_sha256="0"*64)
    _validate_runtime_alias(draft,standard)
    try:
        _require(path.is_symlink(), "native runtime alias required")
        _require(expected.resolve(strict=True)==expected, "canonical framework target required")
        info=expected.lstat()
        _require(stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode), "regular framework binary required")
        resolved=path.resolve(strict=True)
        _require(resolved==expected and stat.S_ISREG(resolved.lstat().st_mode), "native runtime target differs")
        binding=dict(alias_path=str(path),raw_link=os.readlink(path),resolved_target=str(resolved),
                     target_kind="regular",target_sha256=hashlib.sha256(expected.read_bytes()).hexdigest())
    except OSError as error:
        raise SQLSampleBackendError("native runtime alias is unavailable") from error
    return _validate_runtime_alias(binding,standard)


def _pins(deadline):
    roots = _source_paths()
    digest = hashlib.sha256();count=0
    seen=set();aliases={}
    standard=_canonical_framework_base()/"lib"/f"python{sys.version_info.major}.{sys.version_info.minor}"
    for root in roots:
        for path in sorted(root.rglob("*")):
            _require(time.monotonic()<deadline,"identity verification deadline exceeded")
            relative=path.relative_to(root)
            if ("__pycache__" in relative.parts or any(part.startswith(".") for part in relative.parts)
                    or "site-packages" in relative.parts and root.name!="site-packages"):
                continue
            if path.is_symlink():
                binding=_runtime_alias_binding(path,standard)
                aliases[str(path)]=binding
                digest.update(_encoded(binding)+b"\0")
                continue
            if not path.is_file() or path.suffix in {".pyc",".pyo"}:
                continue
            canonical=path.resolve()
            if canonical in seen:continue
            seen.add(canonical)
            digest.update(str(canonical).encode()+b"\0"+hashlib.sha256(path.read_bytes()).digest());count+=1
            _require(count<=30000,"runtime closure exceeds bound")
    script=_SOURCE_ROOT/"scripts/validate_sql_sample_backend.py"
    _require(script.is_file())
    digest.update(str(script).encode()+b"\0"+hashlib.sha256(script.read_bytes()).digest())
    executable=Path(sys.executable).resolve()
    runtime={"roots":[str(path) for path in roots],"files_sha256":digest.hexdigest(),"file_count":count,
             "framework_base":str(_canonical_framework_base()),
             "native_aliases":[aliases[name] for name in sorted(aliases)],
             "python":sys.version,"executable":str(executable),"executable_sha256":hashlib.sha256(executable.read_bytes()).hexdigest()}
    from . import resources
    source={"sample_version":resources.VERSION,"manifest_sha256":resources.MANIFEST_SHA256,
            "readings_sha256":resources.READINGS_SHA256}
    return source,runtime


def _validate_request(request):
    _require(type(request) is dict and set(request)=={"operation","instance","selection","version"})
    _require(type(request["operation"]) is str and request["operation"] in {"build","reopen"}
             and request["version"]==VERSION and request["selection"]==SELECTION)
    _require(type(request["instance"]) is str and len(_encoded(request))<=_REQUEST_LIMIT)
    _instance_path(request["instance"])
    return request


def _header(instance, source, runtime):
    value=_read_json(instance/"candidate.json")
    _require(type(value) is dict and set(value)==_HEADER_KEYS)
    _require(value["version"]==VERSION and value["selection"]==SELECTION and value["backend"]==BACKEND)
    _require(value["instance_id"]==instance.name and value["source"]==source and value["runtime"]==runtime)
    _require(value["state"] in {"partial","complete"})
    if value["state"]=="complete":
        _require(type(value["documents"]) is list and len(value["documents"])==7)
        for row,(_index,identifier,kind) in zip(value["documents"],_SELECTED):
            _require(type(row) is dict and set(row)=={"id","sha256","doc_type"})
            _require(row["id"]==identifier and row["doc_type"]==kind
                     and type(row["sha256"]) is str and re.fullmatch("[0-9a-f]{64}",row["sha256"]) is not None)
        head,terminal=value["sql_head"],value["application_terminal"]
        _require(type(head) is dict and set(head)=={"revision","head"})
        _require(type(head["revision"]) is int and head["revision"]>=0
                 and type(head["head"]) is str and re.fullmatch("[0-9a-f]{64}",head["head"]) is not None)
        _require(type(terminal) is dict and set(terminal)=={"root_id","sequence","head","sql_revision","sql_head"})
        _require(type(terminal["sequence"]) is int and terminal["sequence"]>0
                 and type(terminal["sql_revision"]) is int and terminal["sql_revision"]==head["revision"]
                 and terminal["sql_head"]==head["head"])
        _require(all(type(terminal[name]) is str and re.fullmatch("[0-9a-f]{64}",terminal[name]) is not None
                     for name in ("root_id","head","sql_head")))
        report=_read_json(instance/"report.json")
        _require(type(report) is dict and set(report)==_REPORT_KEYS)
        _require(all(report[name]==value[name] for name in ("version","selection","backend","source","runtime","documents","sql_head","application_terminal")))
    else:
        _require(value["documents"]==[] and value["sql_head"] is None and value["application_terminal"] is None)
    return value


def _group_absent(pgid):
    try:os.killpg(pgid,0)
    except ProcessLookupError:return True
    return False


def _cancel_requested(instance):
    return False


def _launch(operation, instance):
    state=_LAUNCH_STATE.get()
    _require(type(state) is dict, "owned preflight required")
    started=state["started"];deadline=started+120
    _source_host_guard();credential=_credential()
    result={"status":"STOP_PRE_DISPATCH","operation":operation,"owned_group_absent":False,"worker_dispatched":False}
    child=None;pgid=None;owned=False;pre_seconds=0.0;early_cleanup=0.0;streams={};output_fds=[]
    try:
        source,runtime,header=state["source"],state["runtime"],state["header"]
        pre_seconds=state["verification_seconds"]
        request=_validate_request(dict(operation=operation,instance=str(instance),selection=SELECTION,version=VERSION))
        bootstrap="import sys\nsys.path[:]="+repr([str(p) for p in _source_paths()])+"\nfrom viva.sample.sql_instances import _worker_dispatch\n_worker_dispatch()\n"
        dispatch=instance/("dispatch-"+secrets.token_hex(8));dispatch.mkdir(mode=0o700)
        stdout=os.open(dispatch/"stdout.json",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        stderr=os.open(dispatch/"stderr.log",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        environment={"PATH":"/usr/bin:/bin","HOME":str(instance/"home"),"TMPDIR":str(instance/"tmp"),
                     "PYTHONDONTWRITEBYTECODE":"1","VIVA_ENV_FILE":str(instance/"empty.env"),
                     "MERCHANTCORE_HOME":str(instance/"learned"),"XDG_CONFIG_HOME":str(instance/"home")}
        try:
            worker_started=time.monotonic()
            child=subprocess.Popen([sys.executable,"-I","-S","-B","-X","pycache_prefix="+str(instance/"bytecode"),"-c",bootstrap],
                cwd=instance,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        except BaseException:
            os.close(stdout);os.close(stderr);raise
        output_fds=[stdout,stderr]
        for stream,fd in ((child.stdout,stdout),(child.stderr,stderr)):
            os.set_blocking(stream.fileno(),False);streams[stream]=[fd,0]
        def drain():
            for stream,(fd,count) in list(streams.items()):
                try:data=os.read(stream.fileno(),8192)
                except BlockingIOError:continue
                if not data:
                    stream.close();del streams[stream];continue
                allowed=max(0,_REPORT_LIMIT-count)
                if allowed:os.write(fd,data[:allowed])
                streams[stream][1]+=len(data)
                if len(data)>allowed:result["status"]="STOP_OUTPUT_LIMIT"
        pgid=child.pid;result.update(worker_dispatched=True,pid=pgid)
        owned=os.getpgid(pgid)==pgid
        _require(owned,"owned process group unavailable")
        framed=_encoded(request)+b"\n"+credential.encode("ascii")+b"\n"
        worker_deadline=min(time.monotonic()+_WORKER_SECONDS,deadline-30)
        os.set_blocking(child.stdin.fileno(),False)
        sent=0
        while sent<len(framed) and child.poll() is None:
            drain()
            if time.monotonic()>=worker_deadline:
                result["status"]="STOP_TIMEOUT";break
            try:sent+=os.write(child.stdin.fileno(),framed[sent:])
            except BlockingIOError:time.sleep(.005)
        child.stdin.close()
        while result["status"]=="STOP_PRE_DISPATCH" and child.poll() is None:
            drain()
            if result["status"]!="STOP_PRE_DISPATCH":break
            if _cancel_requested(instance):result["status"]="STOP_CANCELLED";break
            if time.monotonic()>=worker_deadline:result["status"]="STOP_TIMEOUT";break
            time.sleep(.01)
        if result["status"] in {"STOP_TIMEOUT","STOP_CANCELLED","STOP_OUTPUT_LIMIT"}:
            stopped=time.monotonic();stop_deadline=min(deadline,stopped+8)
            if owned and not _group_absent(pgid):os.killpg(pgid,signal.SIGTERM)
            try:child.wait(timeout=max(.01,min(1,stop_deadline-time.monotonic())))
            except subprocess.TimeoutExpired:pass
            if owned and not _group_absent(pgid):os.killpg(pgid,signal.SIGKILL)
            child.wait(timeout=max(.01,min(2,stop_deadline-time.monotonic())))
            early_cleanup=time.monotonic()-stopped
        while streams and time.monotonic()<worker_deadline:
            drain()
            if streams:time.sleep(.005)
        result["worker_wall_seconds"]=time.monotonic()-worker_started-early_cleanup
        for fd in output_fds:os.fsync(fd)
        if result["status"]=="STOP_PRE_DISPATCH":
            _require(not streams,"owned worker output did not close")
            payload=_read_json(dispatch/"stdout.json")
            _require(type(payload) is dict and set(payload)=={"status","error_type","report"})
            result.update(status=payload["status"],worker_exit=child.returncode,error_type=payload["error_type"])
            if payload["status"]=="CANDIDATE_COMPLETE":
                _require(child.returncode==0 and type(payload["report"]) is dict and set(payload["report"])==_REPORT_KEYS)
                result["report"]=payload["report"]
        post_started=time.monotonic()
        after_source,after_runtime=_pins(min(deadline-10,post_started+20-pre_seconds))
        _require((source,runtime)==(after_source,after_runtime),"source/runtime changed during candidate dispatch")
        result["source_runtime_unchanged"]=True
        result["verification_seconds"]=pre_seconds+time.monotonic()-post_started
    except BaseException as error:
        if result["status"] not in {"STOP_TIMEOUT","STOP_CANCELLED","STOP_OUTPUT_LIMIT"}:result["status"]="STOP_FAILURE"
        result["error_type"]=type(error).__name__
    finally:
        cleanup=time.monotonic();cleanup_deadline=min(deadline,cleanup+10-early_cleanup)
        for stream in streams:
            stream.close()
        for fd in output_fds:os.close(fd)
        if child is not None:
            try:
                if not owned:
                    if child.poll() is None:child.kill()
                    raise SQLSampleBackendError("owned group identity was not established")
                if not _group_absent(pgid):
                    os.killpg(pgid,signal.SIGTERM)
                    try:child.wait(timeout=max(.01,min(1,cleanup_deadline-time.monotonic())))
                    except subprocess.TimeoutExpired:pass
                if not _group_absent(pgid):os.killpg(pgid,signal.SIGKILL)
                child.wait(timeout=max(.01,min(2,cleanup_deadline-time.monotonic())))
                while not _group_absent(pgid) and time.monotonic()<cleanup_deadline:time.sleep(.01)
                result["owned_group_absent"]=_group_absent(pgid)
            except BaseException as error:
                result.update(status="STOP_CLEANUP_UNCERTAIN",cleanup_error_type=type(error).__name__)
        else:result["owned_group_absent"]=True
        if result["status"]=="CANDIDATE_COMPLETE" and result["owned_group_absent"]:
            report=result["report"]
            report["phases"].update(parent_verification_seconds=result["verification_seconds"],
                owned_worker_wall_seconds=result["worker_wall_seconds"],
                dispatch_before_publication_seconds=time.monotonic()-started)
            _write_json(instance/"report.json",report)
            header.update(state="complete",sql_head=report["sql_head"],application_terminal=report["application_terminal"],documents=report["documents"])
            _write_json(instance/"candidate.json",header)
        result["cleanup_before_terminal_write_seconds"]=early_cleanup+time.monotonic()-cleanup
        if result["cleanup_before_terminal_write_seconds"]>10:result["status"]="STOP_TIMEOUT"
        result["pre_terminal_write_seconds"]=time.monotonic()-started
        if result["pre_terminal_write_seconds"]>120:result["status"]="STOP_TIMEOUT"
        if not result["owned_group_absent"]:result["status"]="STOP_CLEANUP_UNCERTAIN"
        _write_json(instance/("dispatch-result-"+secrets.token_hex(8)+".json"),result)
        result["actual_cleanup_seconds"]=early_cleanup+time.monotonic()-cleanup
        result["api_elapsed_seconds"]=time.monotonic()-started
        if result["api_elapsed_seconds"]>120 or result["actual_cleanup_seconds"]>10:
            result["status"]="STOP_TIMEOUT"
    if result["status"]!="CANDIDATE_COMPLETE":
        raise SQLSampleBackendError("SQL sample candidate dispatch stopped",instance=instance,result=result)
    return {"instance":str(instance),"report":result["report"],"api_elapsed_seconds":time.monotonic()-started}


def _prepared_dispatch(operation, instance, started, *, initialize=False):
    try:
        source,runtime=_pins(started+10)
    except SQLSampleBackendError as error:
        error.instance=str(instance)
        error.result={"status":"STOP_PRE_DISPATCH","worker_dispatched":False,"owned_group_absent":True,
                      "complete_path_seconds":time.monotonic()-started}
        raise
    if initialize:
        header=dict(version=VERSION,selection=SELECTION,backend=BACKEND,instance_id=instance.name,
                    source=source,runtime=runtime,documents=[],state="partial",sql_head=None,application_terminal=None)
        _write_json(instance/"candidate.json",header)
    header=_header(instance,source,runtime)
    state=dict(started=started,source=source,runtime=runtime,header=header,
               verification_seconds=time.monotonic()-started)
    token=_LAUNCH_STATE.set(state)
    try:return _launch(operation,instance)
    finally:_LAUNCH_STATE.reset(token)


def build_sql_candidate(output):
    started=time.monotonic()
    _source_host_guard();_credential()
    output=Path(output).absolute()
    _require(output.resolve(strict=False)==output and not output.exists(),"new canonical output required")
    _ordinary(output.parent,private=False)
    output.mkdir(mode=0o700)
    container=output/"sql-sample-candidates";container.mkdir(mode=0o700)
    version=container/"v1";version.mkdir(mode=0o700)
    instance=version/secrets.token_hex(16);instance.mkdir(mode=0o700)
    for name in ("home","tmp","learned","bytecode"):(instance/name).mkdir(mode=0o700)
    fd=os.open(instance/"empty.env",os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(fd)
    return _prepared_dispatch("build",instance,started,initialize=True)


def reopen_sql_candidate(instance):
    started=time.monotonic()
    _source_host_guard();_credential()
    return _prepared_dispatch("reopen",_instance_path(instance),started)


@contextmanager
def _open_owned_candidate(instance):
    _source_host_guard();credential=_credential();instance=_instance_path(instance)
    source_pins,runtime=_pins(time.monotonic()+20)
    header=_header(instance,source_pins,runtime)
    _require(header["state"]=="complete","partial candidate requires bounded reopen")
    from ..sql_authority import CuratedSource
    from ..sql_authority.application import ApplicationSQLAuthority
    source=CuratedSource.open()
    with ApplicationSQLAuthority.open(instance/"authority",credential,curated_source=source) as owner:
        _require(owner.head==header["sql_head"] and owner.terminal==header["application_terminal"])
        yield owner,source


def _worker_dispatch():
    started=time.monotonic();payload={"status":"STOP_FAILURE","error_type":None,"report":None}
    try:
        line=sys.stdin.buffer.readline(_REQUEST_LIMIT+2)
        _require(len(line)<=_REQUEST_LIMIT+1 and line.endswith(b"\n"))
        def pairs(values):
            record={}
            for key,value in values:
                _require(key not in record)
                record[key]=value
            return record
        request=_validate_request(json.loads(line,object_pairs_hook=pairs))
        secret=sys.stdin.buffer.readline(258)
        _require(secret.endswith(b"\n") and len(secret)<=257 and sys.stdin.buffer.read(1)==b"")
        credential=secret[:-1].decode("ascii");instance=Path(request["instance"])
        _source_host_guard(instance)
        with _credential_scope(credential):
            payload["report"]=_work(request,started)
        payload["status"]="CANDIDATE_COMPLETE"
    except BaseException as error:
        payload["error_type"]=type(error).__name__
    sys.stdout.buffer.write(_encoded(payload));sys.stdout.buffer.flush()
    raise SystemExit(0 if payload["status"]=="CANDIDATE_COMPLETE" else 1)


def _work(request, started):
    import socket
    def blocked(*args,**kwargs):raise SQLSampleBackendError("network forbidden")
    socket.socket.connect=blocked;socket.socket.connect_ex=blocked;socket.create_connection=blocked
    from ..sql_authority import CuratedSource
    from ..sql_authority.application import ApplicationSQLAuthority
    from ..sql_authority.schema import FORMAT,SCHEMA_VERSION
    from ..sql_authority.curated import issue
    from ..sql_authority.store import _encode
    from ..sql_authority.application_history import FORMAT as APP_FORMAT,ENGINE_FORMAT
    instance=Path(request["instance"]);phases={}
    before=time.monotonic();source_pins,runtime=_pins(started+_WORKER_SECONDS)
    header=_header(instance,source_pins,runtime);phases["identity_seconds"]=time.monotonic()-before
    before=time.monotonic();source=CuratedSource.open();documents=source.documents
    selected=[]
    for index,identifier,kind in _SELECTED:
        _require(index<len(documents) and documents[index]["id"]==identifier and documents[index]["doc_type"]==kind)
        _require(next(i for i,doc in enumerate(documents) if doc["doc_type"]==kind)==index)
        selected.append(documents[index])
    expected=[dict(id=doc["id"],sha256=doc["sha256"],doc_type=doc["doc_type"]) for doc in selected]
    _require(not header["documents"] or header["documents"]==expected)
    phases["source_validation_seconds"]=time.monotonic()-before
    authority=instance/"authority";before=time.monotonic()
    if authority.exists():
        if header["state"]=="partial":ApplicationSQLAuthority.recover(authority,_credential(),curated_source=source)
        owner=ApplicationSQLAuthority.open(authority,_credential(),curated_source=source)
    else:
        _require(header["state"]=="partial" and request["operation"] in {"build","reopen"})
        owner=ApplicationSQLAuthority.create(authority,_credential())
        owner.attach_curated(source)
    phases["open_recovery_seconds"]=time.monotonic()-before
    admissions=[];holds=[];failures=[];counts=dict(selected=7,originals=0,receipts=0,raw_null=0,typed_retained=0,unavailable=0,unsupported_financial=0,accepted=0)
    with owner:
        if header["state"]=="complete":
            _require(owner.head==header["sql_head"] and owner.terminal==header["application_terminal"],"candidate terminal differs")
        before=time.monotonic()
        if header["state"]=="complete":
            admissions=_read_json(instance/"report.json")["admissions"]
        else:
            completed=[]
            for doc in selected:
                result=owner.ingest_curated(source.original(doc["sha256"]),source)
                admissions.append(dict(id=doc["id"],sha256=doc["sha256"],initial_state=result.status,final_state=None))
                completed.append(doc["id"])
                _write_json(instance/"progress.json",dict(version=VERSION,selection=SELECTION,completed_ids=list(completed)))
        phases["ingestion_seconds"]=time.monotonic()-before
        before=time.monotonic()
        for doc,admission in zip(selected,admissions):
            doc_id=doc["sha256"];receipt=owner.receipt(doc_id);item=owner.item(doc_id)
            _require(owner.original(doc_id)==source.original(doc_id))
            issued,_admission=issue(source,source.original(doc_id),doc_id)
            _require(receipt["raw_reading"]==_encode(issued) and receipt["raw_reading"]["facts"] is None)
            counts["originals"]+=1;counts["receipts"]+=1;counts["raw_null"]+=1
            admission["final_state"]=item["state"]
            if doc["doc_type"] in _INSTRUMENTS:
                context=receipt["reading"]["authority_context"]
                _require(item["state"]=="unsupported" and context["financial_admission"] is False)
                _require(owner.postings(doc_id)==[] and owner.source_occurrences(doc_id)==[])
                counts["unsupported_financial"]+=1
                counts[context["disposition"]]+=1
                holds.append(dict(id=doc["id"],reason="unsupported_financial_family"))
            elif item["state"]=="accepted":counts["accepted"]+=1
            else:failures.append(dict(id=doc["id"],reason="unexpected_financial_hold"))
        sql_head,terminal=owner.head,owner.terminal
        _require(owner.verify(expected_head=sql_head,expected_terminal=terminal)["verified"])
        _require(len(owner.export_audit()["sources"])==7)
        if header["state"]=="complete":_require((sql_head,terminal)==(header["sql_head"],header["application_terminal"]))
        phases["conservation_complete_verification_seconds"]=time.monotonic()-before
        _require(not failures,"selected source financial expectation failed")
    phases["worker_entry_through_close_seconds"]=time.monotonic()-started
    _require(phases["worker_entry_through_close_seconds"]<=_WORKER_SECONDS)
    return dict(version=VERSION,selection=SELECTION,backend=BACKEND,
        authority_format=dict(application=APP_FORMAT,engine=ENGINE_FORMAT,sql=FORMAT,schema_version=SCHEMA_VERSION),
        source=source_pins,runtime=runtime,documents=expected,counts=counts,sql_head=sql_head,
        application_terminal=terminal,source_checks=dict(exact_selection=True,full_pack_authenticated=True,raw_original_conserved=True),
        financial_holds=holds,financial_failures=failures,phases=phases,admissions=admissions)
