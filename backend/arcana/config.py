from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Gemini (LLM + embeddings)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # ChromaDB
    chromadb_path: str = "./data/chromadb"

    # RAG
    retrieval_top_k: int = 15
    context_token_budget: int = 6000
    score_threshold: float = 0.3
    gemini_temperature: float = 0.2
    gemini_max_output_tokens: int = 2000

    # Database (SQLite by default)
    database_url: str = "sqlite+aiosqlite:///./data/arcana.db"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    def build_google_client(self):
        from google import genai  # type: ignore[import]
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        return genai.Client(api_key=self.gemini_api_key)


settings = Settings()
