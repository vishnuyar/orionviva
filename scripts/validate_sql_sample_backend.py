"""Explicit source caller for the fixed seven-document SQL sample candidate."""
import argparse
from pathlib import Path
import sys


def main():
    if getattr(sys,"frozen",False):
        raise SystemExit("SQL sample candidates require a source interpreter")
    root=Path(__file__).resolve().parents[1]
    sys.path[:0]=[str(root/name) for name in ("product","core","merchant","bench")]
    from viva.sample import sql_instances
    parser=argparse.ArgumentParser()
    parser.add_argument("--operation",required=True,choices=("build","reopen"))
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--output",type=Path)
    target.add_argument("--instance",type=Path)
    arguments=parser.parse_args()
    parser.error("build requires --output; reopen requires --instance") if (
        arguments.operation=="build" and arguments.output is None or
        arguments.operation=="reopen" and arguments.instance is None) else None
    sql_instances._source_host_guard()
    if sys.stdin.isatty():
        parser.error("an explicit caller-owned RAM credential pipe is required")
    framed=sys.stdin.buffer.readline(258)
    if not framed.endswith(b"\n") or len(framed)>257 or sys.stdin.buffer.read(1)!=b"":
        parser.error("invalid bounded credential pipe")
    try:
        with sql_instances._credential_scope(framed[:-1].decode("ascii")):
            result=(sql_instances.build_sql_candidate(arguments.output) if arguments.operation=="build"
                    else sql_instances.reopen_sql_candidate(arguments.instance))
    except sql_instances.SQLSampleBackendError as error:
        print(sql_instances._encoded({"status":"STOP_FAILURE","instance":error.instance,"result":error.result}).decode())
        return 1
    print(sql_instances._encoded(result).decode())
    return 0


if __name__=="__main__":
    raise SystemExit(main())
