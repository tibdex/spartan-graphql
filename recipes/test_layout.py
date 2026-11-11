from pathlib import Path

import pytest

_RECIPES = Path(__file__).parent


@pytest.mark.parametrize(
    "recipe",
    [
        pytest.param(path, id=path.name)
        for path in sorted(_RECIPES.iterdir())
        if (path / "__init__.py").is_file()
    ],
)
def test_a_recipe_is_a_single_copyable_module_and_its_test(recipe: Path) -> None:
    assert {path.name for path in recipe.glob("*.py")} == {
        "__init__.py",
        "recipe.py",
        "test_recipe.py",
    }
