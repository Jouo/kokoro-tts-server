"""Model lifetime and serialized WAV generation."""

import logging
from pathlib import Path
from threading import Lock

import numpy as np
import soundfile as sf

from kokoro_server.settings import get_settings


LANGUAGE_CODES = {
    "american": "a", "british": "b", "japanese": "j", "mandarin": "z",
    "spanish": "e", "french": "f", "hindi": "h", "italian": "i",
}


class SpeechService:
    sample_rate = 24000

    def __init__(self):
        import torch
        from kokoro import KPipeline

        self.settings = get_settings()
        self.device = self.settings.device
        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logging.getLogger(__name__).info("Loading Kokoro on %s", self.device)
        self.pipelines = {"a": KPipeline(lang_code="a", device=self.device)}
        self._lock = Lock()

    def generate(
        self, text: str, output: Path, *,
        language: str | None = None, voice: str | None = None, speed: float | None = None,
    ) -> float:
        # Pipelines share one model; protect initialization, synthesis, and writes.
        with self._lock:
            language = language or self.settings.language
            code = LANGUAGE_CODES[language]
            if speed is None:
                speed = self.settings.speed
            if code not in self.pipelines:
                from kokoro import KPipeline

                self.pipelines[code] = KPipeline(
                    lang_code=code, model=self.pipelines["a"].model,
                )
            pipeline = self.pipelines[code]
            try:
                chunks = [
                    audio.detach().cpu().numpy()
                    for _, _, audio in pipeline(text, voice=voice or self.settings.voice, speed=speed)
                ]
            except OSError as exc:
                raise RuntimeError("Could not load the voice or generate speech") from exc
            if not chunks:
                raise RuntimeError("Kokoro generated no audio.")
            audio = np.concatenate(chunks)
            try:
                sf.write(output, audio, self.sample_rate, format="WAV")
            except sf.LibsndfileError as exc:
                raise OSError(f"Cannot write WAV to {output}") from exc
            return len(audio) / self.sample_rate
