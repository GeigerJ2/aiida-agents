"""Workaround for missing websockets-sansio in uvicorn."""

from __future__ import annotations
import uvicorn.config
from typing import Any, MutableMapping, cast


def register() -> None:
    """Register the missing websockets-sansio protocol."""
    cast(MutableMapping[str, Any], uvicorn.config.WS_PROTOCOLS).setdefault(
        "websockets-sansio",
        "uvicorn.protocols.websockets.wsproto_impl:WSProtocol",
    )
