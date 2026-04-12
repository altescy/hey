import asyncio
import contextvars
import dataclasses
import datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from os import PathLike
from pathlib import Path
from typing import NamedTuple


def normalize_path(path: str | PathLike) -> Path:
    return Path(path).resolve().expanduser().absolute()


class Stamp(NamedTuple):
    read: datetime.datetime
    mtime: float
    size: int


type _FileTypeState = dict[Path, tuple[Stamp, asyncio.Lock]]

_FILE_TIME_STATE: contextvars.ContextVar[_FileTypeState] = contextvars.ContextVar("_FILE_TIME_STATE", default={})


@dataclasses.dataclass(frozen=True, slots=True)
class _FileTime:
    path: Path
    stamp: Stamp

    _set_stamp: Callable[[Stamp], None] = dataclasses.field(repr=False, compare=False)

    def read(self) -> Stamp:
        stat = self.path.stat()
        stamp = Stamp(datetime.datetime.now(), stat.st_mtime, stat.st_size)
        self._set_stamp(stamp)
        return stamp

    def has_changed(self) -> bool:
        stat = self.path.stat()
        return self.stamp.mtime != stat.st_mtime or self.stamp.size != stat.st_size


@asynccontextmanager
async def use_file_time(path: str | PathLike) -> AsyncIterator[_FileTime]:
    path = normalize_path(path)

    state = _FILE_TIME_STATE.get()
    if path not in state:
        state[path] = (Stamp(datetime.datetime.fromtimestamp(0), 0, 0), asyncio.Lock())

    stamp, lock = state[path]

    def set_stamp(new_stamp: Stamp) -> None:
        state[path] = (new_stamp, lock)

    async with lock:
        yield _FileTime(
            path,
            stamp,
            _set_stamp=set_stamp,
        )
