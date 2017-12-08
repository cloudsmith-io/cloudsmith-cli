#!/usr/bin/env bash
self=$(readlink -f $BASH_SOURCE)
self_dir=$(dirname $self)
root_dir=$(readlink -f "$self_dir/..")
cloudsmith_repo_cli="cloudsmith/cli"
project="cloudsmith-cli"
package="cloudsmith_cli"
version=$(cat VERSION)

build_distribution() {
  echo "Building distribution ..."
  python setup.py clean
  python setup.py bdist_wheel --universal
}

upload_to_pypi() {
  echo "Uploading to PyPi ..."
  twine_args="\
    --skip-existing \
    dist/${package}-${version}-py2.py3-none-any.whl"
  test "$TRAVIS" == "true" && {
      echo twine upload \
        -u csm-api-bot \
        -p $PYPI_PASSWORD \
        $twine_args
  } || {
      echo twine upload $twine_args
  }
}

upload_to_cloudsmith() {
  echo "Uploading to Cloudsmith ..."
  cloudsmith_args="\
    dist/${package}-${version}-py2.py3-none-any.whl \
    --skip-errors"
  echo cloudsmith push python \
    ${cloudsmith_repo_cli} \
    ${cloudsmith_args}
}

set -e
cd $root_dir
build_distribution
upload_to_pypi
upload_to_cloudsmith
