"""Typed application dependency ownership."""

from __future__ import annotations

from dataclasses import dataclass

from pyganini import csrf
from starlette.requests import Request

from .contacts import ContactRepository


@dataclass(frozen=True, slots=True)
class Dependencies:
    """One request-visible dependency value owned by the host application."""

    repository: ContactRepository
    csrf: csrf.Guard


def from_request(request: Request) -> Dependencies:
    """Read and validate the dependency value stored by the host."""
    value = getattr(request.app.state, "dependencies", None)
    if not isinstance(value, Dependencies):
        raise RuntimeError("application dependency state is missing or invalid")
    return value
