from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_core_imports_without_retrieval_or_agent_frameworks() -> None:
    source_root = Path(__file__).resolve().parents[3] / "src"
    script = """
import importlib.abc
import sys

blocked = ("deepagents", "langchain", "langchain_core", "langgraph", "numpy", "sqlite_vec")

class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise ModuleNotFoundError(f"blocked optional dependency: {fullname}")
        return None

sys.meta_path.insert(0, BlockOptional())
import document_enhancer.cli
from document_enhancer.core import CoreRunner
assert CoreRunner is not None
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
