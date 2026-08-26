#!/bin/sh
set -eu

REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
TARGET_DIR="$KLIPPER_DIR/klippy/extras"
TARGET="$TARGET_DIR/ms5837.py"
SOURCE="$REPO_DIR/klippy/extras/ms5837.py"

if [ ! -d "$TARGET_DIR" ]; then
    echo "Klipper extras directory not found: $TARGET_DIR"
    echo "Set KLIPPER_DIR if Klipper is installed elsewhere."
    exit 1
fi

if [ ! -f "$SOURCE" ]; then
    echo "Source file not found: $SOURCE"
    exit 1
fi

if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
    BACKUP="$TARGET.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Backing up existing file:"
    echo "  $TARGET -> $BACKUP"
    mv "$TARGET" "$BACKUP"
fi

ln -sfn "$SOURCE" "$TARGET"

echo
echo "Installed Klipper MS5837 extension:"
echo "  $TARGET -> $SOURCE"
echo
echo "Add an [ms5837 <name>] section to printer.cfg, then run RESTART."
