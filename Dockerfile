ARG ALPINE_IMAGE=alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d

FROM ${ALPINE_IMAGE} AS unpack

ARG TARGETARCH
ARG CLOUDSMITH_CLI_VERSION

COPY binaries/ /tmp/binaries/

RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) CS_ARCH="x86_64" ;; \
      arm64) CS_ARCH="aarch64" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    ARCHIVE="cloudsmith-${CLOUDSMITH_CLI_VERSION}-linux-${CS_ARCH}-musl.tar.gz"; \
    cd /tmp/binaries; \
    sha256sum -c "${ARCHIVE}.sha256"; \
    mkdir -p /opt; \
    tar -xzf "${ARCHIVE}" -C /opt

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

COPY --from=unpack /opt/cloudsmith /opt/cloudsmith

RUN adduser -D -u 1000 cloudsmith
USER cloudsmith

ENTRYPOINT ["cloudsmith"]
