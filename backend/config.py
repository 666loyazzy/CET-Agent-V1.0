from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["anthropic", "openai", "deepseek"] = "anthropic"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    judge_provider: str = ""
    judge_model: str = ""
    judge_openai_api_key: str = ""
    judge_openai_base_url: str = ""

    # Embeddings — separate third channel from chat/judge. Default: DashScope
    # (Alibaba Tongyi) OpenAI-compatible, text-embedding-v3, 1024 dim. Any
    # provider exposing /v1/embeddings works; changing dim requires dropping
    # the vec_embedding_items virtual table so it can be recreated.
    embedding_provider: str = "openai"
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    skill_dir: Path = PROJECT_ROOT / "skill"

    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""

    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def skill_md_path(self) -> Path:
        return self.skill_dir / "SKILL.md"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = (self.data_dir / "cet-agent.db").as_posix()
        return f"sqlite+aiosqlite:///{db_path}"


settings = Settings()
