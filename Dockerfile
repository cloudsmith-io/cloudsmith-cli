FROM python:3.12-alpine

LABEL maintainer="support@cloudsmith.io"
LABEL description="Official Cloudsmith CLI, now served in a handy container"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/cloudsmith:${PATH}"

RUN apk add --no-cache curl bash

RUN mkdir -p /opt/cloudsmith \
 && curl -1sLf -o /opt/cloudsmith/cloudsmith 'https://dl.cloudsmith.io/public/cloudsmith/cli-zipapp/raw/names/cloudsmith-cli/versions/latest/cloudsmith-latest.pyz' \
 && chmod +x /opt/cloudsmith/cloudsmith

# Default command
CMD ["/bin/sh"]