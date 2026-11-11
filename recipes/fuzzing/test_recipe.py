from typing import assert_type

from hypothesis import given, strategies as st

from .generated.document.operations import (
    GetOrder,
    GetOrderData,
    ListOrders,
    ListOrdersData,
)
from .generated.runtime import ExecutionError, merge
from .recipe import data_strategy


def ean_13_barcode(data: GetOrderData, /) -> int | None:
    order = data["order"]

    if order is None:
        return None

    gs1_prefix = order["isbn"][:3]
    assert gs1_prefix in {"978", "979"}
    return int(order["isbn"])


@given(example=st.data())
def test_your_code_handles_any_order_the_server_can_send(
    example: st.DataObject,
) -> None:
    data = example.draw(data_strategy(GetOrder({"id": "o1"})))
    assert_type(data, GetOrderData)
    ean_13_barcode(data)


@given(example=st.data())
def test_a_merge_draws_a_tuple_of_its_parts(example: st.DataObject) -> None:
    order, orders = example.draw(
        data_strategy(merge(GetOrder({"id": "o1"}), ListOrders({})))
    )

    assert_type(order, GetOrderData)
    assert_type(orders, ListOrdersData)
    assert all(set(item) == {"id", "status"} for item in orders["orders"])


@given(example=st.data())
def test_a_request_returning_its_error_draws_data_only(
    example: st.DataObject,
) -> None:
    data = example.draw(data_strategy(GetOrder({"id": "o1"}).returning_error()))

    assert not isinstance(data, ExecutionError)
