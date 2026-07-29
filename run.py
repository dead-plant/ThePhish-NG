from gevent import monkey
monkey.patch_all()

import truststore
truststore.inject_into_ssl()

import argparse
import logging
import multiprocessing
import signal
import sys
from pathlib import Path

from app import config

log = logging.getLogger("thephish")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the application.")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "config",
        help="Path to the configuration directory (default: ./config).",
    )
    parser.add_argument(
        "--bind-addr",
        default="127.0.0.1",
        help="Address the web server binds to (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port the web server binds to (default: 8080).",
    )
    return parser.parse_args()


def run_celery_worker(config_dir: Path) -> None:
    """Initialize the application once, then run its Celery worker."""
    config.init(config_dir)

    from app import create_app

    flask_app = create_app()
    celery_app = flask_app.extensions["celery"]
    celery_app.worker_main(["worker", "--pool=gevent", "--loglevel=INFO"])


def main() -> None:
    args = parse_args()

    try:
        config.init(args.config_dir)
    except config.ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    from app import create_app
    from app.extensions import socketio

    app = create_app()

    # A fresh process keeps the worker isolated from Flask and its connections.
    worker_process = multiprocessing.get_context("spawn").Process(
        target=run_celery_worker,
        args=(args.config_dir.resolve(),),
        name="thephish-celery-worker",
    )

    def handle_sigterm(_signum, _frame) -> None:
        raise KeyboardInterrupt

    previous_sigterm_handler = signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        worker_process.start()
        log.info("Starting server on %s:%s", args.bind_addr, args.port)
        socketio.run(
            app,
            host=args.bind_addr,
            port=args.port,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if worker_process.pid is not None:
                if worker_process.is_alive():
                    log.info("Stopping Celery worker")
                    worker_process.terminate()

                worker_process.join()
                worker_process.close()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)


if __name__ == "__main__":
    main()
