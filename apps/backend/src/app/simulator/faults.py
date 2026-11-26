"""Faults, kept in memory in the order they were set (docs/simulator.md, "Faults")."""

import itertools
import json
import os
from typing import Literal

from pydantic import BaseModel, Field

FaultType = Literal[
    "5xx",
    "429",
    "reject",
    "never_answer",
    "delay",
    "malformed_json",
    "schema_violation",
    "truncated",
    "harmful_proposal",
]


class FaultIn(BaseModel):
    type: FaultType
    # Every model when empty, else just this one ("fake" or "fake-judge").
    model: str | None = None
    # For 429: the Retry-After, in seconds.
    retry_after: float | None = Field(default=None, ge=0)
    # For delay: how long the answer waits, in seconds.
    seconds: float | None = Field(default=None, ge=0)
    # For 5xx and reject: the status to answer with.
    status: int | None = Field(default=None, ge=400, le=599)


class Fault(FaultIn):
    id: int


class FaultStore:
    def __init__(self) -> None:
        self._faults: list[Fault] = []
        self._ids = itertools.count(1)

    def add(self, fault: FaultIn) -> Fault:
        stored = Fault(id=next(self._ids), **fault.model_dump())
        self._faults.append(stored)
        return stored

    def all(self) -> list[Fault]:
        return list(self._faults)

    def remove(self, fault_id: int) -> bool:
        before = len(self._faults)
        self._faults = [f for f in self._faults if f.id != fault_id]
        return len(self._faults) != before

    def clear(self) -> None:
        self._faults = []

    def matching(self, model: str) -> list[Fault]:
        return [f for f in self._faults if f.model in (None, model)]

    def load_env(self, variable: str = "SIM_FAULTS") -> None:
        """Faults from the startup config: a JSON list of faults."""
        raw = os.environ.get(variable)
        if raw:
            for item in json.loads(raw):
                self.add(FaultIn.model_validate(item))
