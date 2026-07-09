import logging
from gevent import monkey
monkey.patch_all()

import argparse
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
    return parser.parse_args()


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

    server_cfg:dict = config.get_app_config()["server"]

    log.info(f"Starting server on {server_cfg["bind_addr"]}:{server_cfg["port"]}")

    socketio.run(app, host=server_cfg["bind_addr"], port=server_cfg["port"])

if __name__ == "__main__":
    main()
