import asyncio
from typing import Final, assert_type

import httpx2
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind, StatusCode

from . import recipe
from .generated.document.operations import GetOrder, GetOrderData
from .generated.runtime import ExecutionError, merge
from .generated.runtime.http import GRAPHQL_RESPONSE_JSON_MEDIA_TYPE
from .recipe import http, send

_EXPORTER: Final = InMemorySpanExporter()
_PROVIDER: Final = TracerProvider()
_PROVIDER.add_span_processor(SimpleSpanProcessor(_EXPORTER))
# Once per process: the recipe's tracer resolves to it from then on.
trace.set_tracer_provider(_PROVIDER)

_ORDER: Final = {"id": "o1"}
_ERROR: Final = {"message": "boom", "path": ["order"]}


@pytest.fixture(name="sent_requests")
def sent_requests_fixture(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    _EXPORTER.clear()
    sent_requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request, /) -> httpx2.Response:
        sent_requests.append(request)
        payload: dict[str, object]

        # An order asked by the id `fail` fails, alone or as the second of a merge.
        if b"MergedOperation" in request.content:
            payload = {
                "data": {"order_0": _ORDER, "order_1": None},
                "errors": [{**_ERROR, "path": ["order_1"]}],
            }
        elif b"fail" in request.content:
            payload = {"data": {"order": None}, "errors": [_ERROR]}
        else:
            payload = {"data": {"order": _ORDER}}

        return httpx2.Response(
            200,
            json=payload,
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


def test_a_span_is_named_after_the_operation_and_tells_its_type(
    sent_requests: list[httpx2.Request],
) -> None:
    data = asyncio.run(send(GetOrder({"id": "o1"})))

    assert_type(data, GetOrderData)
    (span,) = _EXPORTER.get_finished_spans()
    assert span.name == "query GetOrder"
    assert span.kind == SpanKind.CLIENT
    assert span.attributes == {
        "graphql.operation.name": "GetOrder",
        "graphql.operation.type": "query",
    }
    assert span.status.status_code == StatusCode.UNSET
    (request,) = sent_requests
    assert request.headers["traceparent"].startswith("00-")


@pytest.mark.usefixtures("sent_requests")
def test_a_raised_error_marks_the_span() -> None:
    with pytest.raises(ExecutionError):
        asyncio.run(send(GetOrder({"id": "fail"})))

    (span,) = _EXPORTER.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]


@pytest.mark.usefixtures("sent_requests")
def test_a_returned_error_marks_the_span_too() -> None:
    result = asyncio.run(send(GetOrder({"id": "fail"}).returning_error()))

    assert isinstance(result, ExecutionError)
    (span,) = _EXPORTER.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == str(result)


@pytest.mark.usefixtures("sent_requests")
def test_a_merge_s_returned_error_marks_the_span_too() -> None:
    request = merge(GetOrder({"id": "o1"}), GetOrder({"id": "fail"}).returning_error())

    order, result = asyncio.run(send(request))

    assert order == {"order": _ORDER}
    assert isinstance(result, ExecutionError)
    (span,) = _EXPORTER.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description == str(result)
