#!/usr/bin/env bash
# SPDX-License-Identifier: BSD-3-Clause
# Portable core/admission checks; no DPDK, SDK or physical NIC is needed.
set -euo pipefail
project_root=$(cd "$(dirname "$0")/.." && pwd)
test_build=$(mktemp -d "${TMPDIR:-/tmp}/l3-core-tests.XXXXXX")
trap 'rm -rf "$test_build"' EXIT
for component in forward options device; do
    "${CC:-cc}" -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
        -fsanitize=address,undefined -g -I"$project_root/src" \
        "$project_root/src/$component.c" "$project_root/tests/test_$component.c" \
        -o "$test_build/test-$component"
    "$test_build/test-$component"
done
"${CC:-cc}" -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror \
    -fsanitize=address,undefined -g -I"$project_root/src" \
    "$project_root/tests/test_netstate.c" -o "$test_build/test-netstate"
"$test_build/test-netstate"
