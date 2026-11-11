import asyncio
import json
from collections.abc import Mapping
from email import message_from_bytes
from io import BytesIO
from typing import Final, assert_type

import httpx2
import pytest

from . import recipe
from .generated.document.operations import AttachFiles
from .generated.runtime import merge
from .generated.runtime.http import CONTENT_TYPE, GRAPHQL_RESPONSE_JSON_MEDIA_TYPE
from .recipe import (
    Upload,
    _collected,
    decode,
    http,
    send,
)

_ISBN: Final = "9780140449433"


@pytest.fixture(name="sent_requests")
def sent_requests_fixture(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    sent_requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request, /) -> httpx2.Response:
        sent_requests.append(request)
        # A merge's root fields carry their index, as its document names them.
        data = (
            {"attachFiles_0": 2, "attachFiles_1": 2}
            if b"MergedOperation" in request.content
            else {"attachFiles": 2}
        )
        return httpx2.Response(
            200,
            json={"data": data},
            headers={"Content-Type": GRAPHQL_RESPONSE_JSON_MEDIA_TYPE},
        )

    monkeypatch.setattr(
        recipe,
        "http",
        httpx2.AsyncClient(
            transport=httpx2.MockTransport(handle),
            base_url=http.base_url,
            headers=http.headers,
        ),
    )
    return sent_requests


def _parts(request: httpx2.Request, /) -> Mapping[str, tuple[str | None, bytes]]:
    """Each part of the multipart body, by name: its filename and its content."""
    message = message_from_bytes(
        f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
        + request.content
    )
    parts: dict[str, tuple[str | None, bytes]] = {}

    for part in message.walk():
        if part.is_multipart():
            continue

        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True)
        assert isinstance(name, str), part
        assert isinstance(payload, bytes), part
        parts[name] = (part.get_filename(), payload)

    return parts


def test_a_file_goes_in_the_variables_like_any_other_value(
    sent_requests: list[httpx2.Request],
) -> None:
    cover = Upload(content=BytesIO(b"cover"), filename="cover.txt")
    scan = Upload(content=BytesIO(b"scan"), filename="scan.txt")
    request = AttachFiles(
        {
            "isbn": "9780140449433",
            "cover": cover,
            "attachments": [{"file": scan, "caption": "p. 3"}, {"file": cover}],
        }
    )

    data = asyncio.run(send(request))

    assert_type(data["attachFiles"], int)
    assert data["attachFiles"] == 2  # noqa: PLR2004
    (http_request,) = sent_requests
    assert http_request.headers["Content-Type"].startswith("multipart/form-data")
    parts = _parts(http_request)
    operations = json.loads(parts["operations"][1])
    assert operations["operationName"] == "AttachFiles"
    assert operations["variables"] == {
        "isbn": _ISBN,
        "cover": None,
        "attachments": [{"file": None, "caption": "p. 3"}, {"file": None}],
    }
    assert json.loads(parts["map"][1]) == {
        "0": ["variables.cover", "variables.attachments.1.file"],
        "1": ["variables.attachments.0.file"],
    }
    assert parts["0"] == ("cover.txt", b"cover")
    assert parts["1"] == ("scan.txt", b"scan")


def test_merged_requests_share_their_files(
    sent_requests: list[httpx2.Request],
) -> None:
    cover = Upload(content=BytesIO(b"cover"), filename="cover.txt")
    request = merge(
        AttachFiles({"isbn": _ISBN, "cover": cover, "attachments": []}),
        AttachFiles({"isbn": _ISBN, "cover": cover, "attachments": []}),
    )

    asyncio.run(send(request))

    (http_request,) = sent_requests
    assert json.loads(_parts(http_request)["map"][1]) == {
        "0": ["variables.cover_0", "variables.cover_1"]
    }


def test_a_request_without_files_is_plain_json(
    sent_requests: list[httpx2.Request],
) -> None:
    request = AttachFiles({"isbn": _ISBN, "attachments": []})

    asyncio.run(send(request))

    (http_request,) = sent_requests
    assert http_request.headers["Content-Type"] == CONTENT_TYPE
    assert http_request.content == bytes(request.prepare())


@pytest.mark.parametrize(
    "caption",
    [
        pytest.param("\0upload:9 is just text", id="a placeholder followed by text"),
        pytest.param('"\0upload:1', id="a quote before a placeholder"),
    ],
)
def test_a_string_resembling_a_placeholder_is_left_as_it_is(
    caption: str, sent_requests: list[httpx2.Request]
) -> None:
    scan = Upload(content=BytesIO(b"scan"), filename="scan.txt")
    request = AttachFiles(
        {"isbn": _ISBN, "attachments": [{"file": scan, "caption": caption}]}
    )

    asyncio.run(send(request))

    (http_request,) = sent_requests
    parts = _parts(http_request)
    assert json.loads(parts["operations"][1])["variables"]["attachments"] == [
        {"file": None, "caption": caption}
    ]
    assert json.loads(parts["map"][1]) == {"0": ["variables.attachments.0.file"]}


@pytest.mark.usefixtures("sent_requests")
def test_the_files_are_collected_in_a_context_of_their_own() -> None:
    request = AttachFiles(
        {
            "isbn": _ISBN,
            "cover": Upload(content=BytesIO(b"cover"), filename="cover.txt"),
            "attachments": [],
        }
    )

    asyncio.run(send(request))

    with pytest.raises(LookupError):
        _collected.get()

    with pytest.raises(LookupError):
        request.prepare()


def test_an_upload_is_input_only() -> None:
    with pytest.raises(TypeError, match=r"^`Upload` is an input-only scalar"):
        decode("cover.txt")
