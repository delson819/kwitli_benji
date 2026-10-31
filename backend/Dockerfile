FROM python:3.14.3-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN groupadd --system kwitli \
    && useradd --system --gid kwitli --create-home kwitli \
    && mkdir -p /app/backend/uploads \
    && chown -R kwitli:kwitli /app

COPY --chown=kwitli:kwitli backend/ /app/backend/
COPY --chown=kwitli:kwitli migrations/ /app/migrations/
COPY --chown=kwitli:kwitli alembic.ini /app/alembic.ini

USER kwitli

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
