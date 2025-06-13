#!/bin/bash

# Activate virtual environment if not already activated
if [ -z "$VIRTUAL_ENV" ]; then
    source venv/bin/activate 2>/dev/null || echo "Virtual environment not found, continuing without it."
fi

# Set the base directory to the script's location
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create a temporary environment with explicit configuration
export CLOUDSMITH_CONFIG_HOME="${SCRIPT_DIR}"
export CLOUDSMITH_CREDENTIALS_FILE="${SCRIPT_DIR}/cloudsmith_cli/data/credentials.ini"
export CLOUDSMITH_PROFILE="jmccay"

# Print debugging information
echo "Using credentials file: ${CLOUDSMITH_CREDENTIALS_FILE}"
echo "Using profile: ${CLOUDSMITH_PROFILE}"

# Run cloudsmith CLI command with explicit paths
python3 -m cloudsmith_cli.__main__ \
    --credentials-file "${CLOUDSMITH_CREDENTIALS_FILE}" \
    --profile "${CLOUDSMITH_PROFILE}" \
    "$@"