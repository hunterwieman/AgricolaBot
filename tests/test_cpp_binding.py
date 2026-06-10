"""Stage 0 gate: the `agricola_cpp` pybind module builds and imports, and the
Python<->C++ string boundary works (the transport every real binding will use).

Skips cleanly if the module hasn't been built — see cpp/README.md for build
steps. The version constants are checked against the Python source of truth so a
future drift fails loudly.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# The pybind module is emitted into cpp/build/ by `cmake --build`.
_BUILD_DIR = pathlib.Path(__file__).resolve().parent.parent / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp",
    reason="cpp module not built — see cpp/README.md (cmake -S cpp -B cpp/build ...)",
)


def test_ping():
    assert agricola_cpp.ping() == "agricola_cpp ok"


def test_echo_roundtrips_strings():
    for s in ["", "hello", '{"__type__":"GameState"}', "🐑🐖🐄"]:
        assert agricola_cpp.echo(s) == s


def test_version_string():
    assert isinstance(agricola_cpp.version(), str)
    assert "agricola_cpp" in agricola_cpp.version()


def test_version_constants_match_python():
    from agricola.agents.nn.encoder import ENCODING_VERSION
    from agricola.agents.nn.schema import DATA_VERSION

    assert agricola_cpp.ENCODING_VERSION == ENCODING_VERSION
    assert agricola_cpp.DATA_VERSION == DATA_VERSION
