"""Run the translation worker inside the web process.

Render's free plan runs a single service, so ``python -m app.worker`` never
starts there: queued chapters stay queued and the source sync never fires.
This supervisor drives the same dispatcher from the web process, guarded by
the same database lease — if a dedicated worker already holds it (docker
compose, Oracle), the embedded loop stays idle instead of double-dispatching.
"""
import asyncio
import contextlib
import logging
import uuid

from app.translator.jobs import (acquire_lease, recover_interrupted_work,
                                 release_lease, renew_lease)

logger = logging.getLogger(__name__)

RENEW_INTERVAL = 15.0
IDLE_SLEEP = 2.0
CONTENDED_SLEEP = 30.0
ERROR_SLEEP = 5.0


class EmbeddedWorker:
    def __init__(self):
        self.owner = uuid.uuid4().hex
        self.task = None
        self.holds_lease = False

    async def start(self):
        self.task = asyncio.create_task(self._supervise(), name="embedded-worker")

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self._surrender()

    async def _surrender(self):
        from app.crawler.auto_updater import auto_updater
        if not self.holds_lease:
            return
        self.holds_lease = False
        with contextlib.suppress(Exception):
            await auto_updater.stop()
        with contextlib.suppress(Exception):
            await release_lease(self.owner)

    async def _claim(self):
        from app.crawler.auto_updater import auto_updater
        if not await acquire_lease(self.owner):
            return False
        self.holds_lease = True
        await recover_interrupted_work(self.owner)
        await auto_updater.start()
        logger.info("Embedded worker holds the queue lease (owner=%s)", self.owner[:8])
        return True

    async def _supervise(self):
        from app.translator.dispatcher import process_next
        renewed_at = 0.0
        while True:
            try:
                loop_time = asyncio.get_running_loop().time()
                if not self.holds_lease:
                    if not await self._claim():
                        # A dedicated worker owns the queue; nothing to do here.
                        await asyncio.sleep(CONTENDED_SLEEP)
                        continue
                    renewed_at = loop_time
                elif loop_time - renewed_at >= RENEW_INTERVAL:
                    if not await renew_lease(self.owner):
                        logger.warning("Embedded worker lost its lease; standing down")
                        await self._surrender()
                        continue
                    renewed_at = loop_time
                if not await process_next(self.owner):
                    await asyncio.sleep(IDLE_SLEEP)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Embedded worker iteration failed")
                await asyncio.sleep(ERROR_SLEEP)


async def start_embedded_worker() -> EmbeddedWorker:
    worker = EmbeddedWorker()
    await worker.start()
    return worker
