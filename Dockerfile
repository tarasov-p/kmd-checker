FROM ubuntu:24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

# Python + DWG/DXF stack
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        libredwg-bin \
        fonts-dejavu \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

# uv (через pip с --break-system-packages: ubuntu 24.04 = PEP 668)
RUN pip install --no-cache-dir --break-system-packages uv

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
