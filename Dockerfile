ARG ALPINE_IMAGE=alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d

FROM astral/uv:alpine AS build

WORKDIR /root/cloudsmith-cli

RUN apk add binutils

COPY VERSION VERSION
RUN export CLOUDSMITH_CLI_VERSION=$(cat VERSION)

ARG TARGETARCH=x86_64

COPY pyproject.toml pyproject.toml
COPY uv.lock uv.lock

RUN uv sync --locked --no-dev --no-editable --group binary --extra all --python "${PYTHON_VERSION}"

COPY packaging/ packaging/
COPY cloudsmith_cli/ cloudsmith_cli/
RUN uv run --no-sync pyinstaller --clean --noconfirm packaging/pyinstaller/cloudsmith.spec

# RUN sha256sum -c "${ARCHIVE}.sha256"
# RUN tar -xzf "${ARCHIVE}" -C /opt

FROM ${ALPINE_IMAGE}

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

COPY --from=build /opt/cloudsmith /opt/cloudsmith

RUN adduser -D -u 1000 cloudsmith
USER cloudsmith

ENTRYPOINT ["cloudsmith"]
