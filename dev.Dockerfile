FROM astral/uv:0.13.8-alpine3.23@sha256:d436fa324e71ef7c8accd7902e893d18a19a0e3afb3ecf57626d696d982137e5 AS build

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

FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf

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
