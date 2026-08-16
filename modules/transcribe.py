"""Transcription plugin — voice/audio → text via faster-whisper."""

import logging
import os
import signal
import subprocess
import time
from typing import BinaryIO

import ffmpeg
import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model initialisation (lazy‑singleton — first call to transcribe loads it)
# ---------------------------------------------------------------------------
_model: WhisperModel | None = None
_model_name: str = ""
_loaded_lock = False

SAMPLE_RATE = 16000


def _get_model(model_name: str, device: str, compute: str, num_threads: int) -> WhisperModel:
    global _model, _model_name, _loaded_lock
    if _model is None or _model_name != model_name:
        logger.info(
            "Loading faster-whisper model '%s' on %s (compute=%s, threads=%d)",
            model_name,
            device,
            compute,
            num_threads,
        )
        _model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute,
            num_workers=num_threads,
            cpu_threads=num_threads,
        )
        _model_name = model_name
        logger.info("Model loaded successfully")
    return _model


# ---------------------------------------------------------------------------
# Audio helpers (ported from tgisper)
# ---------------------------------------------------------------------------
def _load_audio(binary_data: bytes, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Decode raw audio bytes to mono float32 waveform via ffmpeg."""
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install it")

    try:
        out, _ = (
            ffmpeg.input("pipe:", threads=0)
            .output("-", format="s16le", acodec="pcm_s16le", ac=1, ar=sr)
            .run(cmd="ffmpeg", capture_stdout=True, capture_stderr=True, input=binary_data)
        )
    except ffmpeg.Error as exc:
        raise RuntimeError(f"ffmpeg decode failed: {exc.stderr.decode()}") from exc

    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------
# Core transcription
# ---------------------------------------------------------------------------
def transcribe_audio(
    audio_bytes: bytes,
    model_name: str = "distil-large-v3",
    device: str = "cpu",
    compute: str = "float32",
    threads: int = 4,
) -> str:
    """Download → decode → transcribe → return text."""
    model = _get_model(model_name, device, compute, threads)
    waveform = _load_audio(audio_bytes)
    segments, info = model.transcribe(
        audio=waveform,
        vad_filter=True,
        beam_size=1,
    )
    text = "".join(seg.text for seg in segments).strip()
    logger.debug("Transcribed %.1fs audio: %s", info.duration, text[:80])
    return text


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from modules.base import BotPlugin


class TranscribePlugin(BotPlugin):
    def __init__(self, config) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "transcribe"

    def help_text(self) -> str:
        return "🗣️ Transcribes voice / audio messages to text"

    def register(self, app: Application) -> None:
        app.add_handler(
            MessageHandler(
                (filters.VOICE | filters.AUDIO | filters.Document.AUDIO) & self._auth,
                self._handle_audio,
            )
        )

    async def _handle_audio(
        self, update: Update, _context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        msg = update.effective_message
        if not msg:
            return

        # Extract file_id from whichever content type
        content_type: str = msg.content_type
        file_id = None
        if content_type == "voice":
            file_id = msg.voice.file_id
        elif content_type == "audio":
            file_id = msg.audio.file_id
        elif content_type == "document":
            doc = msg.document
            if doc and doc.mime_type and doc.mime_type.startswith("audio/"):
                file_id = doc.file_id
        if not file_id:
            return

        start = time.perf_counter()
        try:
            await msg.chat.send_action("typing")

            file = await msg.effective_chat.get_file(file_id)
            audio_bytes = await file.download_as_bytearray()

            text = transcribe_audio(
                audio_bytes,
                model_name=self._cfg.asr_model,
                device=self._cfg.whisper_device,
                compute=self._cfg.whisper_compute,
                threads=self._cfg.asr_num_threads,
            )

            if not text.strip():
                await msg.reply_text("Couldn't make out any speech in that audio.")
            else:
                await msg.reply_text(text)

            elapsed = time.perf_counter() - start
            logger.info(
                "Transcribed %s %s in %.1fs: '%s'",
                content_type,
                file_id[:12],
                elapsed,
                text[:60],
            )
        except Exception as exc:
            logger.error("Transcription error: %s", exc)
            await msg.reply_text("Sorry, something went wrong processing that audio.")