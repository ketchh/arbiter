FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY broker/ broker/

RUN pip install --no-cache-dir . \
 && useradd -r -s /bin/false arbiter

USER arbiter

# Default env — override at runtime
ENV BROKER_BIND_HOST=0.0.0.0
ENV BROKER_BIND_PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=3)" || exit 1

CMD ["arbiter", "serve"]
