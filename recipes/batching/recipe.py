import asyncio
from dataclasses import dataclass
from typing import Final, Literal, Protocol, assert_never, cast, final

from recipes.batching.generated.runtime import (
    ExecutionError,
    OperationRequest,
    Request,
    merge,
)


class Send(Protocol):
    async def __call__[Data](
        self, request: Request[Literal["query"], Data], /
    ) -> Data: ...


type _Requests = list[OperationRequest[Literal["query"], object]]


@final
@dataclass(kw_only=True)
class _Batch:
    requests: _Requests
    task: asyncio.Task[tuple[object, ...]]
    waiter_count: int = 0


class QueryBatcher:
    """Sends the queries of one event-loop tick as one merged request, as a DataLoader does on a server."""

    def __init__(self, send: Send, /) -> None:
        self._send: Final = send
        self._batch: _Batch | None = None

    async def send[Data](
        self, request: OperationRequest[Literal["query"], Data], /
    ) -> Data:
        if self._batch is None:
            requests: _Requests = []
            # Not `asyncio.create_task()`, which an eager task factory would run at once.
            # The task starts on the next tick, after the other coroutines of this tick added their request.
            task = asyncio.Task(self._run(requests))
            self._batch = _Batch(requests=requests, task=task)

        batch = self._batch
        index = len(batch.requests)
        batch.requests.append(request)
        batch.waiter_count += 1

        try:
            # A caller can give up, such as on its `asyncio.timeout()`.
            # The shield then leaves the others their data.
            results = await asyncio.shield(batch.task)
        finally:
            batch.waiter_count -= 1

            # No caller waits anymore, so neither does the transport.
            if not batch.waiter_count:
                batch.task.cancel()

        result = results[index]

        if isinstance(result, ExecutionError):
            match request.execution_error_handling:
                case "raise":
                    raise result
                case "return":
                    pass
                case _ as never:
                    assert_never(never)

        # `Data` includes the error of a request returning it.
        return cast(Data, result)

    async def _run(self, requests: _Requests, /) -> tuple[object, ...]:
        # The next tick starts another batch.
        self._batch = None
        merged = merge(
            [
                # So that a failed request leaves the others their data.
                request.returning_error()
                for request in requests
            ],
            operation_name="BatchedQueries",
        )
        return await self._send(merged)
