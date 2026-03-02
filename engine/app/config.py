from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://graphmentor:graphmentor@localhost:5432/graphmentor"
    chromadb_mode: str = "persistent"  # "persistent" or "http"
    chromadb_path: str = "./data/chromadb"
    chromadb_host: str = "localhost"
    chromadb_port: int = 8100
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    search_provider: str = "wikipedia"
    enrichment_word_threshold: int = 100

    model_config = {"env_file": ["../.env", ".env"], "env_file_encoding": "utf-8"}


settings = Settings()
