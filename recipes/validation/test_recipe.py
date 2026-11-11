import json
from typing import Any, Final

import pytest
from pydantic import ValidationError

from .generated.document.operations import GetOrder, ListOrders
from .generated.runtime import ExecutionError, Request, merge
from .recipe import validate

_ORDER: Final = {"id": "o1", "status": "SHIPPED"}


def _parsed[Data](request: Request[Any, Data], payload: object, /) -> Data:
    return request.prepare().parse(json.dumps(payload).encode())


def test_a_field_made_nullable_after_codegen_is_caught() -> None:
    request = GetOrder({"id": "o1"})
    body = b'{"data": {"order": {"id": "o1", "status": null}}}'
    data = request.prepare().parse(body)

    with pytest.raises(
        ValidationError,
        match=(
            r"^1 validation error for GetOrderData\n"
            r"order\.status\n"
            r"  Input should be 'PENDING' or 'SHIPPED' "
        ),
    ):
        validate(data, request=request)


@pytest.mark.parametrize(
    "order",
    [
        pytest.param({"id": "o1", "status": "LOST"}, id="a member the enum lacks"),
        pytest.param({"id": "o1"}, id="a key missing"),
        pytest.param({**_ORDER, "total": 3}, id="a key the operation did not select"),
        pytest.param({"id": 1, "status": "SHIPPED"}, id="a value of another type"),
    ],
)
def test_data_not_as_promised_is_rejected(order: object) -> None:
    request = GetOrder({"id": "o1"})
    data = _parsed(request, {"data": {"order": order}})

    with pytest.raises(ValidationError):
        validate(data, request=request)


def test_a_merge_s_data_is_checked_request_by_request() -> None:
    request = merge(GetOrder({"id": "o1"}), ListOrders({}))

    data = _parsed(request, {"data": {"order_0": _ORDER, "orders_1": [_ORDER]}})
    validate(data, request=request)

    with pytest.raises(ValidationError):
        validate(
            _parsed(request, {"data": {"order_0": _ORDER, "orders_1": [{"id": "o2"}]}}),
            request=request,
        )


def test_a_returned_error_s_partial_data_is_checked() -> None:
    request = GetOrder({"id": "o1"}).returning_error()
    errors = [{"message": "boom", "path": ["order"]}]

    result = _parsed(request, {"data": {"order": None}, "errors": errors})
    assert isinstance(result, ExecutionError)
    validate(result, request=request)

    with pytest.raises(ValidationError):
        validate(
            _parsed(request, {"data": {"order": {"id": "o1"}}, "errors": errors}),
            request=request,
        )


def test_a_merge_s_returned_error_is_checked_as_partial_data() -> None:
    request = merge(GetOrder({"id": "o1"}).returning_error(), ListOrders({}))
    errors = [{"message": "boom", "path": ["order_0"]}]

    result = _parsed(
        request, {"data": {"order_0": None, "orders_1": [_ORDER]}, "errors": errors}
    )
    assert isinstance(result[0], ExecutionError)
    validate(result, request=request)

    with pytest.raises(ValidationError):
        validate(
            _parsed(
                request,
                {
                    "data": {"order_0": {"id": "o1"}, "orders_1": [_ORDER]},
                    "errors": errors,
                },
            ),
            request=request,
        )
