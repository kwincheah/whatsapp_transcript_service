from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # WhatsApp Cloud API
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str = ""  # if set, webhook signatures are verified
    whatsapp_api_version: str = "v23.0"
    # Comma-separated E.164 numbers without "+", e.g. "60123456789". Empty = allow anyone.
    allowed_senders: str = ""

    # Speech-to-text (OpenAI)
    openai_api_key: str
    stt_model: str = "gpt-4o-mini-transcribe"
    # Comma-separated names/jargon to help spelling; users can add more with /vocab.
    stt_vocab: str = ""
    stt_max_bytes: int = 25 * MB  # OpenAI upload limit

    # Analysis (DeepSeek, OpenAI-compatible API)
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    summary_model: str = "deepseek-v4-flash"
    # DeepSeek V4+ reasons by default; off = faster, and these tasks don't need it.
    summary_thinking: bool = False

    # Voice: what to add, by audio length
    summary_min_seconds: float = 8.0
    key_points_min_seconds: float = 60.0
    # Translate transcripts/summaries into this language (e.g. "English"). Users override with /lang.
    translate_to: str = ""

    # Output token budgets per task (thinking is off, so these are all output text)
    voice_summary_max_tokens: int = 150  # one sentence
    voice_key_points_max_tokens: int = 350  # 3-5 bullets
    translation_max_tokens: int = 4000  # cap; actual budget scales with transcript length
    doc_max_output_tokens: int = 1500  # summary + key points + optional answer

    # Documents: input limits
    doc_max_bytes: int = 20 * MB
    doc_max_input_chars: int = 150_000  # ~40k tokens sent to the model; longer docs are truncated

    # History / stats (SQLite). On Railway, mount a volume at /app/data to keep it across deploys.
    db_path: str = "data/bot.db"

    # Cost estimates in USD (check provider pricing pages; DeepSeek defaults are peak-hour rates)
    price_stt_per_min: float = 0.003
    price_llm_input_per_m: float = 0.30
    price_llm_cached_input_per_m: float = 0.006
    price_llm_output_per_m: float = 1.20

    @property
    def allowed_sender_set(self) -> set[str]:
        return {s.strip().lstrip("+") for s in self.allowed_senders.split(",") if s.strip()}

    @property
    def stt_vocab_list(self) -> list[str]:
        return [w.strip() for w in self.stt_vocab.split(",") if w.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
