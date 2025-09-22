## Dockerfile for agents (FastAPI + Google ADK multi-agent service)
## Uses multi-stage build to keep runtime image slim.
## Notes:
##  - requirements.txt contains scientific and Google Cloud libs; we use python:3.12-slim for broader compatibility
##  - Add build deps only in builder then copy site-packages.

FROM --platform=$BUILDPLATFORM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	PIP_NO_CACHE_DIR=1

FROM base AS builder
WORKDIR /wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	gcc \
	git \
	curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && \
	pip wheel -r requirements.txt -w /wheels

FROM base AS runtime
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

COPY . .

EXPOSE 8080
ENV PORT=8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]

