import warnings
from functools import cache
from typing import Any, get_args

from pydantic import TypeAdapter

from recipes.validation.generated.runtime import ExecutionError, Request


def validate[Data](data: Data, /, *, request: Request[Any, Data]) -> None:
    if isinstance(data, tuple):
        # A merge's data, in which each request may have returned its error.
        for item, data_type in zip(data, get_args(request.data_type), strict=True):
            _validate(item, data_type)
    else:
        _validate(data, request.data_type)


def _validate(data: object, data_type: type[object], /) -> None:
    match data:
        case ExecutionError():
            # An error can leave no data at all.
            if (partial_data := data.parse_data()) is not None:
                _validate(partial_data, data_type)
        case _:
            _adapter(
                # mypy does not see a type as hashable.
                data_type  # type: ignore[arg-type]
            ).validate_python(data, strict=True)


# Cached, since building an adapter reads the whole type.
@cache
def _adapter(data_type: type[object], /) -> TypeAdapter[object]:
    # pydantic warns that it cannot keep a `ReadOnly` key from being written: the data is only read here.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Item '__typename'", category=UserWarning
        )
        return TypeAdapter(data_type)
