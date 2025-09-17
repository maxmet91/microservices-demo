# Simple FastAPI service
FROM --platform=$BUILDPLATFORM python:3.12.8-alpine AS base

FROM base AS builder
RUN apk add --no-cache build-base linux-headers && rm -rf /var/cache/apk/*
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

FROM base
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
