FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# DWG/DXF stack
RUN apt-get update && apt-get install -y --no-install-recommends \
        libredwg-bin \
        fonts-dejavu \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY README.md ./

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8080

ENTRYPOINT ["kmd-checker"]
CMD ["server", "--host", "0.0.0.0", "--port", "8080"]
