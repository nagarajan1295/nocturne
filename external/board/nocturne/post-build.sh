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

# BirdThing: buildroot's bluez5_utils ships /etc/init.d/S40bluetoothd, which
# starts a SECOND bluetoothd WITHOUT our PAN plugin. It grabs the org.bluez
# D-Bus name at boot, so the supervisord bluetoothd (start-bluetoothd, with
# --plugin=...,network) can never get on D-Bus and crash-loops -> no PAN.
# Remove the duplicate so only the network-plugin daemon runs. See bt-pan.sh.
rm -f "$TARGET_DIR"/etc/init.d/S40bluetoothd
