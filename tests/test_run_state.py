"""
Unit tests for run_state.py — Run state machine, RunStore, and RunQueue.
"""

import asyncio
import pytest

from run_state import (
    Run,
    RunStatus,
    RunStore,
    RunQueue,
    RunNotFoundError,
    InvalidTransitionError,
)


# ---------------------------------------------------------------------------
# Run state-machine transition tests
# ---------------------------------------------------------------------------


class TestRunTransitions:
    def _pending_run(self) -> Run:
        import uuid
        return Run(run_id=str(uuid.uuid4()), question="Test question", config={})

    def test_initial_status_is_pending(self):
        run = self._pending_run()
        assert run.status is RunStatus.PENDING

    def test_start_transitions_to_running(self):
        run = self._pending_run()
        run.start()
        assert run.status is RunStatus.RUNNING
        assert run.started_at is not None

    def test_complete_transitions_to_completed(self):
        run = self._pending_run()
        run.start()
        run.complete({"answer": "42"})
        assert run.status is RunStatus.COMPLETED
        assert run.result == {"answer": "42"}
        assert run.finished_at is not None

    def test_fail_transitions_to_failed(self):
        run = self._pending_run()
        run.start()
        run.fail("something went wrong")
        assert run.status is RunStatus.FAILED
        assert run.error == "something went wrong"
        assert run.finished_at is not None

    def test_cannot_start_from_running(self):
        run = self._pending_run()
        run.start()
        with pytest.raises(InvalidTransitionError):
            run.start()

    def test_cannot_start_from_completed(self):
        run = self._pending_run()
        run.start()
        run.complete({})
        with pytest.raises(InvalidTransitionError):
            run.start()

    def test_cannot_complete_from_pending(self):
        run = self._pending_run()
        with pytest.raises(InvalidTransitionError):
            run.complete({})

    def test_cannot_fail_from_pending(self):
        run = self._pending_run()
        with pytest.raises(InvalidTransitionError):
            run.fail("error")

    def test_cannot_complete_from_failed(self):
        run = self._pending_run()
        run.start()
        run.fail("err")
        with pytest.raises(InvalidTransitionError):
            run.complete({})

    def test_to_dict_pending(self):
        run = self._pending_run()
        d = run.to_dict()
        assert d["status"] == "pending"
        assert d["result"] is None
        assert d["error"] is None
        assert d["started_at"] is None
        assert d["finished_at"] is None

    def test_to_dict_completed(self):
        run = self._pending_run()
        run.start()
        run.complete({"resolution": "Yes."})
        d = run.to_dict()
        assert d["status"] == "completed"
        assert d["result"] == {"resolution": "Yes."}
        assert d["error"] is None

    def test_to_dict_failed(self):
        run = self._pending_run()
        run.start()
        run.fail("timeout")
        d = run.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "timeout"
        assert d["result"] is None


# ---------------------------------------------------------------------------
# RunStore tests
# ---------------------------------------------------------------------------


class TestRunStore:
    @pytest.mark.asyncio
    async def test_create_returns_pending_run(self):
        store = RunStore()
        run = await store.create("What is the meaning of life?")
        assert run.status is RunStatus.PENDING
        assert run.question == "What is the meaning of life?"
        assert run.run_id

    @pytest.mark.asyncio
    async def test_get_returns_run(self):
        store = RunStore()
        run = await store.create("Q?")
        fetched = await store.get(run.run_id)
        assert fetched.run_id == run.run_id

    @pytest.mark.asyncio
    async def test_get_unknown_raises(self):
        store = RunStore()
        with pytest.raises(RunNotFoundError):
            await store.get("no-such-id")

    @pytest.mark.asyncio
    async def test_list_runs_empty(self):
        store = RunStore()
        runs = await store.list_runs()
        assert runs == []

    @pytest.mark.asyncio
    async def test_list_runs_returns_all(self):
        store = RunStore()
        await store.create("Q1")
        await store.create("Q2")
        runs = await store.list_runs()
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_list_runs_filtered_by_owner(self):
        store = RunStore()
        await store.create("Q1", owner_id="alice")
        await store.create("Q2", owner_id="bob")
        alice_runs = await store.list_runs(owner_id="alice")
        assert len(alice_runs) == 1
        assert alice_runs[0].owner_id == "alice"

    @pytest.mark.asyncio
    async def test_update_status_to_running(self):
        store = RunStore()
        run = await store.create("Q?")
        updated = await store.update_status(run.run_id, RunStatus.RUNNING)
        assert updated.status is RunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self):
        store = RunStore()
        run = await store.create("Q?")
        await store.update_status(run.run_id, RunStatus.RUNNING)
        result = {"answer": "42"}
        updated = await store.update_status(run.run_id, RunStatus.COMPLETED, result=result)
        assert updated.status is RunStatus.COMPLETED
        assert updated.result == result

    @pytest.mark.asyncio
    async def test_update_status_to_failed(self):
        store = RunStore()
        run = await store.create("Q?")
        await store.update_status(run.run_id, RunStatus.RUNNING)
        updated = await store.update_status(run.run_id, RunStatus.FAILED, error="boom")
        assert updated.status is RunStatus.FAILED
        assert updated.error == "boom"

    @pytest.mark.asyncio
    async def test_update_completed_requires_result(self):
        store = RunStore()
        run = await store.create("Q?")
        await store.update_status(run.run_id, RunStatus.RUNNING)
        with pytest.raises(ValueError, match="result must be provided"):
            await store.update_status(run.run_id, RunStatus.COMPLETED)

    @pytest.mark.asyncio
    async def test_update_failed_requires_error(self):
        store = RunStore()
        run = await store.create("Q?")
        await store.update_status(run.run_id, RunStatus.RUNNING)
        with pytest.raises(ValueError, match="error must be provided"):
            await store.update_status(run.run_id, RunStatus.FAILED)

    @pytest.mark.asyncio
    async def test_update_invalid_status_raises(self):
        store = RunStore()
        run = await store.create("Q?")
        with pytest.raises(ValueError, match="Unsupported target status"):
            await store.update_status(run.run_id, RunStatus.PENDING)

    @pytest.mark.asyncio
    async def test_update_unknown_run_raises(self):
        store = RunStore()
        with pytest.raises(RunNotFoundError):
            await store.update_status("no-such-id", RunStatus.RUNNING)

    @pytest.mark.asyncio
    async def test_list_runs_newest_first(self):
        store = RunStore()
        r1 = await store.create("Q1")
        await asyncio.sleep(0.01)
        r2 = await store.create("Q2")
        runs = await store.list_runs()
        assert runs[0].run_id == r2.run_id
        assert runs[1].run_id == r1.run_id


# ---------------------------------------------------------------------------
# RunQueue tests
# ---------------------------------------------------------------------------


class TestRunQueue:
    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self):
        q = RunQueue()
        await q.enqueue("run-1")
        run_id = await q.dequeue()
        assert run_id == "run-1"

    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        q = RunQueue()
        for i in range(5):
            await q.enqueue(f"run-{i}")
        results = []
        for _ in range(5):
            results.append(await q.dequeue())
        assert results == [f"run-{i}" for i in range(5)]

    @pytest.mark.asyncio
    async def test_size_reflects_queue_depth(self):
        q = RunQueue()
        assert q.size == 0
        await q.enqueue("a")
        await q.enqueue("b")
        assert q.size == 2
        await q.dequeue()
        assert q.size == 1
