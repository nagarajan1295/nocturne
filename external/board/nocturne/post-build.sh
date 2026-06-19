#!/usr/bin/env bash
set -ex

TARGET_DIR="$1"

git_hash=$(git -C .. rev-parse HEAD)
build_date=$(date +%Y-%m-%d-%H-%M-%S)

sed -i "s|\${GIT_HASH}|${git_hash}|g" "$TARGET_DIR"/etc/nocturne/version.json
sed -i "s|\${BUILD_DATE}|${build_date}|g" "$TARGET_DIR"/etc/nocturne/version.json

version=$(jq -r '.shortVersion' "$TARGET_DIR"/etc/nocturne/version.json)

sed -i "s|\${VERSION}|${version}|g" "$TARGET_DIR"/etc/motd
sed -i "s|\${GIT_HASH}|${git_hash}|g" "$TARGET_DIR"/etc/motd

sed -i "s|\${NOCTURNE_VERSION}|${version}|g" "$TARGET_DIR"/etc/fastfetch/config.jsonc

# BirdThing: dropbear-acceptable perms on root's baked SSH key.
# (No chown: post-build runs unprivileged; Buildroot's fakeroot image step
# makes target files root:root anyway.)
if [ -f "$TARGET_DIR"/root/.ssh/authorized_keys ]; then
  chmod 700 "$TARGET_DIR"/root/.ssh
  chmod 600 "$TARGET_DIR"/root/.ssh/authorized_keys
fi
