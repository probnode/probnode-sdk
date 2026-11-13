"""`probnode` on the command line.

    probnode login                                   # email + password -> a key in ~/.config
    probnode datasets
    probnode files books parquet 2026-11-08T12 2026-11-08T14
    probnode download books parquet 2026-11-08T12 2026-11-08T14 -o data/
    probnode sync books parquet 2026-11-08T12 2026-11-08T14 -o data/   # only what changed
    probnode doctor data/                            # every file against its sha256

Times are UTC hours: `2026-11-08T12`, `2026-11-08T12:00`, or full ISO all work.
Exit codes: 0 done, 1 a check failed (doctor), 2 the API refused or a request failed.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .client import Client, DataFile, ProbNodeError, load_config, save_config, sha256_of

STATE = ".probnode-sync.json"


def iso_hour(value: str) -> str:
    """`2026-11-08T12` / `2026-11-08 12:00` / ISO -> `2026-11-08T12:00:00Z`."""
    v = value.strip().replace(" ", "T").rstrip("Z")
    date, _, time = v.partition("T")
    hour = (time or "00")[:2]
    if len(date) != 10 or not hour.isdigit():
        raise argparse.ArgumentTypeError(f"not a UTC hour: {value!r} (use 2026-11-08T12)")
    return f"{date}T{hour}:00:00Z"


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


def _client(args: argparse.Namespace) -> Client:
    return Client(api_key=args.key, base_url=args.base_url)


def _listing(pn: Client, args: argparse.Namespace) -> list[DataFile]:
    return pn.files(
        args.dataset,
        args.format,
        args.start,
        args.end,
        granularity=args.granularity,
        market=args.market or (),
        series=args.series or (),
    )


def _read_state(dest: Path) -> dict[str, dict]:
    try:
        return json.loads((dest / STATE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write_state(dest: Path, state: dict[str, dict]) -> None:
    tmp = dest / (STATE + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(dest / STATE)


def _current(dest: Path, recorded: dict | None, f: DataFile) -> bool:
    """A file is current when the listing still names the sha256 we fetched AND the file on disk
    is the one we wrote: same size, same mtime. Anything touched since - truncated, overwritten,
    restored from elsewhere - is fetched again, rather than trusted because the state says so.
    (A full re-hash is `probnode doctor`.)"""
    path = dest / f.object_path
    if not recorded or recorded.get("sha256") != f.sha256 or not path.exists():
        return False
    st = path.stat()
    return st.st_size == f.bytes and st.st_mtime_ns == recorded.get("mtime_ns")


def cmd_login(args: argparse.Namespace) -> int:
    email = args.email or input("Email: ")
    password = getpass.getpass("Password: ")
    pn = _client(args)
    key = pn.login(email, password)
    config = load_config()
    config.update({"api_key": key, "base_url": pn.base_url})
    save_config(config)
    print(f"signed in as {email}; key saved")
    return 0


def cmd_datasets(args: argparse.Namespace) -> int:
    for d in _client(args).datasets():
        held = f"{d['first_hour']} .. {d['last_hour']}" if d.get("last_hour") else "nothing held"
        print(f"{d['code']:<10} {d['tier']:<5} {','.join(d['formats']):<20} {held}")
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    files = _listing(_client(args), args)
    for f in files:
        print(f"{f.object_path}  {f.rows:>12,} rows  {human(f.bytes):>10}  {f.sha256[:12]}")
    print(
        f"{len(files)} files, {human(sum(f.bytes for f in files))}, "
        f"{sum(f.rows for f in files):,} rows"
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    path = _client(args).export_book(args.market, args.day, Path(args.out), format=args.format)
    print(path)
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    pn = _client(args)
    files = _listing(pn, args)
    dest = Path(args.out)
    for path in pn.download_all(files, dest):
        print(path)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Download what is new or changed since the last sync into the same directory; a file whose
    sha256 already matches is left alone, so a second run moves nothing. Interrupted downloads
    leave only a .part file, and the next run fetches that file again."""
    pn = _client(args)
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    state = _read_state(dest)
    files = _listing(pn, args)
    todo = [f for f in files if not _current(dest, state.get(f.object_path), f)]
    moved = 0
    for f, path in zip(todo, pn.download_all(todo, dest), strict=False):
        st = path.stat()
        state[f.object_path] = {
            "sha256": f.sha256,
            "bytes": f.bytes,
            "rows": f.rows,
            "mtime_ns": st.st_mtime_ns,
        }
        _write_state(dest, state)
        moved += f.bytes
        print(f"got {path}")
    print(
        f"{len(todo)} of {len(files)} files fetched, {human(moved)}; "
        f"{len(files) - len(todo)} already current"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Every file a sync recorded, re-hashed. Missing or changed files are named; exit 1 if any."""
    dest = Path(args.dir)
    state = _read_state(dest)
    if not state:
        print(f"no {STATE} in {dest}: run `probnode sync` into it first", file=sys.stderr)
        return 1
    bad = 0
    for object_path, meta in sorted(state.items()):
        path = dest / object_path
        if not path.exists():
            print(f"MISSING  {object_path}")
            bad += 1
        elif sha256_of(path) != meta["sha256"]:
            print(f"CORRUPT  {object_path}")
            bad += 1
    print(f"{len(state) - bad} of {len(state)} files ok")
    return 1 if bad else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="probnode", description="ProbNode data from the shell")
    p.add_argument("--key", help="API key (default: PROBNODE_API_KEY or `probnode login`)")
    p.add_argument("--base-url", help="API base (default: https://probnode.com)")
    sub = p.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="sign in with email and password, save the key")
    login.add_argument("--email")
    login.set_defaults(run=cmd_login)

    sub.add_parser("datasets", help="datasets, formats and the hours held").set_defaults(
        run=cmd_datasets
    )

    def selection(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("dataset", help="books, trades, gaps, markets, quotes, ohlcv_1m")
        sp.add_argument("format", help="lp2, parquet or csv")
        sp.add_argument("start", type=iso_hour, help="first UTC hour, inclusive")
        sp.add_argument("end", type=iso_hour, help="last UTC hour, exclusive")
        sp.add_argument("--granularity", default="hour", choices=["hour", "market_day"])
        sp.add_argument("--market", action="append", help="narrow to a market slug (repeatable)")
        sp.add_argument("--series", action="append", help="narrow to a series slug (repeatable)")

    files = sub.add_parser("files", help="list the files in a selection")
    selection(files)
    files.set_defaults(run=cmd_files)

    for name, run, text in (
        ("download", cmd_download, "download a selection, sha256-checked"),
        ("sync", cmd_sync, "download only what is new or changed"),
    ):
        sp = sub.add_parser(name, help=text)
        selection(sp)
        sp.add_argument("-o", "--out", default=".", help="directory (default: here)")
        sp.set_defaults(run=run)

    export = sub.add_parser(
        "export", help="one market's UTC day of the full book, as parquet or csv.gz"
    )
    export.add_argument("market", help="market slug")
    export.add_argument("day", help="UTC day, YYYY-MM-DD (must have ended)")
    export.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    export.add_argument("-o", "--out", default=".", help="directory (default: here)")
    export.set_defaults(run=cmd_export)

    doctor = sub.add_parser("doctor", help="re-check every synced file against its sha256")
    doctor.add_argument("dir", nargs="?", default=".")
    doctor.set_defaults(run=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args)
    except ProbNodeError as exc:
        print(f"probnode: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
