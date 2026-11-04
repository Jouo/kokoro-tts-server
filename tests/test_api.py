import asyncio
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from configparser import ConfigParser
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from kokoro_server import settings
from kokoro_server.api import create_app
from kokoro_server.speech import SpeechService


@pytest.fixture
def api(tmp_path, monkeypatch, request):
    config_path = tmp_path / "settings.ini"
    config = settings.load_settings(config_path)
    overrides = getattr(request, "param", {})
    if overrides:
        ini = ConfigParser()
        ini.read(config_path, encoding="utf-8")
        for name, value in overrides.items():
            if name in {"host", "additional_origins", "detailed_logs"}:
                section = "server"
            elif name in {"device", "max_input_kib", "output_file"}:
                section = "engine"
            else:
                section = "speech"
            ini[section][name] = str(value)
        with config_path.open("w", encoding="utf-8") as file:
            ini.write(file)
        config = settings.load_settings(config_path)
    monkeypatch.setattr(settings, "_settings", config)
    audio = Mock()
    audio.detach.return_value.cpu.return_value.numpy.return_value = np.zeros(2400)
    pipeline = Mock(return_value=[("text", "phonemes", audio)])
    monkeypatch.setitem(sys.modules, "torch", Mock(cuda=Mock(is_available=Mock(return_value=False))))
    monkeypatch.setitem(sys.modules, "kokoro", SimpleNamespace(KPipeline=Mock(return_value=pipeline)))
    service = SpeechService()
    factory = Mock(return_value=service)
    with TestClient(create_app(factory), base_url="http://127.0.0.1:47864") as client:
        yield SimpleNamespace(client=client, pipeline=pipeline, factory=factory, output=tmp_path / "sample.wav", config=config)


def post(api, **updates):
    body = {"text": "Hello", "output_file": str(api.output)}
    body.update(updates)
    return api.client.post("/speech", json=body)


def post_file(api, content, **fields):
    data = {"output_file": str(api.output)}
    data.update(fields)
    return api.client.post(
        "/speech/file", data=data,
        files={"input_file": ("message.txt", content, "text/plain")},
    )


def test_health_and_text_write_wav_reusing_service(api):
    assert api.client.get("/health").json() == {"status": "ok"}
    api.pipeline.assert_not_called()
    for options in ({}, {"language": "american"}):
        response = post(api, **options)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "output_file": str(api.output), "sample_rate": 24000, "duration_seconds": 0.1,
        }
    api.factory.assert_called_once_with()
    assert api.pipeline.call_count == 2
    api.pipeline.assert_called_with("Hello", voice="af_kore,af_bella", speed=0.80)
    assert sf.info(api.output).frames == 2400


def test_utf8_file_upload(api):
    response = post_file(api, "¡Hola!".encode("utf-8"))
    assert response.status_code == 200, response.text
    api.pipeline.assert_called_once_with("¡Hola!", voice="af_kore,af_bella", speed=0.80)
    response = post_file(api, b"Hello again", voice="af_bella", speed="1.25")
    assert response.status_code == 200, response.text
    api.pipeline.assert_called_with("Hello again", voice="af_bella", speed=1.25)


@pytest.mark.parametrize("updates", [
    {"text": None}, {"input_path": "a.txt"}, {"text": " "},
    {"output_file": "a.mp3"}, {"output_file": None}, {"output_path": "a.wav"},
    {"language": "german"}, {"language": "english"}, {"speed": 3},
    {"speed": None}, {"speed": "1"}, {"voice": " "},
])
def test_input_contract_and_options(api, updates):
    assert post(api, **updates).status_code == 422
    api.pipeline.assert_not_called()


@pytest.mark.parametrize("api", [{"output_file": "configured.wav"}], indirect=True)
def test_configured_output_default_and_overrides(api, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    default = tmp_path / "configured.wav"
    response = api.client.post("/speech", json={"text": "Hello"})
    assert response.status_code == 200
    assert response.json()["output_file"] == str(default)
    assert sf.info(default).frames == 2400
    response = api.client.post("/speech/file", files={"input_file": ("input.txt", b"Hello")})
    assert response.status_code == 200
    assert response.json()["output_file"] == str(default)
    assert post(api).json()["output_file"] == str(api.output)
    assert post_file(api, b"Hello").json()["output_file"] == str(api.output)
    assert post_file(api, b"Hello", output_file="bad.mp3").status_code == 422


def test_empty_default_requires_output_for_both_endpoints(api):
    response = api.client.post("/speech", json={"text": "Hello"})
    assert response.status_code == 422
    response = api.client.post("/speech/file", files={"input_file": ("input.txt", b"Hello")})
    assert response.status_code == 422
    api.pipeline.assert_not_called()
    assert post(api).status_code == 200
    assert post_file(api, b"Hello").status_code == 200


@pytest.mark.parametrize("api", [{"output_file": "missing/output.wav"}], indirect=True)
def test_default_output_missing_parent(api, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert api.client.post("/speech", json={"text": "Hello"}).status_code == 400
    assert api.client.post("/speech/file", files={"input_file": ("input.txt", b"Hello")}).status_code == 400
    api.pipeline.assert_not_called()


@pytest.mark.parametrize("language, code", [
    ("british", "b"), ("japanese", "j"), ("mandarin", "z"), ("spanish", "e"),
    ("french", "f"), ("hindi", "h"), ("italian", "i"),
])
def test_language_selection_and_overrides(api, monkeypatch, language, code):
    pipeline = Mock(return_value=api.pipeline.return_value)
    factory = Mock(return_value=pipeline)
    monkeypatch.setitem(sys.modules, "kokoro", Mock(KPipeline=factory))
    assert post(api, language=language).status_code == 200
    pipeline.assert_called_with("Hello", voice="af_kore,af_bella", speed=0.80)
    assert post_file(api, b"Hello", language=language, voice="custom", speed="1.5").status_code == 200
    pipeline.assert_called_with("Hello", voice="custom", speed=1.5)
    factory.assert_called_once_with(lang_code=code, model=api.pipeline.model)
    assert post(api, voice="af_bella", speed=1).status_code == 200
    api.pipeline.assert_called_with("Hello", voice="af_bella", speed=1)


@pytest.mark.parametrize("api", [{"language": "british", "voice": "bf_emma", "speed": "1.1"}], indirect=True)
def test_configured_speech_defaults_apply_to_both_endpoints(api, monkeypatch):
    pipeline = Mock(return_value=api.pipeline.return_value)
    factory = Mock(return_value=pipeline)
    monkeypatch.setitem(sys.modules, "kokoro", Mock(KPipeline=factory))
    assert post(api).status_code == 200
    assert post_file(api, b"Hello").status_code == 200
    assert pipeline.call_count == 2
    pipeline.assert_called_with("Hello", voice="bf_emma", speed=1.1)
    factory.assert_called_once_with(lang_code="b", model=api.pipeline.model)


def test_file_rejects_invalid_language(api):
    assert post_file(api, b"Hello", language="german").status_code == 422
    api.pipeline.assert_not_called()


@pytest.mark.parametrize("content", [b"   ", b"\xff"], ids=["empty", "invalid-utf8"])
def test_bad_file_uploads(api, content):
    response = post_file(api, content)
    assert response.status_code == 400, response.text
    api.pipeline.assert_not_called()


def test_missing_file_upload_is_rejected(api):
    response = api.client.post("/speech/file", data={"output_file": str(api.output)})
    assert response.status_code == 422
    api.pipeline.assert_not_called()


def test_oversized_file_upload_is_rejected(api):
    response = post_file(api, b"a" * (api.config.input_limit_bytes + 1))
    assert response.status_code == 413
    api.pipeline.assert_not_called()


def test_browser_origin_and_host_policy(api):
    origin = "http://127.0.0.1:47864"
    body = {"text": "Hello", "output_file": str(api.output)}
    assert api.client.get("/docs", headers={"Origin": origin}).status_code == 200
    assert api.client.post("/speech", json=body, headers={"Origin": origin}).status_code == 200
    for host in ("localhost:47864", "[::1]:47864"):
        assert api.client.get("/health", headers={"Host": host}).status_code == 200
    for headers in (
        {"Origin": "https://untrusted.example"},
        {"Origin": "null"},
        {"Host": "evil.example:47864", "Origin": "http://evil.example:47864"},
        {"Host": "127.0.0.1:1234"},
    ):
        assert api.client.post("/speech/file", data={"output_file": str(api.output)},
                               files={"input_file": ("x.txt", b"hello")}, headers=headers).status_code == 403
    assert api.pipeline.call_count == 1


@pytest.mark.parametrize("api", [{"host": "old-host.example"}], indirect=True)
def test_legacy_host_setting_does_not_allow_custom_host(api):
    assert api.client.get("/health").status_code == 200
    assert api.client.get("/health", headers={"Host": "old-host.example:47864"}).status_code == 403


@pytest.mark.parametrize("api", [{"additional_origins": "http://localhost:3000", "max_input_kib": 1}], indirect=True)
def test_configured_origin_supports_cors(api):
    headers = {"Origin": "http://localhost:3000"}
    preflight = api.client.options("/speech", headers={**headers, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == headers["Origin"]
    response = api.client.post("/speech", headers=headers, json={"text": "H", "output_file": str(api.output)})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    too_large = api.client.post("/speech", headers=headers, content=b"x" * (6 * 1024 + 65537))
    assert too_large.status_code == 413
    assert too_large.headers["access-control-allow-origin"] == headers["Origin"]


@pytest.mark.parametrize("api", [{"max_input_kib": 1}], indirect=True)
def test_configurable_text_limits(api):
    assert post(api, text="é" * 512).status_code == 200
    assert post(api, text="é" * 513).status_code == 413
    assert post_file(api, ("é" * 512).encode()).status_code == 200
    assert post_file(api, ("é" * 513).encode()).status_code == 413
    assert api.pipeline.call_count == 2


@pytest.mark.parametrize("api", [{"max_input_kib": 1}], indirect=True)
def test_escaped_json_and_total_body_limit(api):
    content = json.dumps({"text": "éé", "output_file": str(api.output)}, ensure_ascii=True)
    assert api.client.post("/speech", content=content, headers={"Content-Type": "application/json"}).status_code == 200
    limit = 6 * api.config.input_limit_bytes + 65536
    response = api.client.post("/speech", content=b"x" * (limit + 1), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    response = api.client.post("/speech/file", data={"output_file": str(api.output)},
                               files={"input_file": ("x.txt", b"x" * limit)})
    assert response.status_code == 413
    assert api.pipeline.call_count == 1


@pytest.mark.parametrize("exceeds_limit", [False, True])
@pytest.mark.parametrize("api", [{"max_input_kib": 1}], indirect=True)
def test_streamed_request_body_limit(api, exceeds_limit):
    body = json.dumps({"text": "a", "output_file": str(api.output)}).encode()
    limit = 6 * api.config.input_limit_bytes + 65536
    body += b" " * (limit + int(exceeds_limit) - len(body))
    headers = [(b"host", b"127.0.0.1:47864"), (b"content-type", b"application/json")]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "scheme": "http", "method": "POST", "path": "/speech", "raw_path": b"/speech",
        "query_string": b"", "headers": headers, "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 47864),
    }
    chunks = iter([
        {"type": "http.request", "body": body[:100], "more_body": True},
        {"type": "http.request", "body": body[100:], "more_body": False},
    ])
    responses = []

    async def receive():
        return next(chunks, {"type": "http.disconnect"})

    async def send(message):
        responses.append(message)

    asyncio.run(api.client.app(scope, receive, send))
    assert responses[0]["status"] == (413 if exceeds_limit else 200)
    assert api.pipeline.call_count == (0 if exceeds_limit else 1)


def test_upload_does_not_block_event_loop_or_parallelize_synthesis(api):
    entered, release = Event(), Event()
    original = api.pipeline.return_value
    calls = []

    def pipeline(*args, **kwargs):
        calls.append(args[0])
        entered.set()
        assert release.wait(5)
        return original

    api.pipeline.side_effect = pipeline
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(post_file, api, b"first")
        try:
            assert entered.wait(2)
            second = pool.submit(post, api, text="second")
            health = pool.submit(api.client.get, "/health")
            assert health.result(timeout=2).status_code == 200
            assert calls == ["first"]
        finally:
            release.set()
        assert first.result(timeout=3).status_code == 200
        assert second.result(timeout=3).status_code == 200
    assert calls == ["first", "second"]


def test_output_and_synthesis_failures(api):
    assert post(api, output_file=str(api.output / "a.wav")).status_code == 400
    api.output.mkdir()
    assert post(api).status_code == 400
    api.pipeline.side_effect = RuntimeError("Synthesis failed")
    assert post(api).status_code == 500


def test_file_upload_output_and_synthesis_failures(api):
    missing_parent = api.output / "missing" / "sample.wav"
    assert post_file(api, b"Hello", output_file=str(missing_parent)).status_code == 400
    api.pipeline.side_effect = RuntimeError("Synthesis failed")
    assert post_file(api, b"Hello").status_code == 500


def test_default_logs_omit_request_and_response_content(api, caplog):
    secret = "private speech text"
    with caplog.at_level(logging.INFO, logger="kokoro_server.api"):
        response = api.client.post("/speech?token=private-query", json={"text": secret, "output_file": str(api.output)})
        invalid = post(api, text=None, voice="private-invalid-voice", speed=3)
        post_file(api, b"private uploaded text")
    assert response.status_code == 200
    assert invalid.status_code == 422
    events = [json.loads(record.getMessage()) for record in caplog.records
              if record.name == "kokoro_server.api" and record.levelno == logging.INFO]
    assert [event["response"]["status"] for event in events] == [200, 422, 200]
    assert events[0]["request"] == {"method": "POST", "path": "/speech"}
    assert secret not in caplog.text
    assert "private-query" not in caplog.text
    assert "private-invalid-voice" not in caplog.text
    assert "private uploaded text" not in caplog.text
    assert str(api.output) not in caplog.text


@pytest.mark.parametrize("api", [{"detailed_logs": "true"}], indirect=True)
def test_detailed_logs_include_json_request_and_response(api, caplog):
    upload_content = b"private uploaded text omitted from logs"
    with caplog.at_level(logging.INFO, logger="kokoro_server.api"):
        api.client.post("/speech?token=debug-query", json={"text": "Hello", "output_file": str(api.output)})
        post(api, text=None)
        post_file(api, upload_content)
        api.pipeline.side_effect = RuntimeError("Synthesis failed")
        post(api)
    events = [
        json.loads(record.getMessage()) for record in caplog.records
        if record.name == "kokoro_server.api" and record.levelno == logging.INFO
    ]
    assert [event["response"]["status"] for event in events] == [200, 422, 200, 500]
    assert events[0]["request"]["body"]["text"] == "Hello"
    assert events[0]["request"]["query"] == "token=debug-query"
    assert events[0]["response"]["body"]["output_file"] == str(api.output)
    assert events[2]["request"]["body"] == "[multipart body omitted]"
    assert upload_content.decode() not in caplog.text


def test_openapi_describes_json_and_multipart_requests(api):
    schema = api.client.get("/openapi.json").json()
    json_content = schema["paths"]["/speech"]["post"]["requestBody"]["content"]
    upload_content = schema["paths"]["/speech/file"]["post"]["requestBody"]["content"]
    assert "application/json" in json_content
    assert "multipart/form-data" in upload_content
    body_ref = upload_content["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    upload_schema = schema["components"]["schemas"][body_ref]
    assert "input_file" in upload_schema["properties"]
    assert "input_file" in upload_schema["required"]
    assert "output_file" not in upload_schema["required"]
    assert "output_file" not in schema["components"]["schemas"]["SpeechRequest"]["required"]
