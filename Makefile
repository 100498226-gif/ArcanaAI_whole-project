.PHONY: run dev setup setup-overlay overlay clean

# -- Run ----------------------------------------------------------------------
# Hot-reload only watches the arcana/ source dir, not .venv (avoids fork crashes)
run:
	cd backend && source .venv/bin/activate && \
	uvicorn arcana.main:app --reload --reload-dir arcana --port 8000

# Without reload (more stable on resource-constrained machines)
dev:
	cd backend && source .venv/bin/activate && \
	uvicorn arcana.main:app --port 8000

# -- Setup --------------------------------------------------------------------
setup:
	cd backend && python -m venv .venv && source .venv/bin/activate && \
	pip install fastapi uvicorn[standard] sse-starlette chromadb google-genai \
	            pydantic-settings tiktoken gitpython PyGithub notion-client structlog

# -- Electron overlay ---------------------------------------------------------
# First time only: install Electron dependencies
setup-overlay:
	cd electron && npm install

# Launch the menu-bar overlay (backend must already be running)
overlay:
	cd electron && npm start

# -- Clean --------------------------------------------------------------------
clean:
	rm -rf data/chromadb data/arcana.db
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
