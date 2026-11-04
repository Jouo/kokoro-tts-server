import json
import logging
import sys
from unittest.mock import Mock

import pytest

from kokoro_server import __main__ as cli
from kokoro_server import settings


@pytest.mark.parametrize("custom_config", [False, True])
def test_startup_selects_config_and_logs_settings(tmp_path, monkeypatch, caplog, custom_config):
    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(settings, "user_config_dir", lambda *args, **kwargs: str(tmp_path / "config"))
    args = []
    port = 47864
    if custom_config:
        path = tmp_path / "custom.ini"
        path.write_text(settings.DEFAULT_CONFIG.replace("port = 47864", "host = 0.0.0.0\nport = 47865"), encoding="utf-8")
        args = ["--config", str(path)]
        port = 47865
    run = Mock()
    monkeypatch.setattr(sys, "argv", ["kokoro-server", *args])
    monkeypatch.setattr(cli.uvicorn, "run", run)
    with caplog.at_level(logging.INFO, logger="kokoro_server.__main__"):
        cli.main()
    assert run.call_count == 1
    assert run.call_args.kwargs == {"host": "127.0.0.1", "port": port, "access_log": False}
    log = json.loads(caplog.records[-1].getMessage())
    expected_config = path if custom_config else tmp_path / "config" / "settings.ini"
    assert log["config_file"] == str(expected_config.resolve())
    assert log["values"]["device"] == "auto"


def test_detailed_logging_enables_uvicorn_access_log(tmp_path, monkeypatch):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("detailed_logs = false", "detailed_logs = true"), encoding="utf-8")
    run = Mock()
    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(sys, "argv", ["kokoro-server", "--config", str(path)])
    monkeypatch.setattr(cli.uvicorn, "run", run)
    cli.main()
    assert run.call_args.kwargs["access_log"] is True


def test_invalid_config_does_not_start_server(tmp_path, monkeypatch, capsys):
    run = Mock()
    path = tmp_path / "invalid.ini"
    path.write_text("not an INI file", encoding="utf-8")
    monkeypatch.setattr(settings, "_settings", None)
    monkeypatch.setattr(sys, "argv", ["kokoro-server", "--config", str(path)])
    monkeypatch.setattr(cli.uvicorn, "run", run)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "Invalid configuration" in capsys.readouterr().err
    run.assert_not_called()
