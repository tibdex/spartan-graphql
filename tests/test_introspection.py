import json
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler
from pathlib import Path, PurePosixPath
from typing import Final
from urllib.error import HTTPError

import pytest
from graphql import (
    GraphQLSchema,
    Source,
    build_schema,
    get_introspection_query,
    graphql_sync,
    parse,
    print_schema,
)

import spartan_graphql
from spartan_graphql import Config, DocumentSiblingModule, PackageLocation, generate
from spartan_graphql._cli._introspection import fetch_sdl
from spartan_graphql.runtime import RequestError
from spartan_graphql.runtime.http import GRAPHQL_RESPONSE_JSON_MEDIA_TYPE
from tests._graphql_server import GraphqlHandler
from tests._server import PostHandler, serve

_PACKAGE_DIRECTORY: Final = Path(spartan_graphql.__file__).parent
_DOCUMENT: Final = _PACKAGE_DIRECTORY / "_cli" / "_introspection.graphql"
_MODULE: Final = _DOCUMENT.with_name("_introspection_graphql.py")


def _generated_module() -> bytes:
    files = generate(
        document=parse(
            Source(_DOCUMENT.read_text(encoding="utf-8"), _DOCUMENT.as_posix())
        ),
        schema=build_schema("type Query { _: Boolean }"),
        config=Config(
            document_sibling_module=DocumentSiblingModule(
                name="{document}_graphql",
                package_location=PackageLocation(
                    module_root=PurePosixPath(_PACKAGE_DIRECTORY.parent.as_posix()),
                    package=spartan_graphql.__name__,
                ),
            ),
            non_null_directive_name="nonNull",
        ),
    )
    return files[PurePosixPath(_MODULE.relative_to(_PACKAGE_DIRECTORY).as_posix())]


def test_the_introspection_document_s_module_is_what_the_library_generates() -> None:
    # Only this module is checked in: the CLI uses the library's own runtime rather than a copy.
    assert _MODULE.read_bytes() == _generated_module()


def test_an_endpoint_is_introspected_with_its_headers_for_all_it_supports(
    graphql_server: Callable[[GraphqlHandler], str], bookshop_schema: GraphQLSchema
) -> None:
    queries: list[str] = []

    def handle(query: str, /, *, headers: Mapping[str, str]) -> object:
        assert headers["Authorization"] == "Bearer t"
        assert headers["User-Agent"].startswith("spartan-graphql/")
        queries.append(query)
        return graphql_sync(bookshop_schema, query).formatted

    sdl = fetch_sdl(graphql_server(handle), headers={"Authorization": "Bearer t"})

    assert print_schema(build_schema(sdl)) == print_schema(bookshop_schema)
    assert queries[1] == get_introspection_query(
        specified_by_url=True,
        directive_is_repeatable=True,
        schema_description=True,
        input_value_deprecation=True,
        one_of=True,
    )


def test_an_older_endpoint_is_asked_only_what_it_knows(
    graphql_server: Callable[[GraphqlHandler], str], bookshop_schema: GraphQLSchema
) -> None:
    later = {"description", "isDeprecated", "isOneOf", "isRepeatable", "specifiedByURL"}
    queries: list[str] = []

    def handle(query: str, /, *, headers: Mapping[str, str]) -> object:
        queries.append(query)
        result = graphql_sync(bookshop_schema, query).formatted

        if len(queries) == 1:
            assert result["data"] is not None
            known = {
                field["name"]
                for type_ in result["data"].values()
                for field in type_["fields"]
            }
            # Guards the test: a misspelled name would strip nothing.
            assert later <= known, later - known

            for type_ in result["data"].values():
                type_["fields"] = [
                    field for field in type_["fields"] if field["name"] not in later
                ]

        return result

    fetch_sdl(graphql_server(handle), headers={})

    assert queries[1] == get_introspection_query()


_REFUSAL: Final = "Introspection is disabled."


def _refusing(*, content_type: str) -> PostHandler:
    def handle(handler: BaseHTTPRequestHandler, /) -> None:
        # Read the body first, or closing resets the connection and may lose the response.
        handler.rfile.read(int(handler.headers["Content-Length"]))
        handler.send_response(422)
        handler.send_header("Content-Type", content_type)
        handler.end_headers()
        handler.wfile.write(json.dumps({"errors": [{"message": _REFUSAL}]}).encode())

    return handle


def test_an_http_error_is_urllib_s_own() -> None:
    with (
        serve(_refusing(content_type="text/plain")) as url,
        pytest.raises(HTTPError) as error_info,
    ):
        fetch_sdl(url, headers={})

    # urllib's error holds the response open.
    error_info.value.close()


def test_a_request_error_is_read_whatever_its_status() -> None:
    with (
        serve(_refusing(content_type=GRAPHQL_RESPONSE_JSON_MEDIA_TYPE)) as url,
        pytest.raises(RequestError, match=_REFUSAL),
    ):
        fetch_sdl(url, headers={})


if __name__ == "__main__":
    # `uv run python -m tests.test_introspection` regenerates it.
    _MODULE.write_bytes(_generated_module())
