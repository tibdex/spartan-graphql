import json
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import TypeAdapter

from bookshop.graphql.runtime import Operation
from bookshop.graphql.runtime._reflection import build_encoder
from bookshop.injectors import INJECTORS
from tests._bookshop import all_bookshop_operations


def _response_body(data: object, /, *, data_type: object) -> bytes:
    if (encode := build_encoder(data_type)) is not None:
        data = encode(data)
    return json.dumps({"data": data}).encode()


def _validate(data: object, /, *, data_type: type[object]) -> None:
    TypeAdapter(data_type).validate_python(data, strict=True)


@pytest.mark.filterwarnings("ignore:Item '__typename':UserWarning")
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(operation, id=repr(operation))
        for operation in all_bookshop_operations()
    ],
)
@settings(max_examples=25, deadline=None)
@given(example=st.data())
def test_any_data_of_the_generated_type_survives_the_wire_and_is_what_the_type_promises(
    operation: Operation[Any, Any, Any], example: st.DataObject
) -> None:
    data_type = operation._data_type
    data = example.draw(st.from_type(data_type))
    body = _response_body(data, data_type=data_type)

    parsed_data = operation({}).prepare(injectors=INJECTORS).parse(body)

    assert parsed_data == data
    _validate(parsed_data, data_type=data_type)
