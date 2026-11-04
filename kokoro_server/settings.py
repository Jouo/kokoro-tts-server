"""Read and validate the selected configuration once at startup."""

from configparser import ConfigParser, Error as ConfigError
import ipaddress
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from platformdirs import user_config_dir
from pydantic import BaseModel, Field, field_validator


DEFAULT_CONFIG = """[server]
port = 47864
additional_origins =
detailed_logs = false

[engine]
device = auto
max_input_kib = 1024
output_file =

[speech]
language = american
voice = af_kore,af_bella
speed = 0.80
"""

Language = Literal["american", "british", "japanese", "mandarin", "spanish", "french", "hindi", "italian"]


def validate_output_file(value: str) -> str:
    value = value.strip()
    if not value or "\0" in value or Path(value).suffix.lower() != ".wav":
        raise ValueError("output_file must be a WAV path without null characters")
    return value


def normalize_origin(value: str) -> str:
    """Validate and canonicalize an HTTP origin without accepting URL paths."""
    try:
        url = urlsplit(value)
        host = url.hostname
        port = url.port
        if (url.scheme not in {"http", "https"} or not host or url.username is not None
                or url.password is not None or url.path or url.query or url.fragment
                or url.netloc.endswith(":")
                or any(c in value for c in "\\ \t\r\n?#%")):
            raise ValueError("not an HTTP origin")
        if ":" in host:
            if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", url.netloc):
                raise ValueError("invalid IPv6 authority")
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        elif len(host) > 253 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError("invalid origin hostname")
        if port == 0:
            raise ValueError("invalid origin port")
        default_port = 80 if url.scheme == "http" else 443
        return f"{url.scheme}://{host}" + (f":{port}" if port and port != default_port else "")
    except ValueError as exc:
        raise ValueError(f"Invalid origin: {value!r}") from exc


class Settings(BaseModel):
    port: int = Field(ge=1, le=65535)
    additional_origins: list[str] = Field(default_factory=list)
    detailed_logs: bool = False
    device: Literal["auto", "cuda", "cpu"]
    max_input_kib: int = Field(default=1024, gt=0)
    output_file: str = ""
    language: Language
    voice: str = Field(min_length=1)
    speed: float = Field(ge=0.1, le=2.0)

    @property
    def input_limit_bytes(self) -> int:
        return self.max_input_kib * 1024

    @field_validator("output_file")
    @classmethod
    def validate_default_output(cls, value: str) -> str:
        return validate_output_file(value) if value.strip() else ""

    @field_validator("additional_origins", mode="before")
    @classmethod
    def parse_origins(cls, value):
        values = value.split(",") if isinstance(value, str) else value
        return [normalize_origin(origin.strip()) for origin in values if origin.strip()]


def config_file_path(path: Path | None = None) -> Path:
    """Return the selected configuration file path."""
    return (Path(path).expanduser() if path is not None
            else Path(user_config_dir("kokoro-server", appauthor=False)) / "settings.ini")


def load_settings(path: Path | None = None) -> Settings:
    config = ConfigParser(interpolation=None)
    resource = config_file_path(path)
    try:
        if path is None:
            resource.parent.mkdir(parents=True, exist_ok=True)
        try:
            with resource.open("x", encoding="utf-8") as handle:
                handle.write(DEFAULT_CONFIG)
        except FileExistsError:
            pass
        config.read_string(resource.read_text(encoding="utf-8"))
        settings = Settings(
            **dict(config["server"]), **dict(config["engine"]), **dict(config["speech"]),
        )
        return settings
    except (OSError, ValueError, KeyError, ConfigError) as exc:
        raise ValueError(f"Invalid configuration in {resource}: {exc}") from exc


_settings: Settings | None = None


def get_settings(path: Path | None = None) -> Settings:
    """Select the configuration on first use; reuse it for the process lifetime."""
    global _settings
    if _settings is None:
        _settings = load_settings(path)
    return _settings
