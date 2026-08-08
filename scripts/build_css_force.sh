#!/usr/bin/env bash

# Hardcoded absolute paths to make absolutely sure
INPUT_CSS="/run/media/eohada/Main/projects/kege_selector_app_current/static/src/input.css"
OUTPUT_CSS="/run/media/eohada/Main/projects/kege_selector_app_current/static/dist/boostudy.css"

echo "Checking tailwind binary..."
if [ ! -f ./tailwindcss ]; then
    echo "Downloading Tailwind..."
    curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
    chmod +x tailwindcss-linux-x64
    mv tailwindcss-linux-x64 tailwindcss
fi

echo "Running Tailwind compiler..."
./tailwindcss -i $INPUT_CSS -o $OUTPUT_CSS

echo "Done!"
