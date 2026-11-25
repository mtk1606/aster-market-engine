#!/usr/bin/env bash
# Write one complete replay and analysis receipt. Keep it under ignored data/.
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "Usage: $0 ASTER_REPLAY INPUT_ITCH_OR_GZ OUTPUT_JSON" >&2
    exit 2
fi

binary=$1
input=$2
output=$3
if [[ ! -x "$binary" || ! -r "$input" ]]; then
    echo "Aster binary must be executable and the input must be readable." >&2
    exit 2
fi

temporary=$(mktemp -- "${output}.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
flags=(--io read --chunk 1048576 --complete --validate --price-jumps)

if [[ "$input" == *.gz ]]; then
    gzip -dc -- "$input" | "$binary" /dev/stdin "${flags[@]}" > "$temporary"
else
    "$binary" "$input" "${flags[@]}" > "$temporary"
fi

mv -f -- "$temporary" "$output"
