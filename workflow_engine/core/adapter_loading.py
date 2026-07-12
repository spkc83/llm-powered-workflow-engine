"""Explicit dotted-path loading for deployment-supplied persistence adapters."""

import importlib
from typing import Callable, TypeVar, cast


Factory = TypeVar("Factory", bound=Callable)


def load_factory(specification: str) -> Factory:
    """Load ``package.module:callable`` from trusted deployment configuration."""
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("Adapter factory must use 'package.module:callable' format")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute, None)
    if not callable(factory):
        raise ValueError(f"Configured adapter factory is not callable: {specification}")
    return cast(Factory, factory)
