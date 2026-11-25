# 🤖 J.A.R.V.I.S. (Voice-Enabled Personal Assistant)

A modular, voice-enabled personal AI assistant powered by your local **Ollama** model (`qwen3.5:4b`) and **macOS** native speech synthesis.

---

## 🌟 Key Features

1. **Local & Private**: Runs 100% locally on your Mac using `qwen3.5:4b` via Ollama.
2. **Cheeky Sidekick Voice**: Speaks responses using macOS's lively **Karen** voice at 275 WPM with zero lag.
3. **Voice & Text Modes**:
   - **Voice Mode**: Press Enter and speak into your microphone.
   - **Text Mode**: Type your prompts and still hear Jarvis speak back.
   - Toggle seamlessly with `/mode`.
4. **Autonomous Tools & Live Capabilities**:
   - 🎙️ **Push-to-Talk (`Cmd+I`)**: Hold `Cmd+I` anywhere on your Mac to talk immediately without touching your terminal! Release when done speaking.
   - 🌐 **Universal Web Automation**: Executes real user commands on ANY website in Google Chrome—automatically searches inputs, clicks buttons/links, fills forms, and extracts dynamic results.
   - 🖥️ **Desktop Application Automation**: Controls native macOS apps on command—Spotify (play, pause, skip, search songs), Apple Notes (create/read), Finder (open Downloads/Desktop, reveal files), and sends keystrokes or shortcuts into active windows.
   - 👁️ **Screen Vision Intelligence**: Look at your Mac screen and diagnose code, analyze errors, or summarize open slides/windows (*"Jarvis, look at my screen"*).
   - 🟢 **Live Watcher on Any Web / App**: Stay live on ANY website or application (e.g. *"Be live on https://... until I say stop"* or *"Stay live on Slack"*). Keeps sessions active, prevents timeouts, watches for keywords/changes, and sounds a chime alert.
   - 🎓 **FFCS Live Course Sniper**: Continuously watches your college course registration portal (VTOP / FFCS) for dropped seats. Runs live in the background until you say stop, sounds a loud alert, and automatically clicks "Add/Register" the split second a seat opens!
   - 🔒 **Human-in-the-Loop Login**: If a site requires login or OTP, Jarvis pauses without terminating, asks you to log in in your browser, and resumes your task immediately once you're logged in!
   - 🎵 **YouTube in Any Browser**: Plays any requested song, artist, or video in Chrome or Safari.
   - ⏯️ **Playback Control**: Pause, resume, mute, or fullscreen YouTube videos.
   - 🔍 **Live Web Search**: Searches DuckDuckGo for real-time news, articles, and answers.
   - 📄 **Webpage Reader**: Extracts readable text from any website or URL and summarizes/answers questions on it.
   - 🔋 **System Health**: Checks battery %, CPU load, free disk space.
   - 📋 **Clipboard**: Reads whatever text or code is on your clipboard or writes to it.
   - 🔊 **Volume Control**: Adjusts your Mac's speaker volume (e.g., *"Set volume to 50%"*).
   - ⏰ **Time & Date**: Real-time clock and calendar reporting.
   - 📝 **Quick Notes**: Appends timestamped reminders to `~/Jarvis_Notes.txt`.
   - 💻 **Terminal Commands**: Runs safe shell commands on request.

---

## 🚀 Quick Start

### 1. Make sure Ollama is running
Ensure your local model is serving:
```bash
ollama run qwen3.5:4b
```

### 2. Run Jarvis
Activate the virtual environment and start Jarvis:
```bash
cd /Users/eshwarchandrams/Jarvis
./.venv/bin/python jarvis.py
```

---

## 🎙️ Interactive Commands

Inside Jarvis, you can use these shortcuts:
- `/mode` - Switch between **Voice Mode** (speech-to-text) and **Text Mode** (keyboard input).
- `/speed <wpm>` - Adjust speech speed instantly (e.g., `/speed 230` or `/speed 260`).
- `/voice <name>` - Switch voice tone instantly (e.g., `/voice Samantha`, `/voice Daniel`, `/voice Rishi`).
- `/voices` - List all popular voices available on your Mac.
- `/mute` - Mute/unmute voice speech output.
- `/status` - Display a quick diagnostic of your Mac's battery, CPU, and disk.
- `/clear` - Clear conversation memory.
- `/exit` or `quit` - Gracefully shut down Jarvis.

---

## 🛠️ How to Add Your Own Tools

Adding new abilities to Jarvis takes under 2 minutes:

1. Open [core/tools.py](file:///Users/eshwarchandrams/Jarvis/core/tools.py).
2. Write a standard Python function (e.g. `check_weather(city)` or `play_music(song)`).
3. Add the function to `TOOL_MAP`.
4. Add a JSON schema description to `TOOL_DEFINITIONS`.

Jarvis's brain (`qwen3.5:4b`) will automatically know when and how to call your new tool when you speak to it!

---

## ⚙️ Configuration

Customize persona, voice, and speed in [config.py](file:///Users/eshwarchandrams/Jarvis/config.py):
- `MODEL_NAME`: Set to any model in your Ollama library (e.g. `qwen3.5:4b`, `llama3.2`).
- `TTS_VOICE`: Change voice (default: `Karen` - Cheeky Sidekick).
- `TTS_RATE`: Adjust speech speed (default: `275` words per minute).
 