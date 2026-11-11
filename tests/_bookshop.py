import shutil
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import Any, Final

from bookshop.graphql.runtime import Operation
from spartan_graphql import generate
from spartan_graphql._cli._graphql_config import read_graphql_config
from spartan_graphql.generate import _Params

_REPOSITORY_DIRECTORY: Final = Path(__file__).parents[1]
BOOKSHOP_DIRECTORY: Final = _REPOSITORY_DIRECTORY / "bookshop"
BOOKSHOP_GENERATED_PACKAGE_DIRECTORY: Final = BOOKSHOP_DIRECTORY / "graphql"


def copy_bookshop(directory: Path, /) -> None:
    for path in [
        BOOKSHOP_DIRECTORY / "schema.graphqls",
        *BOOKSHOP_DIRECTORY.glob("*.graphql"),
    ]:
        shutil.copy(path, directory)


def _read_bookshop_args() -> _Params:
    (args,) = read_graphql_config(BOOKSHOP_DIRECTORY / "graphql.config.yml").values()
    return args


def all_bookshop_operations() -> list[Operation[Any, Any, Any]]:
    operations = [
        value
        for path in generate(**_read_bookshop_args())
        if path.stem != "__init__"
        for value in vars(import_module(_module_name(path))).values()
        if isinstance(value, Operation)
    ]
    assert operations
    return operations


def _module_name(path: PurePosixPath, /) -> str:
    written_to = (BOOKSHOP_GENERATED_PACKAGE_DIRECTORY / path).resolve()
    return ".".join(written_to.relative_to(_REPOSITORY_DIRECTORY).with_suffix("").parts)
