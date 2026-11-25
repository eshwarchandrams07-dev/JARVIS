#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — One-tap Jarvis launcher
# Starts Ollama (if not already running), waits for it to be ready, then
# launches Jarvis inside the project virtual environment.
# Usage: ./start.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "🤖 Starting Jarvis..."

# ── 1. Ensure Ollama is running ───────────────────────────────────────────────
if ! pgrep -x "ollama" > /dev/null 2>&1; then
    echo "⚙  Ollama not running — starting it in the background..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    echo "   Waiting for Ollama to be ready..."
    for i in $(seq 1 15); do
        sleep 1
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "   ✅ Ollama is ready."
            break
        fi
        if [ "$i" -eq 15 ]; then
            echo "   ⚠  Ollama didn't respond in 15s — continuing anyway."
        fi
    done
else
    echo "   ✅ Ollama already running."
fi

# ── 2. Pull the model if missing ──────────────────────────────────────────────
if ! ollama list 2>/dev/null | grep -q "qwen3.5:4b"; then
    echo "📥  Pulling qwen3.5:4b model (first-time only)..."
    ollama pull qwen3.5:4b
fi

# ── 3. Launch Jarvis ─────────────────────────────────────────────────────────
echo "🚀  Launching Jarvis..."
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/jarvis.py"
