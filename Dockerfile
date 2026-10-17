FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV LIBRARY_DB=/data/library.db

EXPOSE 8765

CMD ["uvicorn", "library.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
