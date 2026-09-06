"""Retired DGER Prototype R0 direct-execution surface.

Generation 3 production uses :mod:`dger.relay_v1`. Generation 4 permanently removes the
older Prototype R0 library route because it could reconstruct and directly start GEP with
weaker authorization than the Gen4 AHC/GEP/MOH chain. This module intentionally exposes no
execution-capable compatibility shim.
"""
from __future__ import annotations

from typing import NoReturn

RETIREMENT_CODE = "DGER_PROTOTYPE_R0_RETIRED"


class RetiredPrototypeSurface(RuntimeError):
    pass


def _retired(*_args: object, **_kwargs: object) -> NoReturn:
    raise RetiredPrototypeSurface(RETIREMENT_CODE)


class Relay:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        _retired()


def start_gep(*_args: object, **_kwargs: object) -> NoReturn:
    _retired()


def reconstruct_gep(*_args: object, **_kwargs: object) -> NoReturn:
    _retired()


def provision_gep(*_args: object, **_kwargs: object) -> NoReturn:
    _retired()
