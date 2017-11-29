#!/usr/bin/env bash
self=$(readlink -f $BASH_SOURCE)
self_dir=$(dirname $self)

cd $self_dir
for I in *.in; do
    filename="${I%.*}"
    pip-compile --output-file $filename.txt $filename.in
done
