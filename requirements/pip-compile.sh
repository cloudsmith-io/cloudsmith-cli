#!/usr/bin/env bash
self=$(readlink -f $BASH_SOURCE)
self_dir=$(dirname $self)

cd $self_dir
pip-compile --output-file common.txt common.in
pip-compile --output-file test.txt common.in test.in
pip-compile --output-file development.txt common.in test.in development.in
