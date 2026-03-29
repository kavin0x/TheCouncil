"""
Celery application for TheCouncil background workers.

Celery configuration is driven entirely from environment variables:
  CELERY_BROKER_URL    — Redis broker URL (e.g. redis://redis:6379/1)
  CELERY_RESULT_BACKEND — Redis result backend URL

Usage:
  celery -A council.worker.celery_app worker --loglevel=info -Q council_runs
"""

from __future__ import annotations

import os

from celery import Celery  # type: ignore[import]

BROKER_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/1"))
RESULT_BACKEND = os.getenv(
    "CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://localhost:6379/1")
)

celery_app = Celery(
    "council_worker",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["council.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,                   # ack after task completes, not before
    task_reject_on_worker_lost=True,       # requeue if worker dies mid-task
    worker_prefetch_multiplier=1,          # one task at a time per worker
    task_default_queue="council_runs",
    task_queues={
        "council_runs": {
            "exchange": "council_runs",
            "routing_key": "council_runs",
        }
    },
    task_routes={
        "council.worker.tasks.execute_council_run": {"queue": "council_runs"},
    },
    result_expires=86400,                  # keep results for 24 h
    task_soft_time_limit=600,              # 10 min soft limit
    task_time_limit=720,                   # 12 min hard limit
)
