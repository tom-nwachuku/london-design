"""Compatibility shim for the London dossier renderer."""

from __future__ import annotations

from london.dossier import renderer as _renderer

__file__ = _renderer.__file__

for _name in dir(_renderer):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_renderer, _name)

__all__ = [name for name in globals() if not name.startswith("__") and name != "_renderer"]
