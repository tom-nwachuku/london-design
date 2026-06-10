from __future__ import annotations

import builtins
import importlib
import sys

import pytest

from london.errors import LondonUsageError


def test_pack_build_import_does_not_import_typer(monkeypatch):
    sys.modules.pop("london.pack_build", None)
    real_import = builtins.__import__

    def reject_typer(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "typer" or name.startswith("typer."):
            raise AssertionError("london.pack_build must not import typer")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_typer)

    module = importlib.import_module("london.pack_build")

    assert module.write_london_pack
    assert "typer" not in module.__dict__


def test_pack_build_raises_london_usage_error_for_invalid_pack():
    from london.pack_build import validate_pack

    with pytest.raises(LondonUsageError) as excinfo:
        validate_pack({"pack_id": "x"})

    assert "director output missing/invalid" in str(excinfo.value)
