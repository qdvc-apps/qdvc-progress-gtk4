"""A permissive stand-in for PyGObject, so every ``qdvc.gtk4`` module can be
imported (class bodies, signal hookups, top-level code) without GTK
(spec §13). Any attribute is a distinct stub class; calling anything
returns a stub."""

import sys
import types


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _stub_class(name)

    def __or__(cls, other):
        return cls

    __ror__ = __or__


class Stub(metaclass=_Meta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Stub()

    def __call__(self, *args, **kwargs):
        return Stub()

    def __or__(self, other):
        return self

    __ror__ = __or__

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


_classes = {}


def _stub_class(name):
    if name not in _classes:
        _classes[name] = _Meta(name, (Stub,), {})
    return _classes[name]


def require_version(*_args):
    pass


def require_foreign(*_args):
    pass


class _Repository(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        mod = types.ModuleType(f"gi.repository.{name}")
        mod.__getattr__ = lambda attr: _stub_class(f"{name}.{attr}")
        sys.modules[f"gi.repository.{name}"] = mod
        setattr(self, name, mod)
        return mod


repository = _Repository("gi.repository")
sys.modules["gi.repository"] = repository
