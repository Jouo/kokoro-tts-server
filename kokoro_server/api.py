"""HTTP contract for the local speech service."""

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from kokoro_server.speech import SpeechService
from kokoro_server.settings import Language, get_settings, validate_output_file
from kokoro_server.request_safety import RequestSafety


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SpeechOptions(BaseModel):
    # The multipart form also contains the separately declared file field.
    model_config = ConfigDict(extra="ignore")

    output_file: NonEmptyString = Field(default_factory=lambda: get_settings().output_file, validate_default=True, description="WAV file path on the server. Required unless a default is configured. Its parent must exist; existing files are overwritten. Relative paths use the server working directory.")
    language: Language = Field(default_factory=lambda: get_settings().language)
    voice: NonEmptyString | None = None
    speed: float | None = Field(default=None, ge=0.1, le=2.0, strict=True, description="Omit to use the configured speed. Explicit null is not accepted.")

    @field_validator("speed")
    @classmethod
    def validate_speed(cls, value: float | None) -> float:
        # Omission selects the configured default; explicit null remains invalid.
        if value is None:
            raise ValueError("speed must be a number when provided")
        return value

    _validate_output_file = field_validator("output_file")(validate_output_file)


class SpeechRequest(SpeechOptions):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"text": "Hello!", "output_file": "sample.wav"}]},
    )

    text: NonEmptyString


class SpeechUploadOptions(SpeechOptions):
    speed: float | None = Field(default=None, ge=0.1, le=2.0)


class SpeechResponse(BaseModel):
    output_file: str
    sample_rate: int
    duration_seconds: float


class InteractionLogging:
    """Observe ASGI messages without consuming or changing request/response bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        detailed = get_settings().detailed_logs
        content_type = next(
            (value.decode("latin-1") for name, value in scope.get("headers", [])
             if name.lower() == b"content-type"),
            "",
        )
        is_multipart = content_type.partition(";")[0].strip().lower() == "multipart/form-data"
        request_body = bytearray()
        response_body = bytearray()
        status = 500

        async def logged_receive():
            message = await receive()
            if detailed and message["type"] == "http.request" and not is_multipart:
                request_body.extend(message.get("body", b""))
            return message

        async def logged_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif detailed and message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
            await send(message)

        def decode(body):
            try:
                return json.loads(body) if body else None
            except (ValueError, UnicodeDecodeError):
                return body.decode("utf-8", errors="replace")

        try:
            await self.app(scope, logged_receive, logged_send)
        except Exception:
            # FastAPI's outer error middleware emits this response for unhandled errors.
            if detailed and not response_body:
                response_body.extend(b"Internal Server Error")
            raise
        finally:
            interaction = {
                "event": "interaction",
                "client": scope.get("client"),
                "request": {"method": scope["method"], "path": scope["path"]},
                "response": {"status": status},
            }
            if detailed:
                interaction["request"]["query"] = scope.get("query_string", b"").decode("utf-8", errors="replace")
                interaction["request"]["body"] = "[multipart body omitted]" if is_multipart else decode(request_body)
                interaction["response"]["body"] = decode(response_body)
            logging.getLogger(__name__).info(json.dumps(interaction, ensure_ascii=False))


def create_app(service_factory=SpeechService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        get_settings()
        app.state.speech = service_factory()
        yield
        del app.state.speech

    app = FastAPI(title="Local Kokoro TTS", lifespan=lifespan)
    app.add_middleware(InteractionLogging)
    app.add_middleware(RequestSafety)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/speech", response_model=SpeechResponse)
    def generate_speech(body: SpeechRequest, request: Request):
        try:
            size = len(body.text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise HTTPException(400, "Text must be valid UTF-8") from exc
        if size > get_settings().input_limit_bytes:
            raise HTTPException(413, "Text exceeds the configured size limit")
        return synthesize(body.text, body, request)

    @app.post("/speech/file", response_model=SpeechResponse)
    async def generate_speech_file(
        request: Request,
        options: Annotated[SpeechUploadOptions, Form()],
        input_file: Annotated[UploadFile, File(description="UTF-8 text file; size limit is configurable.")],
    ):
        try:
            limit = get_settings().input_limit_bytes
            content = await input_file.read(limit + 1)
            if len(content) > limit:
                raise HTTPException(413, "Uploaded text file exceeds the configured size limit")
            try:
                text = content.decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise HTTPException(400, "Uploaded file must be valid UTF-8 text") from exc
            if not text:
                raise HTTPException(400, "Uploaded file must contain nonempty text")
            return await run_in_threadpool(synthesize, text, options, request)
        finally:
            await input_file.close()

    def synthesize(text: str, options: SpeechOptions, request: Request) -> SpeechResponse:
        try:
            output = Path(options.output_file).expanduser().resolve()
            if not output.parent.is_dir():
                raise HTTPException(400, "Output parent directory does not exist")
            service = request.app.state.speech
            duration = service.generate(
                text, output,
                language=options.language, voice=options.voice, speed=options.speed,
            )
        except OSError as exc:
            logging.getLogger(__name__).exception("Could not write speech output")
            raise HTTPException(400, "Cannot write the requested output file") from exc
        except RuntimeError as exc:
            logging.getLogger(__name__).exception("Speech generation failed")
            raise HTTPException(500, "Speech generation failed") from exc
        return SpeechResponse(
            output_file=str(output),
            sample_rate=service.sample_rate,
            duration_seconds=duration,
        )

    return app


app = create_app()
