"""The ProbNode API, as a Python object.

    import probnode
    pn = probnode.Client()                      # key from PROBNODE_API_KEY or `probnode login`
    files = pn.files("books", "parquet", "2026-11-08T12:00:00Z", "2026-11-08T14:00:00Z")
    for f in files:
        path = pn.download(f, "data/")          # sha256-checked against the listing
    table = probnode.read(path)                 # pyarrow.Table, whatever the format

Every method is one HTTP call (download is two: sign, then fetch). Errors are `ProbNodeError` with
the API's own sentence in it, never a bare status code.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://probnode.com"
CONFIG_PATH = Path(os.environ.get("PROBNODE_CONFIG", Path.home() / ".config" / "probnode.json"))
SIGN_BATCH = 100  # POST /v1/data/urls takes at most 100 paths
CHUNK = 1 << 20


class ProbNodeError(Exception):
    """A refusal or failure from the API, with its status and its sentence."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class DataFile:
    """One object in the lake, as GET /v1/data/files lists it."""

    dataset: str
    format: str
    event_date: str
    hour: int
    src: str
    object_path: str
    rows: int
    bytes: int
    sha256: str
    granularity: str = "hour"
    market: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> DataFile:
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw and k != "extra"}
        rest = {k: v for k, v in raw.items() if k not in cls.__dataclass_fields__}
        return cls(**known, extra=rest)


def load_config() -> dict[str, str]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_config(values: dict[str, str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(values, indent=2), encoding="utf-8")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass  # Windows: the file lives in the user's profile, which is already private


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class Client:
    """A session against one ProbNode deployment.

    `api_key` and `base_url` fall back to PROBNODE_API_KEY / PROBNODE_BASE_URL, then to what
    `probnode login` saved, then (base URL only) to https://probnode.com. Public calls - datasets,
    samples, the catalog - work without a key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        saved = load_config()
        self.api_key = api_key or os.environ.get("PROBNODE_API_KEY") or saved.get("api_key")
        self.base_url = (
            base_url
            or os.environ.get("PROBNODE_BASE_URL")
            or saved.get("base_url")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=transport, follow_redirects=False
        )
        # Signed URLs point at the lake, possibly another host; fetched without our key.
        self._fetch = httpx.Client(timeout=timeout, transport=transport, follow_redirects=True)

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()
        self._fetch.close()

    # -- plumbing ---------------------------------------------------------------------------

    def _headers(self, need_key: bool) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        if need_key:
            raise ProbNodeError(
                401, "no API key: pass api_key, set PROBNODE_API_KEY, or run `probnode login`"
            )
        return {}

    def _request(self, method: str, path: str, *, need_key: bool = True, **kw: Any) -> Any:
        response = self._http.request(method, path, headers=self._headers(need_key), **kw)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            if not isinstance(detail, str):
                detail = json.dumps(detail) if detail else response.reason_phrase
            raise ProbNodeError(response.status_code, detail)
        return response

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        return self._request(method, path, **kw).json()

    # -- account ----------------------------------------------------------------------------

    def login(self, email: str, password: str) -> str:
        """Mint a key with email and password; the client uses it from then on."""
        out = self._json(
            "POST", "/v1/auth/login", need_key=False, json={"email": email, "password": password}
        )
        self.api_key = out["key"]
        return self.api_key

    def me(self) -> dict[str, Any]:
        return self._json("GET", "/v1/me")

    def usage(self) -> dict[str, Any]:
        return self._json("GET", "/v1/data/usage")

    # -- catalog ----------------------------------------------------------------------------

    def datasets(self) -> list[dict[str, Any]]:
        """Every dataset, its formats, its tier and the hours held. Public."""
        return self._json("GET", "/v1/data/datasets", need_key=False)

    def series(self, category: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        params = {k: v for k, v in {"category": category, "q": q}.items() if v}
        return self._json("GET", "/v1/catalog/series", need_key=False, params=params)

    def markets(self, series: str | None = None, **params: Any) -> Any:
        if series:
            params["series"] = series
        return self._json("GET", "/v1/catalog/markets", need_key=False, params=params)

    def coverage(self, token_id: str, start: str | None = None, end: str | None = None) -> Any:
        params = {k: v for k, v in {"token_id": token_id, "start": start, "end": end}.items() if v}
        return self._json("GET", "/v1/catalog/coverage", need_key=False, params=params)

    def samples(self) -> Any:
        """Free sample files, one market-day per dataset and format. Public."""
        return self._json("GET", "/v1/samples", need_key=False)

    # -- files ------------------------------------------------------------------------------

    def files(
        self,
        dataset: str,
        format: str,
        start: str,
        end: str,
        *,
        granularity: str = "hour",
        market: Iterable[str] = (),
        series: Iterable[str] = (),
    ) -> list[DataFile]:
        """The objects for one dataset and format over [start, end), from the manifests."""
        params: list[tuple[str, str]] = [
            ("dataset", dataset),
            ("format", format),
            ("start", start),
            ("end", end),
        ]
        if granularity != "hour":
            params.append(("granularity", granularity))
        params += [("market", m) for m in market] + [("series", s) for s in series]
        out = self._json("GET", "/v1/data/files", params=params)
        return [DataFile.from_api(f) for f in out["files"]]

    def sign(self, paths: Iterable[str]) -> dict[str, str]:
        """object_path -> signed URL (valid for minutes; sign again any time)."""
        paths = list(paths)
        urls: dict[str, str] = {}
        for i in range(0, len(paths), SIGN_BATCH):
            out = self._json("POST", "/v1/data/urls", json={"paths": paths[i : i + SIGN_BATCH]})
            urls.update({u["object_path"]: u["url"] for u in out["urls"]})
        return urls

    def download(
        self,
        file: DataFile,
        dest: str | Path = ".",
        *,
        url: str | None = None,
        verify: bool = True,
    ) -> Path:
        """Fetch one file to `dest/<object_path>`, written to a .part first and renamed only when
        complete and (unless verify=False) its sha256 matches the listing."""
        target = Path(dest) / file.object_path
        target.parent.mkdir(parents=True, exist_ok=True)
        url = url or self.sign([file.object_path])[file.object_path]
        part = target.with_name(target.name + ".part")
        h = hashlib.sha256()
        with self._fetch.stream("GET", url) as response:
            if response.status_code >= 400:
                raise ProbNodeError(response.status_code, f"fetching {file.object_path} failed")
            with part.open("wb") as out:
                for chunk in response.iter_bytes(CHUNK):
                    out.write(chunk)
                    h.update(chunk)
        if verify and h.hexdigest() != file.sha256:
            part.unlink(missing_ok=True)
            raise ProbNodeError(0, f"sha256 mismatch for {file.object_path}")
        part.replace(target)
        return target

    def download_all(
        self, files: Iterable[DataFile], dest: str | Path = ".", *, verify: bool = True
    ) -> Iterator[Path]:
        files = list(files)
        urls = self.sign(f.object_path for f in files)
        for f in files:
            yield self.download(f, dest, url=urls[f.object_path], verify=verify)

    # -- range query ------------------------------------------------------------------------

    def timeseries(
        self, dataset: str, market: str, start: str, end: str, *, format: str = "parquet"
    ) -> Any:
        """Rows for one market over a window (at most 7 days, 200,000 rows) as a pyarrow Table
        (format="parquet") or a list of dicts (format="ndjson")."""
        response = self._request(
            "GET",
            "/v1/timeseries",
            params={
                "dataset": dataset,
                "market": market,
                "start": start,
                "end": end,
                "format": format,
            },
        )
        if format == "ndjson":
            return [json.loads(line) for line in response.text.splitlines() if line]
        import io

        import pyarrow.parquet as pq

        return pq.read_table(io.BytesIO(response.content))
