#!/bin/sh
set -eu

KLIPPER_DIR="${KLIPPER_DIR:-$HOME/klipper}"
TARGET="$KLIPPER_DIR/klippy/extras/ms5837.py"

if [ -L "$TARGET" ]; then
    rm "$TARGET"
    echo "Removed symlink: $TARGET"
elif [ -e "$TARGET" ]; then
    echo "Not removing $TARGET because it is not a symlink."
    echo "Remove it manually if you are sure it belongs to this project."
else
    echo "MS5837 extension is not installed at $TARGET"
fi
