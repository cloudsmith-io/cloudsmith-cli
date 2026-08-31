ARG ALPINE_IMAGE=alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d
ARG UV_IMAGE=astral/uv:0.12.7-alpine3.23@sha256:d0d7c7a05e4d9270b97392da2204371581b431287f2ae959e4aef715c86f9efc

FROM ${UV_IMAGE} AS build

WORKDIR /root/cloudsmith-cli

RUN apk add --no-cache binutils=2.45.1-r0

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

FROM ${ALPINE_IMAGE}

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
