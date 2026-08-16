"""Bot configuration — loaded from environment variables."""

import os


class Config:
    """All config values read from env vars with sensible defaults."""

    # --- Access control ---
    authorized_users: list[int] = [
        int(uid.strip()) for uid in os.getenv("AUTHORIZED_USERS", "").split(",")
        if uid.strip().lstrip("-").isdigit()
    ]

    # --- Telegram ---
    bot_token: str = os.getenv("BOT_TOKEN", "")

    # --- Transcription (faster-whisper) ---
    asr_model: str = os.getenv("ASR_MODEL", "distil-large-v3")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute: str = os.getenv("WHISPER_COMPUTE", "float32")
    asr_num_threads: int = int(os.getenv("ASR_NUM_THREADS", "4"))

    # --- LLM (OpenAI‑compatible) ---
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://your-llm-server:8088/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "not-needed")
    llm_model: str = os.getenv("LLM_MODEL", "grug-35b-v2-iq4xs")

    # --- Summary ---
    summary_max_messages: int = int(os.getenv("SUMMARY_MAX_MESSAGES", "500"))
    summary_history_path: str = os.getenv(
        "SUMMARY_HISTORY_PATH", "/data/history.jsonl"
    )

    # --- Persona ---
    personas_path: str = os.getenv("PERSONAS_PATH", "/data/personas.yaml")

    # --- Prometheus (optional) ---
    metrics_port: int = int(os.getenv("METRICS_PORT", "0"))

    # --- General ---
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def valid(self) -> bool:
        errors: list[str] = []
        if not self.bot_token:
            errors.append("BOT_TOKEN is required")
        if not self.authorized_users:
            errors.append(
                "AUTHORIZED_USERS is required — comma-separated Telegram user IDs"
            )
        if self.summary_max_messages < 1:
            errors.append("SUMMARY_MAX_MESSAGES must be >= 1")
        if errors:
            for e in errors:
                print(f"[config] ERROR: {e}")
            return False
        return True