#!/bin/bash
# foamy-train's own tests; tests/validate.sh runs this after the linters.
#   --ci    no Quickshell, no Omarchy host: node, and the helper against the
#           local fake Entur (bin/x86_64; bin/aarch64 too where binfmt runs it)
#   --fast  skip the offscreen runtime tests
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." || exit 1
ci=0 fast=0
for arg in "$@"; do
  case $arg in
    --ci) ci=1 ;;
    --fast) fast=1 ;;
    *)
      echo "suite.sh: unknown argument $arg" >&2
      exit 2
      ;;
  esac
done
status=0
run() {
  echo "== $*"
  "$@" || status=1
}
skip() { echo "SKIP $*"; }

run node --test tests/*.test.cjs
run python3 -m unittest discover -s tests -p 'test_*.py'
# The aarch64 helper runs through a registered qemu binfmt handler; a crash
# under emulation must not leave a core file in the tree.
if [[ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]]; then
  (
    ulimit -c 0
    export FOAMY_HELPER='["bin/aarch64/foamy-train-helper"]'
    run python3 -m unittest discover -s tests -p 'test_*.py'
    exit $status
  ) || status=1
else
  skip "the aarch64 helper: no qemu-aarch64 binfmt handler"
fi
if ((ci || fast)); then
  skip "the kit's i18n_runtime.py, tests/runtime.py and tests/cursor.py: offscreen Quickshell"
else
  kit=${FOAMY_KIT:-$HOME/GitHub/Personal/foamy-kit}
  run python3 "$kit/preview/i18n_runtime.py" .
  run python3 tests/runtime.py
  run python3 tests/cursor.py
fi
exit $status
