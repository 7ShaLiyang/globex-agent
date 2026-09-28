FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY knowledge ./knowledge
COPY scripts ./scripts
RUN mkdir -p /app/data && useradd --uid 10001 --create-home globex && chown -R globex:globex /app
USER globex
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn","app.presentation.api:app","--host","0.0.0.0","--port","8000"]
