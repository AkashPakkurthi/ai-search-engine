from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "sqlite:///./search_engine.db"
    crawl_depth: int = 2
    max_pages: int = 50

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
