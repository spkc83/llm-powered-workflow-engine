"""Explicit dotted-path loading for deployment-supplied persistence adapters."""

import importlib
from typing import Any, Callable, cast


def load_factory(specification: str) -> Callable[..., Any]:
    """Load ``package.module:callable`` from trusted deployment configuration."""
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("Adapter factory must use 'package.module:callable' format")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError(f"Configured adapter factory is not callable: {specification}")
    return cast(Callable[..., Any], factory)
