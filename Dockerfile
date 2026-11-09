FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 meeting \
    && mkdir -p /app/data \
    && chown meeting:meeting /app/data
USER meeting
EXPOSE 4561
ENV MEETING_MCP_HOST=0.0.0.0 \
    MEETING_MCP_PORT=4561 \
    MEETING_DB_PATH=/app/data/meeting_booking.sqlite3
CMD ["meeting-mcp"]
