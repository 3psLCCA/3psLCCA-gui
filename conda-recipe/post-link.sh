#!/bin/bash

set -e

echo "Running post-link script..."

"$PREFIX/bin/python" -m pip install --no-cache-dir pywebview

echo "Post-link completed."

exit 0