import json
import re
from collections.abc import Callable
from contextvars import ContextVar, copy_context
from dataclasses import dataclass
from functools import partial
from typing import BinaryIO, Final, Literal, NoReturn

import httpx2

from recipes.upload.generated.runtime import Request
from recipes.upload.generated.runtime.http import (
    ACCEPT,
    CONTENT_TYPE,
    is_graphql_response,
)

# A NUL character never appears in a string a person would send.
_PREFIX: Final = "\0upload:"
_PLACEHOLDER: Final = re.compile(f"{_PREFIX}(\\d+)")


@dataclass(frozen=True, kw_only=True)
class Upload:
    content: BinaryIO
    filename: str
    content_type: str = "application/octet-stream"


_collected: ContextVar[tuple[Upload, ...]] = ContextVar("_collected")


def encode(value: Upload, /) -> str:
    uploads = _collected.get()

    # The same file in several places is sent once, mapped to each of them.
    index = next((i for i, upload in enumerate(uploads) if upload is value), None)

    if index is None:
        index = len(uploads)
        _collected.set((*uploads, value))

    return f"{_PREFIX}{index}"


def _collect_uploads[T](prepare: Callable[[], T], /) -> tuple[T, tuple[Upload, ...]]:
    context = copy_context()
    context.run(_collected.set, ())
    return context.run(prepare), context[_collected]


def decode(value: object, /) -> NoReturn:
    raise TypeError(f"`Upload` is an input-only scalar, but got `{value!r}`.")


def _multipart_fields(body: bytes, /) -> dict[str, str]:
    paths: dict[str, list[str]] = {}

    def nullify_placeholders(value: object, path: tuple[str, ...], /) -> object:
        match value:
            case str() if placeholder := _PLACEHOLDER.fullmatch(value):
                paths.setdefault(placeholder[1], []).append(".".join(path))
                return None
            case dict():
                return {
                    key: nullify_placeholders(item, (*path, key))
                    for key, item in value.items()
                }
            case list():
                return [
                    nullify_placeholders(item, (*path, str(position)))
                    for position, item in enumerate(value)
                ]
            case _:
                return value

    operations = nullify_placeholders(json.loads(body), ())
    return {"operations": json.dumps(operations), "map": json.dumps(paths)}


# No default `Content-Type`: each request sets its own, JSON or multipart.
http: Final = httpx2.AsyncClient(
    base_url="https://bookshop.example",
    headers={"Accept": ACCEPT},
    # No timeout of its own: the caller's `asyncio.timeout()` is the deadline.
    timeout=None,
)


async def send[Data](request: Request[Literal["query", "mutation"], Data], /) -> Data:
    prepared, uploads = _collect_uploads(request.prepare)
    post = partial(http.post, "/graphql")

    if uploads:
        response = await post(
            data=_multipart_fields(bytes(prepared)),
            files={
                str(index): (upload.filename, upload.content, upload.content_type)
                for index, upload in enumerate(uploads)
            },
        )
    else:
        response = await post(
            content=bytes(prepared), headers={"Content-Type": CONTENT_TYPE}
        )

    if not is_graphql_response(content_type=response.headers.get("Content-Type")):
        response.raise_for_status()

    return prepared.parse(response.content)
