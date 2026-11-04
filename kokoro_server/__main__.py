"""Run one server process so the model stays loaded between requests."""

import argparse
import json
import logging
from pathlib import Path

import uvicorn

from kokoro_server.settings import config_file_path, get_settings

def main():
    parser = argparse.ArgumentParser(description="Run the local Kokoro speech API.")
    parser.add_argument("--config", type=Path,
                        help="INI file path (default: settings.ini in the user config directory; created if missing)")
    args = parser.parse_args()
    config_path = config_file_path(args.config).resolve()
    try:
        settings = get_settings(args.config)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger(__name__).info(
        '{"event": "settings", "config_file": %s, "values": %s}',
        json.dumps(str(config_path)), settings.model_dump_json(exclude_none=True),
    )
    uvicorn.run("kokoro_server.api:app", host="127.0.0.1", port=settings.port,
                access_log=settings.detailed_logs)


if __name__ == "__main__":
    main()
