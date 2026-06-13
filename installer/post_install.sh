#!/usr/bin/env bash

set -e

APP_NAME="threePSLCCA"
INSTALL_DIR="$PREFIX"

launch_shortcut="$HOME/.local/share/applications/$APP_NAME.desktop"
uninstall_shortcut="$HOME/.local/share/applications/Uninstall-$APP_NAME.desktop"
ICON_FILE="$INSTALL_DIR/logo-3psLCCA.png"
LAUNCHER="$INSTALL_DIR/bin/$APP_NAME"
UNINSTALLER="$INSTALL_DIR/Uninstall-lcca-gui.sh"
[ -f "$LAUNCHER" ] || echo "Launcher not found: $LAUNCHER"
[ -f "$UNINSTALLER" ] || echo "Uninstaller not found: $UNINSTALLER"

echo "Creating application launcher..."

mkdir -p "$HOME/.local/share/applications"

cat <<EOF > "$launch_shortcut"
[Desktop Entry]
Name=$APP_NAME
Exec=$LAUNCHER
Icon=$ICON_FILE
Type=Application
Categories=Science;Education;
Terminal=false
EOF

chmod +x "$launch_shortcut"

echo "Launcher created at:"
echo "$launch_shortcut"

echo "Creating application Uninstaller..."
if [ -f "$UNINSTALLER" ]; then
    chmod +x "$UNINSTALLER"

    cat <<EOF > "$uninstall_shortcut"
[Desktop Entry]
Name=Uninstall $APP_NAME
Exec=$UNINSTALLER
Icon=$ICON_FILE
Type=Application
Categories=Science;Education;
Terminal=true
EOF

    chmod +x "$uninstall_shortcut"
fi

update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "Uninstaller created at:"
echo "$uninstall_shortcut"