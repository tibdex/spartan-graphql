import subprocess
import sys
from pathlib import Path


def pytest_configure() -> None:
    # Before the tests import the packages.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "spartan_graphql",
            Path(__file__).with_name("graphql.config.json"),
        ],
        check=True,
    )
