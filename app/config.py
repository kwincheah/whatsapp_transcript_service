from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Summarisation (DeepSeek, OpenAI-compatible API)
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    summary_model: str = "deepseek-v4-flash"
    summary_min_seconds: float = 8.0
    summary_max_tokens: int = 400  # headroom for reasoning; the prompt keeps output short

    @property
    def allowed_sender_set(self) -> set[str]:
        return {s.strip().lstrip("+") for s in self.allowed_senders.split(",") if s.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
