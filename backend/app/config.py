from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM provider — any OpenAI-compatible endpoint.
    # Defaults target Google Gemini 2.5 Flash via AI Studio's OpenAI shim.
    # Swap base_url + model for Groq, DeepSeek, OpenAI, Ollama, etc.
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_model: str = "gemini-2.5-flash"
    llm_top_n: int = 10  # max trade suggestions returned per LLM run
    llm_candidate_pool: int = 25  # top-by-raw-confidence sent to LLM for ranking

    database_url: str = "sqlite:///./trading_agent.db"

    news_interval_min: int = 30
    market_interval_min: int = 15
    signal_interval_min: int = 60
    live_quotes_interval_min: int = 5

    market_open_hhmm: str = "0915"
    market_close_hhmm: str = "1530"

    # --- Upstox live feed (V3 market-data WS) ---
    # When upstox_api_key is blank, the integration is a no-op and the app
    # silently falls back to the yfinance ~15-min-delayed live agent.
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_redirect_uri: str = ""
    # Daily reminder time (IST) embedded in the .ics calendar feed.
    upstox_reminder_hhmm: str = "0800"

    # --- Auth (Google OAuth + email allowlist) ---
    # When auth_enabled is False, all routes are open (handy for local dev).
    auth_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    session_secret: str = "change-me-to-a-long-random-string"
    # Comma-separated list of allowed email addresses.
    allowed_emails_raw: str = ""
    # Optional override; if blank, callback URL is built from the request.
    oauth_redirect_uri: str = ""

    @property
    def allowed_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails_raw.split(",") if e.strip()}


settings = Settings()
