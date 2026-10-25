#!/bin/bash
# Builds dist/dualboot-switcher_<version>_all.deb from this checkout.
# Needs only dpkg-deb, which every Debian/Ubuntu system has.
#
# Every file in the package is owned by root (--root-owner-group) and only
# root can write it. That matters most for the helper that pkexec runs as root.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
VERSION=$(sed -nE 's/^__version__ = "(.*)"$/\1/p' "$REPO/dualboot_switcher/__init__.py")
# Debian sorts "~" before everything, so 0.1.0~rc1 comes before 0.1.0.
DEB_VERSION=${VERSION//-/\~}
OUT="$REPO/dist/dualboot-switcher_${DEB_VERSION}_all.deb"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

for file in "$REPO"/dualboot_switcher/*.py; do
    install -Dm644 "$file" "$STAGE/usr/lib/dualboot-switcher/dualboot_switcher/$(basename "$file")"
done
install -Dm755 "$REPO/packaging/linux/dualboot-switcher" "$STAGE/usr/bin/dualboot-switcher"
install -Dm755 "$REPO/packaging/linux/dualboot-switcher-helper" \
    "$STAGE/usr/libexec/dualboot-switcher/dualboot-switcher-helper"
install -Dm644 "$REPO/packaging/linux/io.github.sharkbeans.dualboot.policy" \
    "$STAGE/usr/share/polkit-1/actions/io.github.sharkbeans.dualboot.policy"
install -Dm644 "$REPO/packaging/linux/dualboot-switcher.desktop" \
    "$STAGE/usr/share/applications/dualboot-switcher.desktop"
install -Dm644 "$REPO/LICENSE" "$STAGE/usr/share/doc/dualboot-switcher/copyright"

mkdir -m755 "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: dualboot-switcher
Version: $DEB_VERSION
Architecture: all
Maintainer: sharkbeans <sharkbeans01@gmail.com>
Depends: python3 (>= 3.9), python3-tk, efibootmgr, pkexec | policykit-1
Section: admin
Priority: optional
Homepage: https://github.com/sharkbeans/dualboot
Description: restart a UEFI dual-boot PC straight into the other OS
 Dual Boot Switcher sets a one-time UEFI boot entry (BootNext) for the
 other operating system and restarts, skipping the boot menu. The
 permanent boot order is never changed.
EOF
chmod 644 "$STAGE/DEBIAN/control"

# install -D creates parent directories with the current umask; normalize them.
find "$STAGE" -type d -exec chmod 755 {} +

mkdir -p "$REPO/dist"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "Built $OUT"
