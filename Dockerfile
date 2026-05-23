FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

# Fonts для matplotlib (рендер DXF) + ca + curl для healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Сначала dep-файлы — кэш слоя зависимостей
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Остальной код
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8080

ENTRYPOINT ["kmd-checker"]
CMD ["server", "--host", "0.0.0.0", "--port", "8080"]
