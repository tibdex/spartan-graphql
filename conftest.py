"""What the tests and the recipes share."""

import shutil
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import strategies as st


def pytest_configure() -> None:
    # JSON has no NaN and no infinity, so no generated value holds one.
    st.register_type_strategy(
        Decimal, st.decimals(allow_nan=False, allow_infinity=False)
    )
    st.register_type_strategy(float, st.floats(allow_nan=False, allow_infinity=False))


@pytest.fixture(name="assert_type_checks", params=["mypy", "pyright", "pyrefly", "ty"])
def assert_type_checks_fixture(
    request: pytest.FixtureRequest,
) -> Callable[[Path], None]:
    name = request.param
    checker = shutil.which(name, path=str(Path(sys.executable).parent))
    assert checker is not None, (
        f"Expected `{name}` to be installed next to the interpreter, as a development dependency."
    )

    def assert_type_checks(package: Path, /) -> None:
        arguments = {
            "mypy": ["--strict", "--python-executable", sys.executable],
            "ty": [
                "check",
                "--python",
                sys.executable,
                "--extra-search-path",
                str(package.parent),
            ],
            "pyright": ["--pythonpath", sys.executable],
            # Pyrefly's default preset reports none of the mistakes the other checkers catch.
            "pyrefly": [
                "check",
                "--preset",
                "strict",
                "--python-interpreter-path",
                sys.executable,
                "--search-path",
                str(package.parent),
            ],
        }[name]
        result = subprocess.run(
            [checker, *arguments, str(package)],
            capture_output=True,
            check=False,
            cwd=package.parent,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr

    return assert_type_checks
