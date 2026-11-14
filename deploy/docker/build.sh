#!/usr/bin/env bash
# Obraz linux/amd64 dla wormera, otagowany commitem (nie :local, bo to alias z compose).
set -euo pipefail
cd "$(dirname "$0")/../.."
rev=$(git rev-parse HEAD); tag=$(git rev-parse --short HEAD)
[[ -z $(git status --porcelain) ]] || tag="$tag-dirty"
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile \
    --build-arg REVISION="$rev" -t "garmin-dashboard:$tag" --load .
echo "garmin-dashboard:$tag"
