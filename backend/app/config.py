"""Central config: env vars, LLM provider presets, budgets and thresholds.

LLM access goes through any OpenAI-compatible endpoint. Presets:
  groq          -> https://api.groq.com/openai/v1      (needs LLM_API_KEY from console.groq.com)
  ollama_cloud  -> https://ollama.com/v1               (needs LLM_API_KEY from ollama.com/settings/keys)
  ollama_local  -> http://localhost:11434/v1           (no key; run `ollama serve`)
  openai_compat -> set LLM_BASE_URL yourself
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
# Runtime state (database, fetch cache, eval runs, briefs). Docker points this at a volume.
DATA_DIR = Path(os.environ.get("VEYRA_DATA_DIR") or (REPO_DIR / "data")).resolve()
# Frozen backtest dataset: shipped with the code, read-only, so it stays in the repo even when DATA_DIR moves.
REPLAY_DATA_DIR = REPO_DIR / "data" / "replay"

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "strong": "openai/gpt-oss-120b",
        "fast": "openai/gpt-oss-20b",
    },
    "ollama_cloud": {
        "base_url": "https://ollama.com/v1",
        "strong": "gpt-oss:120b",
        "fast": "gpt-oss:20b",
    },
    "ollama_local": {
        "base_url": "http://localhost:11434/v1",
        "strong": "llama3.1:8b",
        "fast": "llama3.1:8b",
    },
    "openai_compat": {"base_url": "", "strong": "", "fast": ""},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    # --- LLM ---
    llm_provider: str = "groq"
    llm_api_key: str = ""
    llm_base_url: str = ""  # overrides preset when set
    llm_strong: str = ""  # strategist / skeptic / chat / reporter
    llm_fast: str = ""  # classification / stance labeling
    llm_timeout_s: float = 60.0
    llm_tpm_limit: int = 0  # client-side tokens/minute throttle; 0 = auto (8000 for groq free tier)
    llm_max_wait_s: float = 2700  # wait up to 45 min on a provider rate limit (e.g. Groq daily cap) before failing
    llm_max_tokens: int = 4096  # reasoning models (gpt-oss) spend part of this on hidden reasoning

    # --- deployment / security ---
    env: str = Field(default="development", validation_alias=AliasChoices("VEYRA_ENV"))
    admin_password: str = Field(default="", validation_alias="VEYRA_ADMIN_PASSWORD")
    secret_key: str = Field(default="", validation_alias="VEYRA_SECRET_KEY")
    cookie_secure_override: bool | None = Field(default=None, validation_alias="VEYRA_COOKIE_SECURE")
    log_level: str = "INFO"

    # --- storage ---
    db_url: str = f"sqlite:///{(DATA_DIR / 'veyra.db').as_posix()}"

    # --- crawling etiquette ---
    user_agent_email: str = "veyra-bot@example.com"
    per_domain_delay_s: float = 2.0
    fetch_timeout_s: float = 20.0

    # --- agent budgets (hard limits) ---
    investigator_max_tool_calls: int = 6  # per hypothesis per cycle
    cycle_max_fetches: int = 25
    run_max_tokens: int = 60_000
    investigator_min_delta: float = 0.02  # stop when evidence moves confidence less than this
    uncertain_band: tuple[float, float] = (0.35, 0.80)
    strategist_max_new_hypotheses: int = 2
    strategist_max_signals: int = 40  # per competitor per cycle, highest priority first
    max_investigations_per_cycle: int = 2  # per competitor
    max_skeptic_per_cycle: int = 2  # per competitor
    skeptic_threshold: float = 0.6  # challenge before a hypothesis is raised to likely / alerted
    prediction_threshold: float = 0.6  # register falsifiable predictions at or above this
    classify_with_llm: bool = True  # page/news classification; the backtest can switch to deterministic rules
    investigator_role: str = "fast"  # "fast" saves strong-model quota on free tiers; set "strong" for quality

    # --- scheduling ---
    scheduler_enabled: bool = False
    cycle_interval_min: int = 720

    # --- notifications (optional) ---
    slack_webhook_url: str = ""

    @property
    def production(self) -> bool:
        return self.env.lower() in ("production", "prod")

    @property
    def cookie_secure(self) -> bool:
        """Secure cookies need HTTPS; default on in production. Set VEYRA_COOKIE_SECURE=false for plain-HTTP LAN use."""
        return self.production if self.cookie_secure_override is None else self.cookie_secure_override

    def check_production(self) -> list[str]:
        """Problems that must stop a production start (an open, unauthenticated instance spends your API key)."""
        problems = []
        if self.production:
            if len(self.admin_password) < 10:
                problems.append("VEYRA_ADMIN_PASSWORD must be set (at least 10 characters)")
            if len(self.secret_key) < 32:
                problems.append("VEYRA_SECRET_KEY must be set (at least 32 random characters)")
        return problems

    @property
    def preset(self) -> dict[str, str]:
        return PROVIDER_PRESETS.get(self.llm_provider, PROVIDER_PRESETS["openai_compat"])

    @property
    def resolved_base_url(self) -> str:
        return self.llm_base_url or self.preset["base_url"]

    @property
    def model_strong(self) -> str:
        return self.llm_strong or self.preset["strong"]

    @property
    def model_fast(self) -> str:
        return self.llm_fast or self.preset["fast"]

    @property
    def llm_configured(self) -> bool:
        needs_key = self.llm_provider != "ollama_local"
        return bool(self.resolved_base_url and self.model_strong and (self.llm_api_key or not needs_key))

    @property
    def user_agent(self) -> str:
        return f"VeyraCIBot/0.1 (college research project; contact: {self.user_agent_email})"


@lru_cache
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()
