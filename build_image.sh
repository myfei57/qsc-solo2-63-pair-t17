#!/bin/sh
# Build the control service image for both supported architectures.
set -eu

image="${1:-line-control-service:local}"
root="$(cd "$(dirname "$0")" && pwd)"

docker buildx build --platform linux/amd64,linux/arm64 -t "$image" --push "$root"
