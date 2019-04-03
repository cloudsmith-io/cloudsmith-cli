FROM python:3.6-alpine

# Install Python dependencies from PyPI
WORKDIR /opt/csm/requirements/
COPY requirements/development.py3.txt ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache --force-reinstall --ignore-installed -r development.txt

# Don't write .pyc files (or __pycache__ dirs) inside the container
ENV PYTHONDONTWRITEBYTECODE 1

# Copy application source code into container
WORKDIR /usr/src/app
COPY . .

CMD [ "bash" ]
