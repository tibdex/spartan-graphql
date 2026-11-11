import asyncio
import json
from typing import Any, Final, Literal, NoReturn, assert_type

import pytest

from .generated.document.operations import GetOrder, GetOrderData
from .generated.runtime import ExecutionError, Request
from .recipe import QueryBatcher, Send

_ORDER: Final = {"id": "o1"}
_OTHER_ORDER: Final = {"id": "o2"}
_FIRST_ORDER_FAILED: Final = {
    "data": {"order_0": None, "order_1": _OTHER_ORDER},
    "errors": [{"message": "boom", "path": ["order_0"]}],
}


def _transport(
    *payloads: object,
) -> tuple[Send, list[Request[Literal["query"], Any]]]:
    sent_requests: list[Request[Literal["query"], Any]] = []
    answers = iter(payloads)

    async def send[Data](request: Request[Literal["query"], Data], /) -> Data:
        sent_requests.append(request)
        return request.prepare().parse(json.dumps(next(answers)).encode())

    return send, sent_requests


def test_the_requests_of_the_same_tick_are_merged() -> None:
    send, sent_requests = _transport(
        {"data": {"order_0": _ORDER, "order_1": _OTHER_ORDER}}
    )
    batcher = QueryBatcher(send)

    async def order(order_id: str, /) -> GetOrderData:
        return await batcher.send(GetOrder({"id": order_id}))

    async def page() -> tuple[GetOrderData, GetOrderData]:
        # Two parts of a page, each fetching for itself, started in the same tick.
        header = asyncio.create_task(order("header"))
        footer = asyncio.create_task(order("footer"))
        return await header, await footer

    first, second = asyncio.run(page())

    assert_type(first, GetOrderData)
    assert (first, second) == ({"order": _ORDER}, {"order": _OTHER_ORDER})
    # Both queries reached the transport as one merged request.
    (request,) = sent_requests
    assert request.operation_name == "BatchedQueries"


def test_an_eager_task_factory_still_batches() -> None:
    send, sent_requests = _transport(
        {"data": {"order_0": _ORDER, "order_1": _OTHER_ORDER}}
    )
    batcher = QueryBatcher(send)

    async def both() -> tuple[GetOrderData, GetOrderData]:
        asyncio.get_running_loop().set_task_factory(asyncio.eager_task_factory)
        return await asyncio.gather(
            batcher.send(GetOrder({"id": "o1"})),
            batcher.send(GetOrder({"id": "o2"})),
        )

    assert list(asyncio.run(both())) == [{"order": _ORDER}, {"order": _OTHER_ORDER}]
    assert len(sent_requests) == 1


def test_a_later_tick_is_another_request() -> None:
    send, sent_requests = _transport(
        {"data": {"order": _ORDER}}, {"data": {"order": _OTHER_ORDER}}
    )
    batcher = QueryBatcher(send)

    async def one_after_the_other() -> tuple[GetOrderData, GetOrderData]:
        first = await batcher.send(GetOrder({"id": "o1"}))
        second = await batcher.send(GetOrder({"id": "o2"}))
        return first, second

    assert asyncio.run(one_after_the_other()) == (
        {"order": _ORDER},
        {"order": _OTHER_ORDER},
    )
    # A merge of one request is sent as the request itself.
    assert [request.operation_name for request in sent_requests] == [
        "GetOrder",
        "GetOrder",
    ]


def test_a_failed_request_leaves_the_others_their_data() -> None:
    send, _ = _transport(_FIRST_ORDER_FAILED)
    batcher = QueryBatcher(send)

    async def both() -> tuple[BaseException, GetOrderData]:
        first, second = await asyncio.gather(
            batcher.send(GetOrder({"id": "o1"})),
            batcher.send(GetOrder({"id": "o2"})),
            return_exceptions=True,
        )
        assert isinstance(first, BaseException)
        assert not isinstance(second, BaseException)
        return first, second

    error, data = asyncio.run(both())

    assert isinstance(error, ExecutionError)
    assert str(error) == "boom"
    assert data == {"order": _OTHER_ORDER}


def test_a_request_returning_its_error_gets_it_returned() -> None:
    send, _ = _transport(_FIRST_ORDER_FAILED)
    batcher = QueryBatcher(send)

    async def both() -> tuple[
        GetOrderData | ExecutionError[GetOrderData], GetOrderData
    ]:
        return await asyncio.gather(
            batcher.send(GetOrder({"id": "o1"}).returning_error()),
            batcher.send(GetOrder({"id": "o2"})),
        )

    error, data = asyncio.run(both())

    assert isinstance(error, ExecutionError)
    assert data == {"order": _OTHER_ORDER}


def test_a_transport_failure_fails_every_request() -> None:
    async def send(_: Request[Literal["query"], Any], /) -> NoReturn:
        raise ConnectionError

    batcher = QueryBatcher(send)

    async def both() -> tuple[BaseException | GetOrderData, ...]:
        return await asyncio.gather(
            batcher.send(GetOrder({"id": "o1"})),
            batcher.send(GetOrder({"id": "o2"})),
            return_exceptions=True,
        )

    results = asyncio.run(both())

    assert all(isinstance(result, ConnectionError) for result in results)


def test_a_caller_giving_up_leaves_the_others_their_data() -> None:
    send, _ = _transport({"data": {"order_0": _ORDER, "order_1": _OTHER_ORDER}})
    batcher = QueryBatcher(send)

    async def patient() -> GetOrderData:
        impatient = asyncio.create_task(batcher.send(GetOrder({"id": "o1"})))
        other = asyncio.create_task(batcher.send(GetOrder({"id": "o2"})))
        # Both queued, so in the same batch.
        await asyncio.sleep(0)
        impatient.cancel()
        async with asyncio.timeout(1):
            return await other

    assert asyncio.run(patient()) == {"order": _OTHER_ORDER}


def test_a_response_without_data_fails_every_request() -> None:
    send, _ = _transport({"data": None, "errors": [{"message": "boom"}]})
    batcher = QueryBatcher(send)

    async def both() -> object:
        return await asyncio.gather(
            batcher.send(GetOrder({"id": "o1"}).returning_error()),
            batcher.send(GetOrder({"id": "o2"}).returning_error()),
        )

    # Raised rather than returned: the error is no request's own.
    with pytest.raises(ExecutionError, match="boom"):
        asyncio.run(both())


def test_every_caller_giving_up_cancels_the_request() -> None:
    async def both() -> None:
        stopped = asyncio.Event()

        async def send(_: Request[Literal["query"], Any], /) -> Any:  # noqa: ANN401
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        batcher = QueryBatcher(send)

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await asyncio.gather(
                    batcher.send(GetOrder({"id": "o1"})),
                    batcher.send(GetOrder({"id": "o2"})),
                )

        async with asyncio.timeout(1):
            await stopped.wait()

    asyncio.run(both())
