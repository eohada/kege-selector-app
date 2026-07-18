#!/usr/bin/env bash
if [ ! -f tailwindcss ]; then
    echo "Downloading Tailwind CSS standalone..."
    curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
    chmod +x tailwindcss-linux-x64
    mv tailwindcss-linux-x64 tailwindcss
fi
./tailwindcss -i ./static/src/input.css -o ./static/dist/boostudy.css --minify
