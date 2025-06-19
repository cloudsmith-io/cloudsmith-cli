FROM python:3.12-alpine

LABEL maintainer="support@cloudsmith.io"
LABEL description="Official Cloudsmith CLI, now served in a handy container"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/cloudsmith:${PATH}"

RUN apk add --no-cache curl bash ca-certificates
ARG CLOUDSMITH_CLI_VERSION

RUN mkdir -p /opt/cloudsmith \
 && curl -1sLf -o /opt/cloudsmith/cloudsmith "https://dl.cloudsmith.io/public/cloudsmith/cli-zipapp/raw/names/cloudsmith-cli/versions/${CLOUDSMITH_CLI_VERSION}/cloudsmith-${CLOUDSMITH_CLI_VERSION}.pyz" \
 && chmod +x /opt/cloudsmith/cloudsmith

# Default command
ENTRYPOINT [ "cloudsmith" ]