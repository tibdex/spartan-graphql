from collections.abc import Callable
from pathlib import Path


def test_the_recipes_type_check(assert_type_checks: Callable[[Path], None]) -> None:
    assert_type_checks(Path(__file__).parent)
