FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY arcana/ arcana/
COPY migrations/ migrations/
COPY alembic.ini .

RUN pip install --no-cache-dir -e .

RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "arcana.main:app", "--host", "0.0.0.0", "--port", "8000"]
