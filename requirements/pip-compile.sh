#!/usr/bin/env bash
set -eou pipefail
self=$(readlink -f $BASH_SOURCE)
self_dir=$(dirname $self)

cd $self_dir
echo "Rebuilding Python 2.x requirements"
if [ ! -d .venv/py2 ]; then
  virtualenv -p python2.7 .venv/py2
  .venv/py2/bin/pip install pip-tools
fi

.venv/py2/bin/pip-compile --pre --output-file production.py2.txt common.in
.venv/py2/bin/pip-compile --pre --output-file development.py2.txt common.in development.in test.in lint.in

echo "Rebuild Python 3.x requirements"
if [ ! -d .venv/py3 ]; then
  virtualenv -p python3 .venv/py3
  .venv/py3/bin/pip install pip-tools
fi

.venv/py3/bin/pip-compile --pre --output-file production.py3.txt common.in
.venv/py3/bin/pip-compile --pre --output-file development.py3.txt common.in development.in test.in lint.in
