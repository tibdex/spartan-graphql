from typing import Final, Literal

import httpx2
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.semconv._incubating.attributes import graphql_attributes  # noqa: PLC2701 (not stable yet)
from opentelemetry.trace import SpanKind, StatusCode

from recipes.tracing.generated.runtime import ExecutionError, Request
from recipes.tracing.generated.runtime.http import (
    ACCEPT,
    CONTENT_TYPE,
    is_graphql_response,
)

http: Final = httpx2.AsyncClient(
    base_url="https://bookshop.example",
    headers={"Accept": ACCEPT, "Content-Type": CONTENT_TYPE},
    # No timeout of its own: the caller's `asyncio.timeout()` is the deadline.
    timeout=None,
)
tracer: Final = trace.get_tracer("bookshop")


async def send[Data](request: Request[Literal["query", "mutation"], Data], /) -> Data:
    with tracer.start_as_current_span(
        f"{request.operation_type} {request.operation_name}",
        kind=SpanKind.CLIENT,
        attributes={
            graphql_attributes.GRAPHQL_OPERATION_NAME: request.operation_name,
            graphql_attributes.GRAPHQL_OPERATION_TYPE: request.operation_type,
        },
    ) as span:
        # In the span, so that it records variables failing to encode.
        prepared = request.prepare()
        # As headers, so that the server's spans join the trace.
        trace_context: dict[str, str] = {}
        inject(trace_context)

        response = await http.post(
            "/graphql", content=bytes(prepared), headers=trace_context
        )

        if not is_graphql_response(content_type=response.headers.get("Content-Type")):
            response.raise_for_status()

        data = prepared.parse(response.content)
        # A merge's data is a tuple, with each returned error in its request's place.
        results = data if isinstance(data, tuple) else (data,)
        # A raised error, `RequestError` included, marks the span on its own, but a returned one does not.
        if errors := [
            str(result) for result in results if isinstance(result, ExecutionError)
        ]:
            span.set_status(StatusCode.ERROR, "; ".join(errors))

        return data
