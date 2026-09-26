"""测试运行入口：把 backend 目录放进 sys.path，并在每个用例前重置内存台账。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.seed import SEED_ROWS  # noqa: E402
from app.store import store  # noqa: E402


@pytest.fixture(autouse=True)
def reset_store():
    """每个用例都从种子数据重新出发，避免导入流水互相污染。"""
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}
    yield
