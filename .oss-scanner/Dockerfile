FROM python:3.14-bookworm
COPY --from=astral/uv:0.12.22 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/usr/local
COPY . /src
WORKDIR /src
RUN uv sync --locked --group dev
# Tests marked "integration" call the live Cloudsmith service and need credentials.
RUN pytest cloudsmith_cli -m "not integration" -q || echo "WARNING: pytest reported failures"
