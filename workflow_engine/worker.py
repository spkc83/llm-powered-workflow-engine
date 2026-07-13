"""Supervised action-delivery and reconciliation worker process."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal


async def run(poll_seconds: float) -> None:
    from main import (
        action_worker,
        core_store,
        policy_repository,
        provider_bundle,
        reconciliation_worker,
    )

    await core_store.initialize()
    await policy_repository.initialize()
    if provider_bundle is not None:
        await provider_bundle.initialize()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    while not stop.is_set():
        try:
            await action_worker.run_once()
            await reconciliation_worker.run_once()
        except Exception:
            logging.getLogger(__name__).exception("Worker iteration failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    asyncio.run(run(args.poll_seconds))


if __name__ == "__main__":
    main()
