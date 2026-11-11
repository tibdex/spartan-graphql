from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack
from pathlib import PurePosixPath

import pytest
from graphql import GraphQLSchema

import bookshop.transport
from spartan_graphql import generate
from spartan_graphql.generate import _Params
from tests._bookshop import _read_bookshop_args
from tests._graphql_server import GraphqlHandler, answer_graphql
from tests._server import PostHandler, serve


@pytest.fixture(name="_bookshop_args", scope="session")
def bookshop_args_fixture() -> _Params:
    return _read_bookshop_args()


@pytest.fixture(name="bookshop_schema", scope="session")
def bookshop_schema_fixture(_bookshop_args: _Params) -> GraphQLSchema:
    return _bookshop_args["schema"]


@pytest.fixture(name="bookshop_files", scope="session")
def files_fixture(_bookshop_args: _Params) -> Mapping[PurePosixPath, bytes]:
    return generate(**_bookshop_args)


@pytest.fixture(name="graphql_server")
def graphql_server_fixture() -> Iterator[Callable[[GraphqlHandler], str]]:
    with ExitStack() as stack:
        yield (
            lambda graphql_handler: (
                stack.enter_context(serve(answer_graphql(graphql_handler))) + "/graphql"
            )
        )


@pytest.fixture(name="bookshop_server")
def bookshop_server_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[PostHandler], None]]:
    with ExitStack() as stack:

        def start(post_handler: PostHandler, /) -> None:
            url = stack.enter_context(serve(post_handler))
            monkeypatch.setattr(bookshop.transport, "BASE_URL", url)

        yield start
