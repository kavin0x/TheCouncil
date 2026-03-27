"""
Run state machine for TheCouncil API.

Models the lifecycle of a council debate run:

  PENDING  → queued, waiting to be picked up by a worker
  RUNNING  → worker has claimed the run and is executing it
  COMPLETED → run finished successfully; result is available
  FAILED   → run finished with an unrecoverable error

Transitions:
  PENDING  → RUNNING    (worker claims the run)
  RUNNING  → COMPLETED  (worker reports success)
  RUNNING  → FAILED     (worker reports failure)

An in-process queue is provided for local / dev mode.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Run record
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """A single council-debate run record."""

    run_id: str
    question: str
    config: dict[str, Any]                     # forwarded to DebateSession
    status: RunStatus = RunStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None       # populated on COMPLETED
    error: str | None = None                   # populated on FAILED
    owner_id: str = ""                         # API token / user identifier

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Transition PENDING → RUNNING."""
        if self.status is not RunStatus.PENDING:
            raise InvalidTransitionError(
                f"Cannot start run {self.run_id}: current status is {self.status.value!r}"
            )
        self.status = RunStatus.RUNNING
        self.started_at = time.time()

    def complete(self, result: dict[str, Any]) -> None:
        """Transition RUNNING → COMPLETED."""
        if self.status is not RunStatus.RUNNING:
            raise InvalidTransitionError(
                f"Cannot complete run {self.run_id}: current status is {self.status.value!r}"
            )
        self.status = RunStatus.COMPLETED
        self.finished_at = time.time()
        self.result = result

    def fail(self, error: str) -> None:
        """Transition RUNNING → FAILED."""
        if self.status is not RunStatus.RUNNING:
            raise InvalidTransitionError(
                f"Cannot fail run {self.run_id}: current status is {self.status.value!r}"
            )
        self.status = RunStatus.FAILED
        self.finished_at = time.time()
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this run."""
        return {
            "run_id": self.run_id,
            "question": self.question,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "owner_id": self.owner_id,
            "result": self.result,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RunNotFoundError(KeyError):
    """Raised when a run_id is not found in the store."""


class InvalidTransitionError(RuntimeError):
    """Raised when a state transition is illegal."""


# ---------------------------------------------------------------------------
# In-process run store + queue (suitable for dev / single-process deployments)
# ---------------------------------------------------------------------------


class RunStore:
    """Thread-safe in-memory store for Run objects."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        question: str,
        config: dict[str, Any] | None = None,
        owner_id: str = "",
    ) -> Run:
        """Create a new Run in PENDING status and add it to the store."""
        run = Run(
            run_id=str(uuid.uuid4()),
            question=question,
            config=config or {},
            owner_id=owner_id,
        )
        async with self._lock:
            self._runs[run.run_id] = run
        return run

    async def get(self, run_id: str) -> Run:
        """Return the Run for the given run_id, raising RunNotFoundError if absent."""
        async with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise RunNotFoundError(f"Run not found: {run_id!r}")
        return run

    async def list_runs(self, owner_id: str | None = None) -> list[Run]:
        """Return all runs, optionally filtered by owner_id."""
        async with self._lock:
            runs = list(self._runs.values())
        if owner_id is not None:
            runs = [r for r in runs if r.owner_id == owner_id]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    async def update_status(
        self,
        run_id: str,
        new_status: RunStatus,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Run:
        """Apply a status transition to the named run.

        Delegates to the appropriate Run transition method so that the
        state-machine invariants are always enforced.
        """
        run = await self.get(run_id)
        async with self._lock:
            if new_status is RunStatus.RUNNING:
                run.start()
            elif new_status is RunStatus.COMPLETED:
                if result is None:
                    raise ValueError("result must be provided when completing a run")
                run.complete(result)
            elif new_status is RunStatus.FAILED:
                if error is None:
                    raise ValueError("error must be provided when failing a run")
                run.fail(error)
            else:
                raise ValueError(f"Unsupported target status: {new_status!r}")
        return run


# ---------------------------------------------------------------------------
# In-process job queue
# ---------------------------------------------------------------------------


class RunQueue:
    """Async FIFO queue of run_id strings for local / dev workers."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()

    async def enqueue(self, run_id: str) -> None:
        """Push a run_id onto the queue."""
        await self._q.put(run_id)

    async def dequeue(self) -> str:
        """Block until a run_id is available and return it."""
        return await self._q.get()

    def task_done(self) -> None:
        """Signal that the previously dequeued run has been processed."""
        self._q.task_done()

    @property
    def size(self) -> int:
        """Current number of items waiting in the queue."""
        return self._q.qsize()


# ---------------------------------------------------------------------------
# Module-level singletons for use by the API layer
# ---------------------------------------------------------------------------

run_store = RunStore()
run_queue = RunQueue()
