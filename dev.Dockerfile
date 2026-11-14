FROM astral/uv:0.13.7-alpine3.23@sha256:a788290ce829958f18bcea1dfd9fb5dcf4bfb22f6380b52c9322f9d91e86b117 AS build

WORKDIR /root/cloudsmith-cli

RUN apk add --no-cache binutils

ARG PYTHON_VERSION=3.14.10

# Install dependencies before copying the source, so the layer is reused until
# pyproject.toml or uv.lock change.
COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock
RUN uv sync --locked --no-dev --no-editable --group binary --extra all --python "${PYTHON_VERSION}" --no-install-project

COPY bin bin
COPY cloudsmith_cli cloudsmith_cli
COPY packaging packaging
COPY VERSION VERSION

ARG CLOUDSMITH_CLI_VERSION

RUN uv sync --locked --no-dev --no-editable --group binary --extra all --python "${PYTHON_VERSION}"
RUN uv run --no-sync pyinstaller --clean --noconfirm packaging/pyinstaller/cloudsmith.spec

FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

COPY --from=build /root/cloudsmith-cli/dist/cloudsmith /opt/cloudsmith

ARG CLOUDSMITH_CLI_VERSION
ARG VCS_REF

LABEL maintainer="support@cloudsmith.io" \
    org.opencontainers.image.title="Cloudsmith CLI" \
    org.opencontainers.image.description="Official Cloudsmith CLI" \
    org.opencontainers.image.vendor="Cloudsmith" \
    org.opencontainers.image.url="https://cloudsmith.com" \
    org.opencontainers.image.source="https://github.com/cloudsmith-io/cloudsmith-cli" \
    org.opencontainers.image.documentation="https://docs.cloudsmith.com/developer-tools/cli" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.version="${CLOUDSMITH_CLI_VERSION}" \
    org.opencontainers.image.revision="${VCS_REF}"

ENV PATH="/opt/cloudsmith:${PATH}"

RUN adduser -D -u 1000 cloudsmith
USER cloudsmith

ENTRYPOINT ["cloudsmith"]
