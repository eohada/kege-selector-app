#!/bin/bash
# 1. Compile Tailwind CSS
if command -v npm &> /dev/null; then
    npx tailwindcss -i ./static/src/input.css -o ./static/dist/boostudy.css --minify
elif [ -f tailwindcss ]; then
    ./tailwindcss -i ./static/src/input.css -o ./static/dist/boostudy.css --minify
else
    echo "Downloading Tailwind CSS standalone..."
    curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
    chmod +x tailwindcss-linux-x64
    mv tailwindcss-linux-x64 tailwindcss
    ./tailwindcss -i ./static/src/input.css -o ./static/dist/boostudy.css --minify
fi

# 2. Kill old server instances to prevent port conflicts
killall -9 python3 python run_local.py 2>/dev/null || true

# 3. Start server
source venv_linux/bin/activate && python3 scripts/run_local.py > logs/local_server.log 2>&1 &
