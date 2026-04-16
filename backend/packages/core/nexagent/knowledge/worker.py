"""Production knowledge worker.

Runs queued parse/index/graph/eval jobs outside the FastAPI request process.
Redis is the primary queue; when Redis is unavailable the worker polls Postgres
for queued jobs so local development can still make progress with a degraded
diagnostic state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from sqlalchemy import select

from nexagent.db.models import KnowledgeJobRecord
from nexagent.db.session import AsyncSessionLocal
from nexagent.knowledge.production_service import PRODUCTION_JOB_QUEUE, ProductionKnowledgeService

logger = logging.getLogger("nexagent.knowledge.worker")


class KnowledgeWorker:
    def __init__(self) -> None:
        self.service = ProductionKnowledgeService()
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("Knowledge worker started")
        while not self._stopping.is_set():
            job_id = await self._next_redis_job()
            if not job_id:
                job_id = await self._next_db_job()
            if not job_id:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=2)
                except TimeoutError:
                    pass
                continue
            try:
                logger.info("Running knowledge job %s", job_id)
                await self.service.run_job(job_id)
            except Exception:
                logger.exception("Knowledge job failed outside service handler: %s", job_id)

    async def _next_redis_job(self) -> str:
        try:
            import redis.asyncio as redis

            client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            item = await client.blpop(PRODUCTION_JOB_QUEUE, timeout=1)
            await client.aclose()
            if not item:
                return ""
            return str(item[1])
        except Exception:
            return ""

    async def _next_db_job(self) -> str:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(KnowledgeJobRecord)
                .where(KnowledgeJobRecord.status == "queued")
                .order_by(KnowledgeJobRecord.created_at.asc())
                .limit(1)
            )
            job = result.scalars().first()
            return job.id if job else ""


async def amain() -> None:
    logging.basicConfig(level=os.environ.get("NEXAGENT_LOG_LEVEL", "INFO"))
    worker = KnowledgeWorker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop)
        except NotImplementedError:
            pass
    await worker.run()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
