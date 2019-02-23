#!/usr/bin/env bash
self=$(readlink -f $BASH_SOURCE)
self_dir=$(dirname $self)
base_dir=$(basename $self_dir)

if [[ "${base_dir}" == py* ]]; then
  root_dir=$(readlink -f "$self_dir/../..")
  py_version=$base_dir
  pip_compile=${root_dir}/.venv/${py_version}/bin/pip-compile

  cd $self_dir
  echo "Building requirements for Python: ${py_version}"
  ${pip_compile} --output-file common.txt common.in
  ${pip_compile} --pre --output-file test.txt common.in test.in
  ${pip_compile} --pre --output-file development.txt common.in test.in development.in
else
  for py_version in py2 py3; do
    ${self_dir}/${py_version}/pip-compile.sh
  done
fi
