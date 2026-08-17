import chess
import pytest

from decodex.engine import EngineNotFound, RawEngine, find_engine


@pytest.fixture(scope="session")
def engine_path() -> str:
    try:
        return find_engine()
    except EngineNotFound as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="session")
def raw_engine(engine_path: str):
    with RawEngine(engine_path) as raw:
        yield raw


@pytest.fixture(scope="session")
def search_engine(engine_path: str):
    import chess.engine

    engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    # A single thread keeps the search deterministic, so test assertions about
    # specific evaluations do not flake.
    engine.configure({"Threads": 1, "Hash": 128})
    try:
        yield engine
    finally:
        engine.quit()


@pytest.fixture
def start_board() -> chess.Board:
    return chess.Board()
