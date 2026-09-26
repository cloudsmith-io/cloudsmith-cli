FROM astral/uv:0.12.17-alpine3.23@sha256:05b442451c40e8f9dc315b7d388e59f1ccb095d002e9be7628608e47ea570e4c AS build

WORKDIR /root/cloudsmith-cli

RUN apk add --no-cache binutils

COPY bin bin
COPY cloudsmith_cli cloudsmith_cli
COPY packaging packaging
COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock
COPY VERSION VERSION

ARG CLOUDSMITH_CLI_VERSION
ARG PYTHON_VERSION=3.14

RUN uv sync --locked --no-dev --no-editable --group binary --extra all --python "${PYTHON_VERSION}"
RUN uv run --no-sync pyinstaller --clean --noconfirm packaging/pyinstaller/cloudsmith.spec

FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

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
