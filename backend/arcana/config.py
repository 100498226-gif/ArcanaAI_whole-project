from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Gemini (LLM + embeddings)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    embedding_model: str = "gemini-embedding-001"

    # Optional image captioning API (remote captioning for ingested images)
    image_caption_api_url: str = ""

    # ChromaDB
    chromadb_path: str = "./data/chromadb"

    # GitHub ingestion
    github_pat: str = ""
    github_repos: str = ""  # comma-separated: "owner/repo1,owner/repo2"

    # Notion ingestion
    notion_token: str = ""
    notion_page_ids: str = ""  # comma-separated Notion page IDs
    notion_max_depth: int = 5
    notion_request_delay_ms: int = 350

    # Ollama (local model for offline mode)
    ollama_base_url: str = "http://localhost:11434"
    ollama_fast_model: str = "qwen2.5:3b"  # OLLAMA_FAST_MODEL in .env

    # RAG
    retrieval_top_k: int = 15
    context_token_budget: int = 6000
    score_threshold: float = 0.3       # minimum cosine similarity to include a chunk
    gemini_temperature: float = 0.2
    gemini_max_output_tokens: int = 2000

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
