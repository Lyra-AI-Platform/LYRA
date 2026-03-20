<div align="center">

# ✦ Lyra

### Your Private, Intelligent AI — Runs Entirely on Your Machine

[![License: Lyra Community License](https://img.shields.io/badge/License-Lyra%20Community%20License%20v1.0-blueviolet.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Platform: Windows | Mac | Linux](https://img.shields.io/badge/Platform-Windows%20%7C%20Mac%20%7C%20Linux-lightgrey.svg)](#)

**No subscriptions. No data leaving your machine. No limits.**

[Quick Start](#quick-start) · [Features](#features) · [Models](#models) · [Privacy](#privacy) · [License](#license)

</div>

---

## What is Lyra?

Lyra is a full-featured personal AI platform you run on your own computer. It combines:

- A **beautiful chat interface** (accessible in your browser at `http://localhost:7860`)
- **Multiple open-source AI models** — download any GGUF or HuggingFace model
- **Five built-in AI personas** optimized for different tasks
- **Autonomous self-learning** — Lyra crawls the web on its own to get smarter
- **Long-term memory** — remembers your conversations across sessions
- **File analysis** — upload PDFs, code, spreadsheets, images
- **Web search** — real-time DuckDuckGo integration
- **Opt-in Collective Intelligence** — anonymously share topic trends to help everyone

---

## Quick Start

```bash
# Linux / macOS
git clone https://github.com/your-username/lyra
cd lyra
./scripts/install.sh
./scripts/start.sh

# Windows
git clone https://github.com/your-username/lyra
cd lyra
scripts\install.bat
scripts\start.bat

# Then open:
# http://localhost:7860
```

---

## Features

| Feature | Details |
|---------|---------|
| **Chat UI** | Dark, modern interface with streaming responses, markdown, code highlighting |
| **5 AI Personas** | Lyra · Lyra-Code · Lyra-Research · Lyra-Create · Lyra-Web |
| **Any Open Model** | Download Mistral, Llama 3, DeepSeek, Qwen, Phi-3 or any GGUF model |
| **Model Manager** | Built-in downloader with progress — no command line needed |
| **Long Context** | 8K–128K tokens depending on model |
| **File Analysis** | PDF · Word · Excel · CSV · Code · Images |
| **Memory** | ChromaDB vector database — Lyra remembers across all sessions |
| **Auto-Learning** | Crawls Wikipedia, web, RSS feeds autonomously in the background |
| **Web Search** | DuckDuckGo, no API key required |
| **100% Offline** | After setup, zero internet required (web search is optional) |
| **GPU Support** | Auto-detects CUDA for GPU acceleration |
| **Collective Intelligence** | Opt-in: share anonymous topic keywords to help the community |

---

## Models

Lyra ships with a built-in model downloader. Recommended models:

| Model | Size | RAM | Best For |
|-------|------|-----|---------|
| **Mistral 7B Instruct Q4** | 4.4 GB | 8 GB | General chat — fast, smart |
| **Llama 3 8B Instruct Q4** | 4.9 GB | 8 GB | Reasoning, instruction-following |
| **DeepSeek R1 7B Q4** | 4.7 GB | 8 GB | Coding, logic |
| **Qwen 2.5 7B Q4** | 4.7 GB | 8 GB | Multilingual, coding |
| **Phi-3 Mini Q4** | 2.2 GB | 4 GB | Low-RAM devices |
| **Llama 3 70B Q4** | 40 GB | 48 GB | Maximum intelligence |

You can also download any GGUF model from a custom URL directly in the UI.

---

## Lyra's AI Personas

Switch between these built-in intelligences from the sidebar:

| Persona | Icon | Best For |
|---------|------|---------|
| **Lyra** | ✦ | General — balanced, thoughtful, all-purpose |
| **Lyra-Code** | ⟨/⟩ | Programming — clean, complete, production-ready code |
| **Lyra-Research** | ◎ | Analysis — documents, papers, data, research |
| **Lyra-Create** | ✸ | Writing — stories, copy, ideation, creative work |
| **Lyra-Web** | ⊕ | Search — real-time web research with citations |

---

## Privacy

**Lyra is private by design.**

- ✅ Runs entirely on your machine
- ✅ Conversations never leave your device (by default)
- ✅ Files you upload stay local
- ✅ Memory stored locally in ChromaDB

### Collective Intelligence (Opt-In)

When you choose to opt in, Lyra shares **only anonymous topic keywords** (e.g., "machine learning", "python") with a community server. In return, you receive trending topics the community is interested in, which Lyra pre-learns.

What is **never** shared, even with opt-in:
- ❌ Your messages or AI responses
- ❌ File contents
- ❌ Your IP address
- ❌ Your name, email, or any personal information

You can opt out at any time. All local telemetry data is immediately deleted.

→ **[Read the full Privacy Policy](PRIVACY_POLICY.md)**

---

## Self-Hosting the Community Server

If you want to run your own collective intelligence server:

```bash
cd server/
pip install fastapi uvicorn
uvicorn community_server:app --host 0.0.0.0 --port 8000
```

Deploy free on [Railway](https://railway.app), [Render](https://render.com), or [Fly.io](https://fly.io).

Then point Lyra at your server in Settings → Privacy → Collective Intelligence.

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 8 GB | 16 GB+ |
| Storage | 10 GB free | 50 GB+ |
| Python | 3.10+ | 3.11+ |
| GPU | Not required | CUDA GPU (10x faster) |
| OS | Windows 10+, macOS 12+, Ubuntu 20.04+ | — |

---

## License

Lyra is released under the **[Lyra Community License v1.0](LICENSE)**.

**In plain terms:**
- ✅ You can download and use Lyra for personal use
- ✅ You can view the source code
- ❌ You cannot modify the source code
- ❌ You cannot redistribute or rebrand Lyra
- ❌ You cannot use Lyra commercially without permission
- ✅ You must credit "Lyra AI" in any reference to the software

For commercial licensing or partnerships: [your-email@example.com]

---

## Credits

**Lyra AI Platform**
Copyright (C) 2026 Lyra Contributors. All rights reserved.

Built with: FastAPI · llama-cpp-python · ChromaDB · Transformers · DuckDuckGo Search

---

<div align="center">
<sub>✦ Lyra — Intelligence that's truly yours.</sub>
</div>
