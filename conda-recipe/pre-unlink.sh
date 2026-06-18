#!/bin/bash

set -e

echo "Running pre-unlink script..."

"$PREFIX/bin/python" -m pip uninstall --no-cache-dir pywebview -y

echo "Pre-Unlink completed."

exit 0