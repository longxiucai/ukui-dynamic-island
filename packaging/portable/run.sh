#!/bin/sh
# Portable launcher: no install, no root.
set -e
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$HERE/ukui-island/ukui-island" "$@"
