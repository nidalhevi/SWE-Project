import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
BIN = os.environ.get("CHESS_BIN", os.path.join(HERE, "..", "..", "build", "release", "chess"))


@pytest.fixture(scope="session")
def engine():
    from chessvision.engine import EngineClient
    if not os.access(BIN, os.X_OK):
        pytest.skip("engine binary missing: run `make release` (looked at %s)" % BIN)
    with EngineClient(BIN) as e:
        yield e
