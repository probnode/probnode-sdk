"""The SDK and CLI against a fake ProbNode: an httpx MockTransport that serves a listing, signs
paths and hands out the bytes behind each signed URL."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

import probnode
from probnode import cli
from probnode.client import Client, ProbNodeError

BLOBS = {
    "x/parquet/books/event_date=2026-11-08/hour=12.parquet": b"twelve" * 1000,
    "x/parquet/books/event_date=2026-11-08/hour=13.parquet": b"thirteen" * 1000,
}


class Fake:
    def __init__(self) -> None:
        self.blobs = dict(BLOBS)
        self.fetches: list[str] = []
        self.signed: list[str] = []

    def listing(self) -> list[dict]:
        return [
            {
                "dataset": "books",
                "format": "parquet",
                "event_date": "2026-11-08",
                "hour": int(p.split("hour=")[1][:2]),
                "src": "s6",
                "object_path": p,
                "rows": 10,
                "bytes": len(b),
                "sha256": hashlib.sha256(b).hexdigest(),
                "granularity": "hour",
                "market": None,
                "future_field": 1,
            }
            for p, b in self.blobs.items()
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "lake.test":
            path = url.path.removeprefix("/")
            self.fetches.append(path)
            return httpx.Response(200, content=self.served(path))
        if request.headers.get("Authorization") != "Bearer k":
            return httpx.Response(401, json={"detail": "missing or invalid API key"})
        if url.path == "/v1/data/files":
            if url.params.get("dataset") == "nope":
                return httpx.Response(400, json={"detail": "unknown dataset 'nope'"})
            files = self.listing()
            return httpx.Response(
                200,
                json={
                    "files": files,
                    "total_files": len(files),
                    "total_bytes": sum(f["bytes"] for f in files),
                },
            )
        if url.path == "/v1/data/urls":
            paths = json.loads(request.content)["paths"]
            self.signed += paths
            return httpx.Response(
                200,
                json={
                    "urls": [
                        {"object_path": p, "url": f"https://lake.test/{p}", "expires_at": "x"}
                        for p in paths
                    ],
                    "licence": "research",
                    "licence_detail": "",
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    def served(self, path: str) -> bytes:
        return self.blobs[path]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Fake:
    f = Fake()
    monkeypatch.setenv("PROBNODE_CONFIG", str(tmp_path / "cfg.json"))
    real_init = Client.__init__

    def init(self, api_key=None, base_url=None, **kw):
        real_init(
            self,
            api_key=api_key or "k",
            base_url=base_url or "https://api.test",
            transport=httpx.MockTransport(f),
        )

    monkeypatch.setattr(Client, "__init__", init)
    return f


ARGS = ["books", "parquet", "2026-11-08T12", "2026-11-08T14"]


def test_files_keeps_unknown_fields_and_parses(fake: Fake) -> None:
    files = Client().files("books", "parquet", "2026-11-08T12:00:00Z", "2026-11-08T14:00:00Z")
    assert [f.hour for f in files] == [12, 13]
    assert files[0].extra == {"future_field": 1}


def test_api_refusal_is_the_api_sentence(fake: Fake) -> None:
    with pytest.raises(ProbNodeError) as err:
        Client().files("nope", "parquet", "a", "b")
    assert err.value.status == 400 and "unknown dataset" in err.value.detail


def test_download_verifies_sha256(fake: Fake, tmp_path: Path) -> None:
    pn = Client()
    f = pn.files(*ARGS[:2], "s", "e")[0]
    fake.served = lambda path: b"tampered"  # type: ignore[method-assign]
    with pytest.raises(ProbNodeError, match="sha256 mismatch"):
        pn.download(f, tmp_path)
    assert not (tmp_path / f.object_path).exists()
    assert not list(tmp_path.rglob("*.part"))


def test_sync_twice_moves_nothing_then_only_the_change(fake: Fake, tmp_path: Path) -> None:
    out = tmp_path / "data"
    assert cli.main(["sync", *ARGS, "-o", str(out)]) == 0
    assert len(fake.fetches) == 2
    assert cli.main(["sync", *ARGS, "-o", str(out)]) == 0
    assert len(fake.fetches) == 2, "second sync fetched again"

    changed = "x/parquet/books/event_date=2026-11-08/hour=13.parquet"
    fake.blobs[changed] = b"corrected" * 1000
    assert cli.main(["sync", *ARGS, "-o", str(out)]) == 0
    assert fake.fetches[2:] == [changed]
    assert (out / changed).read_bytes() == fake.blobs[changed]


def test_doctor_names_a_corrupt_and_a_missing_file(
    fake: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "data"
    cli.main(["sync", *ARGS, "-o", str(out)])
    assert cli.main(["doctor", str(out)]) == 0
    paths = sorted(BLOBS)
    (out / paths[0]).write_bytes(b"bitrot")
    (out / paths[1]).unlink()
    capsys.readouterr()
    assert cli.main(["doctor", str(out)]) == 1
    text = capsys.readouterr().out
    assert f"CORRUPT  {paths[0]}" in text and f"MISSING  {paths[1]}" in text


def test_cli_refusal_exits_2(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["files", "nope", "parquet", "2026-11-08T12", "2026-11-08T13"]) == 2
    assert "unknown dataset" in capsys.readouterr().err


def test_iso_hour_accepts_the_short_forms() -> None:
    assert cli.iso_hour("2026-11-08T12") == "2026-11-08T12:00:00Z"
    assert cli.iso_hour("2026-11-08 07:00") == "2026-11-08T07:00:00Z"
    assert cli.iso_hour("2026-11-08T12:00:00Z") == "2026-11-08T12:00:00Z"


def test_read_parquet_and_csv(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq

    t = pa.table({"a": [1, 2]})
    pq.write_table(t, tmp_path / "x.parquet")
    pacsv.write_csv(t, tmp_path / "x.csv")
    assert probnode.read(tmp_path / "x.parquet").to_pydict() == {"a": [1, 2]}
    assert probnode.read(tmp_path / "x.csv").to_pydict() == {"a": [1, 2]}
    with pytest.raises(ValueError):
        probnode.read(tmp_path / "x.txt")


def test_lp2_reader_is_the_api_one() -> None:
    """The SDK ships the same lp2 decoder the ingest uses; if they drift, a customer decodes
    differently from the exports we made. Byte-identical, checked where both are present."""
    api = Path(__file__).resolve().parents[3] / "apps/api/src/pmd_api/lp2.py"
    if not api.exists():
        pytest.skip("not in the monorepo")
    ours = Path(probnode.__file__).with_name("lp2.py")
    assert ours.read_bytes() == api.read_bytes()


def test_sync_refetches_a_file_changed_on_disk(fake: Fake, tmp_path: Path) -> None:
    """The state file says current, but the bytes on disk were changed: sync must notice and fetch
    again, not trust its own bookkeeping."""
    out = tmp_path / "data"
    cli.main(["sync", *ARGS, "-o", str(out)])
    victim = sorted(BLOBS)[0]
    (out / victim).write_bytes(b"corrupt")
    assert cli.main(["sync", *ARGS, "-o", str(out)]) == 0
    assert fake.fetches[2:] == [victim]
    assert cli.main(["doctor", str(out)]) == 0
