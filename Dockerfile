# Presentation Studio API. Python backend and Oracle thick mode only.
# Layout checks and PPTX/PDF export need the Node presentation-export runtime,
# which this image does not install.

FROM python:3.11-slim-bookworm

ARG http_proxy=http://proxy.etisalat.corp.ae:8080
ARG https_proxy=http://proxy.etisalat.corp.ae:8080
# Override when download.oracle.com is blocked. Folder inside the zip must match ORACLE_CLIENT_PATH.
ARG ORACLE_IC_URL=https://download.oracle.com/otn_software/linux/instantclient/2326300/instantclient-basiclite-linux.x64-23.26.3.0.0.zip

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    APP_DATA_DIRECTORY=/app_data \
    TEMP_DIRECTORY=/tmp/presenton \
    ORACLE_CLIENT_PATH=/opt/oracle/instantclient_23_26 \
    LD_LIBRARY_PATH=/opt/oracle/instantclient_23_26 \
    ORACLE_PROTOCOL=tcp \
    CONTEXT_PATH=/presentation-studio

# Instant Client for Native Network Encryption. The thin driver fails with DPY-3001 on this listener.
RUN set -eux; \
    export HTTP_PROXY="$http_proxy" HTTPS_PROXY="$https_proxy" http_proxy="$http_proxy" https_proxy="$https_proxy"; \
    apt-get -o Acquire::Check-Valid-Until=false -o Acquire::Retries=3 update; \
    apt-get install -y --no-install-recommends ca-certificates libaio1 wget unzip; \
    mkdir -p /opt/oracle; \
    cd /opt/oracle; \
    wget -q --header "Cookie: oraclelicense=accept-securebackup-cookie" -O ic.zip "$ORACLE_IC_URL"; \
    unzip -q ic.zip; \
    rm -f ic.zip; \
    test -d "$ORACLE_CLIENT_PATH"; \
    echo "$ORACLE_CLIENT_PATH" > /etc/ld.so.conf.d/oracle-instantclient.conf; \
    ldconfig; \
    apt-get purge -y --auto-remove wget unzip; \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app_data /tmp/presenton \
    && chown -R appuser:appuser /app_data /tmp/presenton

WORKDIR /app/servers/fastapi

RUN pip install --proxy "$http_proxy" --no-cache-dir uv

COPY servers/fastapi/pyproject.toml servers/fastapi/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY servers/fastapi /app/servers/fastapi
RUN uv sync --locked --no-dev --no-editable \
    && chown -R appuser:appuser /app

ENV PATH="/app/servers/fastapi/.venv/bin:${PATH}"

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import socket; s=socket.create_connection(('127.0.0.1',8000),5); s.close()"

# Oracle credentials, PERSISTENCE_MODE, and CONTEXT_PATH are supplied at runtime.
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
