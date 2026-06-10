#!/usr/bin/env bash

APP_NAME="threePSLCCA"
PREFIX="$( cd "$( dirname "$(readlink -f "$0")" )" && pwd )"

read -p "Are you sure you want to uninstall 3PS LCCA? [y/N]: " confirm
[[ "$confirm" == "y" || "$confirm" == "Y" ]] || exit 0

echo "Removing 3PS LCCA shortcuts..."

rm -f "$HOME/.local/share/applications/$APP_NAME.desktop" 2>/dev/null
rm -f "$HOME/Desktop/$APP_NAME.desktop"  2>/dev/null
rm -f "$HOME/.local/share/applications/Uninstall-$APP_NAME.desktop" 2>/dev/null


update-desktop-database ~/.local/share/applications 2>/dev/null || true

rm -rf "$PREFIX"

echo "3PS LCCA cleanup complete."
read -p "Press Enter to close this window..."