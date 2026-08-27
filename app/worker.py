"""Single-host worker: python -m app.worker [--healthcheck]."""
import argparse
import asyncio
import contextlib
import logging
import signal
import uuid

from app.database import engine, init_db
from app.translator.dispatcher import process_next
from app.translator.jobs import (acquire_lease, lease_is_healthy, recover_interrupted_work,
                                 release_lease, renew_lease)

logger = logging.getLogger(__name__)


async def heartbeat(owner):
    while True:
        await asyncio.sleep(15)
        if not await renew_lease(owner):
            raise RuntimeError("Worker lost its singleton lease")


async def run_dispatcher(owner):
    while True:
        worked = await process_next(owner)
        if not worked:
            await asyncio.sleep(1)


async def run_worker():
    from app.crawler.auto_updater import auto_updater
    await init_db()
    owner = uuid.uuid4().hex
    if not await acquire_lease(owner):
        raise RuntimeError("Another translation worker is already running")
    tasks = []
    try:
        await recover_interrupted_work(owner)
        await auto_updater.start()
        tasks = [asyncio.create_task(heartbeat(owner)), asyncio.create_task(run_dispatcher(owner))]
        loop = asyncio.get_running_loop()
        current = asyncio.current_task()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, current.cancel)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await auto_updater.stop()
        await release_lease(owner)
        await engine.dispose()


async def healthcheck():
    try:
        return await lease_is_healthy()
    except Exception:
        return False
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Durable translation worker")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.healthcheck:
        raise SystemExit(0 if asyncio.run(healthcheck()) else 1)
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    main()
