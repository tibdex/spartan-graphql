from collections.abc import Mapping, Set as AbstractSet
from dataclasses import dataclass, field
from typing import final

from graphql import GraphQLError, assert_name

from spartan_graphql._error_note import error_note
from spartan_graphql.document_sibling_module import DocumentSiblingModule
from spartan_graphql.scalar import Scalar


@final
@dataclass(frozen=True, kw_only=True)
class Config:
    document_sibling_module: DocumentSiblingModule | None = None
    """When `None`, each document's operations and fragments go to a module named after it in the generated package's `document` subpackage."""

    injector_names: AbstractSet[str] = frozenset()
    """The names of the variables and input fields that injectors supply.

    They are left out of the generated types, and must have the same type wherever they appear, nullability aside.
    """

    non_null_directive_name: str | None = None
    """The name of the client directive asserting that a field is not null, stripped from the document before it is sent."""

    scalars: Mapping[str, Scalar] = field(default_factory=dict)
    """The Python type, and codec, of each scalar by its GraphQL name."""

    struct_interface_name: str | None = None
    """The name of the interface every struct implements: a type whose single field carries a JSON payload.

    The payload is typed by the input type the struct is named after: `BookFilter` for `BookFilterStruct` when the interface is `Struct`.
    """

    def __post_init__(self) -> None:
        for field_name, names in (
            ("injector_names", sorted(self.injector_names)),
            ("non_null_directive_name", [self.non_null_directive_name]),
            ("struct_interface_name", [self.struct_interface_name]),
        ):
            with error_note(f"In `{field_name}`."):
                for name in names:
                    if name is None:
                        continue

                    try:
                        assert_name(name)
                    except GraphQLError as error:
                        raise ValueError(error.message) from error
