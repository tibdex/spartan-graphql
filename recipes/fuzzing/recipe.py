from typing import Any, NewType, cast

from hypothesis import strategies as st

from recipes.fuzzing.generated.runtime import Request

ISBN = NewType("ISBN", str)

# Without it, any `str` is drawn: the supertype of the `NewType`.
st.register_type_strategy(
    # Hypothesis supports a `NewType` here, but its annotation leaves it out.
    cast(Any, ISBN),
    st.from_regex(r"97[89][0-9]{10}", fullmatch=True),
)


def data_strategy[Data](request: Request[Any, Data], /) -> st.SearchStrategy[Data]:
    return st.from_type(request.data_type)
