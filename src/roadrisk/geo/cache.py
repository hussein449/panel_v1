"""Step 2.9 — cache by geography, and never let it make a run look fresher than it is.

*"Cache by geography — DEM tiles, ERA5, OSM extracts, detections. A second corridor in
the same country is nearly free."* That line from the brief is a cost rule, and the
measured costs on this pipeline say it is the right one: a strategic-network fetch took
4 to 46 seconds depending on which Overpass mirror answered, and a Mapillary corridor
took 29 to 76.

**A cache that hides the age of what it serves is worse than no cache.** Everything else
in this package exists to stop a number looking more certain than it is, and a silent
cache is the same failure wearing different clothes: a run that quietly used a
three-month-old road network while presenting itself as today's assessment. So every
entry records when it was fetched, every hit is counted, and the age of the oldest thing
used travels into the report alongside the values it produced.

**Content-addressed, so the key is the question.** An entry is keyed by the adapter that
asked, a digest of the exact request, and — where it makes sense — a *quantised* spatial
key. The quantisation is what turns "the same corridor twice" into "the same region
twice": snap a bounding box out to a grid and two different roads through the same
county ask an identical question, so the second one is free. Where a request is
corridor-shaped rather than area-shaped it is still cached, but only a re-run of that
same corridor will hit it, and this module does not pretend otherwise.

**Staleness is per source, because the sources age differently.** OpenStreetMap changes
every day. Mapillary detections change when somebody drives past with a camera.
Copernicus DEM is a fixed 2019-2021 product that will never change again. One expiry
policy for all three would be wrong for two of them.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import threading
import time
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

#: Where entries live unless a caller says otherwise. Overridable so a CI run, a
#: container or a test never writes into somebody's home directory.
CACHE_DIR_ENV = "ROADRISK_CACHE_DIR"

#: Grid the network bounding box is snapped to. A tenth of a degree is roughly 11 km
#: north-south: coarse enough that two corridors in the same county share an entry,
#: fine enough that snapping never adds more area than the 20 km margin already does.
DEFAULT_GRID_DEG = 0.1

#: How long an entry from each source stays usable. OpenStreetMap changes daily, but a
#: month-old road network is not materially different for a risk assessment, and
#: re-fetching a 2,000-way region every run is rude to a service run on donations.
#: Mapillary changes only when someone drives past with a camera.
MAX_AGE_DAYS: dict[str, float] = {
    "overpass": 30.0,
    "mapillary": 90.0,
}
DEFAULT_MAX_AGE_DAYS = 30.0

#: Entries older than this are reported prominently even when still inside their expiry.
STALE_WARNING_DAYS = 14.0


@dataclass(frozen=True)
class CacheEntry:
    """One stored answer, and when it was true."""

    key: str
    source: str
    payload: Any
    fetched_at: float

    @property
    def age_days(self) -> float:
        return max(time.time() - self.fetched_at, 0.0) / 86_400.0

    @property
    def fetched_on(self) -> str:
        return datetime.fromtimestamp(self.fetched_at, tz=UTC).strftime("%Y-%m-%d")

    def expired(self, max_age_days: float) -> bool:
        return self.age_days > max_age_days


class Cache(Protocol):
    """Anything that can remember an answer between runs."""

    def get(self, key: str) -> CacheEntry | None: ...

    def put(self, key: str, source: str, payload: Any) -> None: ...


@dataclass
class NullCache:
    """Remembers nothing. The default, so nothing is cached unless it is asked for."""

    def get(self, key: str) -> CacheEntry | None:
        return None

    def put(self, key: str, source: str, payload: Any) -> None:
        return None


@dataclass
class FileCache:
    """Gzipped JSON on disk, one file per key.

    Written to a temporary name and renamed into place, because a run interrupted
    halfway through a 40 MB network fetch must not leave a half-file that the next run
    reads as a valid answer.
    """

    directory: Path
    max_age_days: dict[str, float] = field(default_factory=lambda: dict(MAX_AGE_DAYS))

    @classmethod
    def default(cls) -> FileCache:
        configured = os.environ.get(CACHE_DIR_ENV)
        root = Path(configured) if configured else Path.home() / ".cache" / "roadrisk"
        return cls(directory=root)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json.gz"

    def get(self, key: str) -> CacheEntry | None:
        path = self.path_for(key)
        if not path.exists():
            return None

        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                stored = json.load(handle)
            entry = CacheEntry(
                key=key,
                source=str(stored["source"]),
                payload=stored["payload"],
                fetched_at=float(stored["fetched_at"]),
            )
        except (OSError, ValueError, KeyError):
            # A corrupt entry is a miss, not a crash. Deleting it means the next run
            # repairs itself rather than failing the same way forever.
            path.unlink(missing_ok=True)
            return None

        limit = self.max_age_days.get(entry.source, DEFAULT_MAX_AGE_DAYS)
        if entry.expired(limit):
            path.unlink(missing_ok=True)
            return None
        return entry

    def put(self, key: str, source: str, payload: Any) -> None:
        path = self.path_for(key)
        # Unique per *writer*, not per process. The pid alone was enough while one
        # corridor ran at a time. Step 5.1d put two jobs in a thread pool and 5.2a fans
        # the adapters out inside each, so two writers now share a pid and genuinely
        # race: they would open the same temporary path, interleave their gzip streams,
        # and one would rename a half-written file into place while the other still had
        # it open. `get` treats a corrupt entry as a miss and deletes it, so the symptom
        # is not corruption — it is a key that silently never caches, in the busiest
        # region, which is the hardest kind of performance bug to go looking for.
        temporary = path.with_suffix(f".{os.getpid()}.{uuid4().hex}.tmp")

        try:
            # Inside the try, not before it: a cache directory that cannot be created —
            # a read-only volume, a file already sitting at that path — must cost the
            # run its speed and nothing else.
            self.directory.mkdir(parents=True, exist_ok=True)
            with gzip.open(temporary, "wt", encoding="utf-8") as handle:
                json.dump(
                    {
                        "source": source,
                        "fetched_at": time.time(),
                        "payload": payload,
                    },
                    handle,
                )
            temporary.replace(path)
        except OSError:
            # A cache that cannot write is a slow pipeline, not a broken one — and
            # that has to include the tidying up. missing_ok= only swallows
            # FileNotFoundError, so on a path whose parent is a file this unlink
            # raises NotADirectoryError and the handler meant to absorb the failure
            # becomes the thing that propagates it. Windows hid this by reporting the
            # same condition as ENOENT, which missing_ok= does absorb.
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


@dataclass
class CacheReport:
    """What the cache did, and how old the answers were.

    Carried into the run's warnings so a reader can see that a result rests on stored
    data, and how stale that data was, without having to know a cache exists.
    """

    hits: int = 0
    misses: int = 0
    ages: list[tuple[str, float, str]] = field(default_factory=list)
    #: One report is shared by every cached client in a corridor, and from step 5.2a
    #: those clients run on different threads. `self.hits += 1` is a load, an add and a
    #: store, so two branches recording a hit at once lose one of them — and the number
    #: that goes wrong is the one printed in the sentence telling a reader how much of
    #: their assessment rests on stored data.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_hit(self, entry: CacheEntry) -> None:
        with self._lock:
            self.hits += 1
            self.ages.append((entry.source, entry.age_days, entry.fetched_on))

    def record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    @property
    def used(self) -> bool:
        return bool(self.hits)

    @property
    def oldest_days(self) -> float:
        return max((age for _, age, _ in self.ages), default=0.0)

    def notes(self) -> list[str]:
        if not self.hits:
            return []

        oldest_source, oldest_age, oldest_date = max(self.ages, key=lambda row: row[1])
        note = (
            f"{self.hits} of {self.hits + self.misses} source fetch(es) were served from "
            f"the cache rather than the network. The oldest was {oldest_source} data "
            f"fetched on {oldest_date}, {oldest_age:.0f} day(s) ago."
        )
        if oldest_age >= STALE_WARNING_DAYS:
            note += (
                " That is old enough that the road may have changed since. Clear the "
                "cache and re-run before presenting this as a current assessment."
            )
        return [note]


class SingleFlight:
    """One in-flight fetch per key, so concurrent misses do not all pay for it.

    Step 5.2a's note in `STEPS.md`: *"the chord is where the cache stops being a cache
    — parallel adapter branches racing on the same half-degree grid cell need a lock or
    a shared store, or the first corridor pays its 55.5 s several times over."* Two
    corridors in the same county, running as two jobs in 5.1d's pool, both miss on the
    grid-rounded network query and both fetch it. The second one's answer is discarded
    the moment the first is written.

    So a miss takes a lock named by the key, and re-checks the cache under it: the loser
    of the race wakes up to a hit. Different keys take different locks and never wait
    for each other, which is what keeps the fan-out a fan-out.

    **In-process only, and deliberately.** Two uvicorn workers, or two Celery workers on
    two machines, still duplicate the fetch. Making that not so needs a lock *file* with
    an expiry and stale-owner recovery — a distributed lock, with everything that
    implies — to save one duplicated fetch on a cold cache. The correctness of the write
    does not depend on it: `FileCache.put` renames into place, so the loser overwrites
    the winner with an identical answer.
    """

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        # Guards the dictionary itself, and is held only long enough to look a key up.
        # Never held across a fetch, or every key would wait for every other one.
        self._guard = threading.Lock()

    def lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = self._locks.setdefault(key, threading.Lock())
            return lock


def digest(*parts: object) -> str:
    """A stable key from the pieces of a request.

    ``repr`` rather than ``str`` so that ``1`` and ``"1"`` do not collide, and sorted
    dictionaries so that two identical requests built in a different order agree.
    """
    material = "|".join(_stable(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _stable(value: object) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{k!r}:{_stable(v)}" for k, v in sorted(value.items())) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable(item) for item in value) + "]"
    if isinstance(value, float):
        # Round before hashing: two bounding boxes differing in the twelfth decimal are
        # the same question, and floating point arithmetic will produce both.
        return repr(round(value, 9))
    return repr(value)


def quantise_bbox(
    bbox: tuple[float, float, float, float],
    grid_deg: float = DEFAULT_GRID_DEG,
) -> tuple[float, float, float, float]:
    """Snap a bounding box outwards to a grid, so nearby requests become one request.

    Outwards on every side, never inwards: a snapped box always contains the box that
    was asked for, so quantising can only ever fetch more than was needed. Fetching
    slightly more is a cost; fetching slightly less would be a wrong answer.

    This is the whole mechanism behind "a second corridor in the same country is nearly
    free" — two different roads through one county round to the same box, ask the same
    question, and the second one never leaves the disk.
    """
    if grid_deg <= 0:
        raise ValueError(f"grid_deg must be positive, got {grid_deg}")

    west, south, east, north = bbox
    return (
        math.floor(west / grid_deg) * grid_deg,
        math.floor(south / grid_deg) * grid_deg,
        math.ceil(east / grid_deg) * grid_deg,
        math.ceil(north / grid_deg) * grid_deg,
    )


def collect_notes(reports: Iterable[CacheReport]) -> list[str]:
    """Every cache report's note, for the pipeline's warnings."""
    return [note for report in reports for note in report.notes()]


__all__ = [
    "CACHE_DIR_ENV",
    "DEFAULT_GRID_DEG",
    "DEFAULT_MAX_AGE_DAYS",
    "MAX_AGE_DAYS",
    "STALE_WARNING_DAYS",
    "Cache",
    "CacheEntry",
    "CacheReport",
    "FileCache",
    "NullCache",
    "SingleFlight",
    "collect_notes",
    "digest",
    "quantise_bbox",
]
