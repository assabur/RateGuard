FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --create-home rateguard && mkdir /app/data && chown rateguard:rateguard /app/data
USER rateguard
EXPOSE 8000
CMD ["rateguard", "serve", "--host", "0.0.0.0"]
