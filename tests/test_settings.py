from pathlib import Path
import sys

import pytest

from kokoro_server import settings


def test_default_uses_user_config_and_explicit_path_uses_working_directory(tmp_path, monkeypatch):
    working = tmp_path / "other"
    working.mkdir()
    monkeypatch.chdir(working)
    config_dir = tmp_path / "user" / "kokoro-server"
    monkeypatch.setattr(settings, "user_config_dir", lambda *args, **kwargs: str(config_dir))
    settings.load_settings()
    assert (config_dir / "settings.ini").is_file()
    config_file = config_dir / "settings.ini"
    custom = settings.DEFAULT_CONFIG.replace("port = 47864", "port = 47865")
    config_file.write_text(custom, encoding="utf-8")
    assert settings.load_settings().port == 47865
    assert config_file.read_text(encoding="utf-8") == custom
    assert not (working / "settings.ini").exists()
    settings.load_settings(Path("custom.ini"))
    assert (working / "custom.ini").is_file()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="XDG paths apply on Linux")
def test_default_respects_xdg_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.load_settings()
    assert (tmp_path / "kokoro-server" / "settings.ini").is_file()


def test_creates_defaults_and_preserves_edits(tmp_path, monkeypatch):
    path = tmp_path / "settings.ini"
    config = settings.load_settings(path)
    assert config.port == 47864
    assert config.device == "auto"
    assert config.additional_origins == []
    assert config.detailed_logs is False
    assert config.max_input_kib == 1024
    assert config.output_file == ""
    assert config.language == "american"
    assert config.voice == "af_kore,af_bella"
    assert config.speed == 0.80
    custom = settings.DEFAULT_CONFIG.replace("device = auto", "device = cpu")
    path.write_text(custom, encoding="utf-8")
    monkeypatch.setattr(settings, "_settings", None)
    config = settings.get_settings(path)
    assert config.device == "cpu"
    assert path.read_text(encoding="utf-8") == custom
    path.write_text("invalid", encoding="utf-8")
    assert settings.get_settings().device == "cpu"
    assert path.read_text(encoding="utf-8") == "invalid"
    with pytest.raises(ValueError, match="Invalid configuration"):
        settings.load_settings(path)


def test_invalid_values_and_unwritable_location(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("port = 47864", "port = 0"), encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)
    with pytest.raises(ValueError):
        settings.load_settings(tmp_path / "missing-folder" / "settings.ini")


def test_default_config_directory_creation_failure(tmp_path, monkeypatch):
    blocking_file = tmp_path / "file"
    blocking_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "user_config_dir", lambda *args, **kwargs: str(blocking_file / "config"))
    with pytest.raises(ValueError, match="Invalid configuration"):
        settings.load_settings()


def test_optional_settings_and_existing_configs(tmp_path):
    path = tmp_path / "settings.ini"
    old = (settings.DEFAULT_CONFIG.replace("additional_origins =\n", "")
           .replace("detailed_logs = false\n", "").replace("max_input_kib = 1024\n", ""))
    path.write_text(old, encoding="utf-8")
    config = settings.load_settings(path)
    assert config.additional_origins == []
    assert config.detailed_logs is False
    assert config.max_input_kib == 1024
    path.write_text(old.replace("port = 47864", "port = 47864\nadditional_origins = http://localhost:3000, HTTPS://example.com:443")
                    .replace("device = auto", "device = auto\nmax_input_kib = 42"), encoding="utf-8")
    config = settings.load_settings(path)
    assert config.additional_origins == ["http://localhost:3000", "https://example.com"]
    assert config.max_input_kib == 42


@pytest.mark.parametrize("origin", ["*", "null", "http://example.com/", "http://user@example.com", "https://example.com:0", "http://example.com:", "http://bad host", "http://[::1]evil:47864"])
def test_invalid_origin_is_rejected(tmp_path, origin):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("additional_origins =", f"additional_origins = {origin}"), encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)


def test_nonpositive_text_limit_is_rejected(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("max_input_kib = 1024", "max_input_kib = 0"), encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)


def test_invalid_configured_language_is_rejected(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("language = american", "language = german"), encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)


@pytest.mark.parametrize("output", ["file.mp3", "bad\0.wav"])
def test_invalid_configured_output_is_rejected(tmp_path, output):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("output_file =", f"output_file = {output}"), encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)


@pytest.mark.parametrize("entry", ["output_file =", "output_file =   ", ""])
def test_optional_configured_output(tmp_path, entry):
    path = tmp_path / "settings.ini"
    path.write_text(settings.DEFAULT_CONFIG.replace("output_file =", entry), encoding="utf-8")
    assert settings.load_settings(path).output_file == ""
