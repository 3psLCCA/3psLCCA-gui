#!/usr/bin/env bash

set -e

APP_NAME="threePSLCCA"
INSTALL_DIR="$PREFIX"

launch_shortcut="$HOME/.local/share/applications/$APP_NAME.desktop"
uninstall_shortcut="$HOME/.local/share/applications/Uninstall-$APP_NAME.desktop"
ICON_FILE="$INSTALL_DIR/logo-3psLCCA.ico"
LAUNCHER="$INSTALL_DIR/bin/$APP_NAME"
UNINSTALLER="$INSTALL_DIR/Uninstall-lcca-gui.sh"

echo "Creating application launcher..."

mkdir -p "$HOME/.local/share/applications"

cat <<EOF > "$launch_shortcut"
[Desktop Entry]
Name=$APP_NAME
Exec=$LAUNCHER
Icon=$ICON_FILE
Type=Application
Categories=Engineering;
Terminal=false
EOF

chmod +x "$launch_shortcut"

echo "Launcher created at:"
echo "$launch_shortcut"

echo "Creating application Uninstaller..."

cat <<EOF > "$uninstall_shortcut"
[Desktop Entry]
Name=Uninstall $PP_NAME
Exec=$UNINSTALLER
Icon=$ICON_FILE
Type=Application
Categories=Engineering;
Terminal=true
EOF

chmod +x "$UNINSTALLER"
chmod +x "$uninstall_shortcut"

update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "Uninstaller created at:"
echo "$uninstall_shortcut"