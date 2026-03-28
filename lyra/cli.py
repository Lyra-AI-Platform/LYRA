"""
Lyra AI Platform — Terminal CLI
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Full-featured terminal interface for Lyra.
No browser needed — runs directly in your terminal.

Usage:
    python -m lyra.cli                  # auto-connects or starts server
    python -m lyra.cli --direct         # load model directly (no server)
    python -m lyra.cli --host localhost --port 7860
    lyra-cli                            # if installed via scripts/

Slash commands:
    /help          show commands
    /status        show system status
    /model <id>    switch persona (lyra, lyra-code, lyra-research, lyra-create, lyra-web)
    /memory        show memory stats
    /cognition     show autonomous cognition stats
    /web           toggle web search
    /clear         clear conversation
    /save          save conversation to file
    /quit  /exit   exit
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Try to import rich for beautiful output ──
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.live import Live
    from rich.spinner import Spinner
    from rich import print as rprint
    RICH = True
except ImportError:
    RICH = False

ROOT = Path(__file__).parent.parent

# ── ANSI colors (fallback when rich not installed) ──
class _C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[96m"
    PURPLE  = "\033[95m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"

PERSONA_COLORS = {
    "lyra":          (_C.PURPLE,  "✦"),
    "lyra-code":     (_C.GREEN,   "⟨/⟩"),
    "lyra-research": (_C.YELLOW,  "◎"),
    "lyra-create":   (_C.CYAN,    "✸"),
    "lyra-web":      (_C.BLUE,    "⊕"),
}

BANNER = r"""
  ██╗  ██╗   ██╗██████╗  █████╗
  ██║  ╚██╗ ██╔╝██╔══██╗██╔══██╗
  ██║   ╚████╔╝ ██████╔╝███████║
  ██║    ╚██╔╝  ██╔══██╗██╔══██║
  ███████╗██║   ██║  ██║██║  ██║
  ╚══════╝╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝
"""

COMMANDS = {
    "/help":       "Show this help",
    "/status":     "System status (model, memory, cognition, learning)",
    "/model <id>": "Switch persona: lyra | lyra-code | lyra-research | lyra-create | lyra-web",
    "/memory":     "Memory statistics",
    "/cognition":  "Autonomous cognition stats + recent self-questions",
    "/web":        "Toggle web search on/off",
    "/clear":      "Clear conversation history",
    "/save":       "Save conversation to file",
    "/quit":       "Exit Lyra CLI",
}


# ════════════════════════════════════════════════════════════
#  DISPLAY HELPERS
# ════════════════════════════════════════════════════════════

def _c(color: str, text: str) -> str:
    """Wrap text in ANSI color."""
    return f"{color}{text}{_C.RESET}"


def print_banner(model_name: str = "", memory_count: int = 0, cognition_answered: int = 0):
    if RICH:
        console = Console()
        console.print(f"[bold magenta]{BANNER}[/]")
        console.print(Panel(
            f"[bold white]Personal AI · v2.0[/]\n"
            f"[dim]Model:[/] [green]{model_name or 'none loaded'}[/]  "
            f"[dim]Memory:[/] [cyan]{memory_count} facts[/]  "
            f"[dim]Cognition:[/] [yellow]{cognition_answered} self-questions answered[/]",
            border_style="magenta",
            padding=(0, 2),
        ))
        console.print(
            "[dim]Type [/][bold]/help[/][dim] for commands · [/]"
            "[bold]Ctrl+C[/][dim] or [/][bold]/quit[/][dim] to exit[/]\n"
        )
    else:
        print(_c(_C.PURPLE, BANNER))
        print(_c(_C.BOLD, f"  Lyra AI  ·  Personal AI  ·  v2.0"))
        if model_name:
            print(f"  Model: {_c(_C.GREEN, model_name)}  "
                  f"Memory: {_c(_C.CYAN, str(memory_count))} facts  "
                  f"Cognition: {_c(_C.YELLOW, str(cognition_answered))} Q&As")
        print(f"  {_c(_C.GRAY, 'Type /help for commands · Ctrl+C or /quit to exit')}\n")


def print_user_prompt(persona_id: str = "lyra"):
    color, icon = PERSONA_COLORS.get(persona_id, (_C.WHITE, "✦"))
    if RICH:
        Console().print(f"\n[bold {_persona_rich_color(persona_id)}]{icon} Lyra[/] ", end="")
    else:
        sys.stdout.write(f"\n{color}{icon} Lyra{_C.RESET}  ")
        sys.stdout.flush()


def _persona_rich_color(pid: str) -> str:
    m = {"lyra": "magenta", "lyra-code": "green", "lyra-research": "yellow",
         "lyra-create": "cyan", "lyra-web": "blue"}
    return m.get(pid, "white")


def stream_token(token: str):
    """Write a streaming token to stdout immediately."""
    sys.stdout.write(token)
    sys.stdout.flush()


def print_system(msg: str):
    if RICH:
        Console().print(f"[dim italic]{msg}[/]")
    else:
        print(_c(_C.GRAY, f"  {msg}"))


def print_error(msg: str):
    if RICH:
        Console().print(f"[bold red]Error:[/] {msg}")
    else:
        print(_c(_C.RED, f"  Error: {msg}"))


def print_help():
    if RICH:
        console = Console()
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="bold cyan", width=20)
        t.add_column(style="dim")
        for cmd, desc in COMMANDS.items():
            t.add_row(cmd, desc)
        console.print(Panel(t, title="[bold]Commands[/]", border_style="cyan"))
    else:
        print(f"\n{_c(_C.CYAN, _C.BOLD + '  Commands:')}")
        for cmd, desc in COMMANDS.items():
            print(f"  {_c(_C.CYAN, cmd):<30} {_c(_C.GRAY, desc)}")
        print()


def print_status(status: dict):
    if RICH:
        console = Console()
        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="dim", width=24)
        t.add_column(style="bold white")
        for k, v in status.items():
            t.add_row(str(k).replace("_", " ").title(), str(v))
        console.print(Panel(t, title="[bold]System Status[/]", border_style="blue"))
    else:
        print(f"\n{_c(_C.BLUE, _C.BOLD + '  System Status:')}")
        for k, v in status.items():
            print(f"  {_c(_C.GRAY, k):<28} {v}")
        print()


# ════════════════════════════════════════════════════════════
#  DIRECT MODE — loads model directly without server
# ════════════════════════════════════════════════════════════

class DirectLyraSession:
    """
    Runs Lyra completely standalone — no server process needed.
    Imports and uses the same core modules the server uses.
    """

    def __init__(self):
        self.persona_id = "lyra"
        self.conversation = []
        self.use_web = False
        self.conv_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self._initialized = False

    def _init(self):
        if self._initialized:
            return
        print_system("Loading Lyra systems...")
        # Add repo root to path
        sys.path.insert(0, str(ROOT))
        self._initialized = True

    def _get_model_name(self) -> str:
        try:
            from lyra.core.engine import engine
            return engine.loaded_model_name or "none"
        except Exception:
            return "none"

    def _get_memory_count(self) -> int:
        try:
            from lyra.memory.vector_memory import memory
            return memory.get_stats().get("count", 0)
        except Exception:
            return 0

    def _get_cognition_count(self) -> int:
        try:
            from lyra.core.cognition_engine import cognition_engine
            return cognition_engine.questions_answered
        except Exception:
            return 0

    async def start(self):
        self._init()

        # Start background tasks
        try:
            from lyra.core.auto_learner import auto_learner
            auto_learner.start()
            from lyra.core.synthesis_engine import synthesizer
            synthesizer.start()
            from lyra.core.cognition_engine import cognition_engine
            cognition_engine.start()
        except Exception as e:
            print_system(f"Background systems: {e}")

        # Check for available models
        try:
            from lyra.core.engine import engine
            models = engine.get_available_models()
            if models and not engine.loaded_model:
                print_system(f"Available model: {models[0]['name']}")
                print_system(f"Loading {models[0]['name']}...")
                result = await engine.load_model(models[0]["name"])
                if result.get("status") in ("loaded", "already_loaded"):
                    print_system(f"Model ready: {models[0]['name']}")
                else:
                    print_error(f"Model load failed: {result.get('message', 'unknown')}")
            elif not models:
                print_system("No models found in data/models/. Use the web UI to download one first.")
        except Exception as e:
            print_error(f"Model check failed: {e}")

        print_banner(
            self._get_model_name(),
            self._get_memory_count(),
            self._get_cognition_count(),
        )
        await self._chat_loop()

    async def _chat_loop(self):
        from lyra.core.engine import engine
        from lyra.memory.vector_memory import memory
        from lyra.models.lyra_models import get_model
        from lyra.core.auto_learner import auto_learner
        from lyra.core.reasoning_engine import reasoning_engine
        from lyra.core.reflection import reflector

        color, icon = PERSONA_COLORS.get(self.persona_id, (_C.WHITE, "✦"))

        while True:
            # User input prompt
            try:
                if RICH:
                    Console().print(f"\n[bold cyan]You:[/] ", end="")
                else:
                    sys.stdout.write(f"\n{_c(_C.CYAN, _C.BOLD + 'You:')} ")
                    sys.stdout.flush()

                user_input = input().strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{_c(_C.GRAY, 'Goodbye.')}")
                break

            if not user_input:
                continue

            # ── Slash commands ──
            if user_input.startswith("/"):
                await self._handle_command(user_input)
                continue

            # ── Feed to learner ──
            auto_learner.observe_message("user", user_input)

            # ── Build context ──
            lyra_model = get_model(self.persona_id)
            system_prompt = lyra_model["system_prompt"]

            # Reasoning engine enrichment
            try:
                reasoning = await reasoning_engine.build_enhanced_context(user_input)
                if reasoning.enhanced_context:
                    system_prompt += "\n\n" + reasoning.enhanced_context
            except Exception:
                pass

            # Memory injection
            try:
                ctx = memory.get_context_for_prompt(user_input)
                if ctx:
                    system_prompt += f"\n\n{ctx}"

                learned = memory.retrieve(user_input, n_results=3, memory_type="learned_knowledge")
                if learned:
                    lines = ["\n[LEARNED KNOWLEDGE:]"]
                    for item in learned[:2]:
                        lines.append(f"• {item['content'][:350]}")
                    system_prompt += "\n".join(lines)

                wisdom = memory.retrieve(user_input, n_results=2, memory_type="synthesized_wisdom")
                if wisdom:
                    lines = ["\n[SYNTHESIZED WISDOM:]"]
                    for item in wisdom[:1]:
                        lines.append(f"★ {item['content'][:350]}")
                    system_prompt += "\n".join(lines)

                # Reasoning templates
                template_ctx = await reflector.get_template_context(user_input)
                if template_ctx:
                    system_prompt += template_ctx
            except Exception:
                pass

            # Web search
            if self.use_web:
                try:
                    from lyra.search.web_search import search
                    print_system("Searching the web...")
                    results = await search.search(user_input, max_results=4)
                    if results:
                        system_prompt += "\n\n" + search.format_for_prompt(results)
                except Exception:
                    pass

            # ── Add to conversation ──
            self.conversation.append({"role": "user", "content": user_input})

            # ── Stream response ──
            print_user_prompt(self.persona_id)

            full_response = ""
            if not engine.loaded_model:
                print_error("No model loaded. Use the web UI to download and load a model.")
                self.conversation.pop()
                continue

            try:
                async for token in engine.generate(
                    messages=self.conversation,
                    system_prompt=system_prompt,
                    max_tokens=lyra_model.get("max_tokens", 2048),
                    temperature=lyra_model.get("temperature", 0.7),
                    stream=True,
                ):
                    stream_token(token)
                    full_response += token

            except Exception as e:
                print_error(f"Generation failed: {e}")
                self.conversation.pop()
                continue

            print()  # newline after streaming ends

            # ── Store response ──
            self.conversation.append({"role": "assistant", "content": full_response})
            auto_learner.observe_exchange(user_input, full_response)

            try:
                from lyra.api.chat import _store_memory_async
                asyncio.create_task(
                    _store_memory_async(user_input, full_response, self.conv_id)
                )
                asyncio.create_task(
                    reflector.evaluate_async(user_input, full_response, self.conv_id)
                )
            except Exception:
                pass

    async def _handle_command(self, cmd: str):
        parts = cmd.strip().split(maxsplit=1)
        base = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if base in ("/quit", "/exit", "/q"):
            print(_c(_C.GRAY, "\nGoodbye."))
            sys.exit(0)

        elif base == "/help":
            print_help()

        elif base == "/clear":
            self.conversation.clear()
            print_system("Conversation cleared.")

        elif base == "/model":
            valid = ["lyra", "lyra-code", "lyra-research", "lyra-create", "lyra-web"]
            if arg in valid:
                self.persona_id = arg
                color, icon = PERSONA_COLORS.get(arg, (_C.WHITE, "✦"))
                print_system(f"Switched to {icon} {arg}")
            elif not arg:
                print_system(f"Current persona: {self.persona_id}")
                print_system("Available: " + " | ".join(valid))
            else:
                print_error(f"Unknown persona: {arg}. Available: {' | '.join(valid)}")

        elif base == "/web":
            self.use_web = not self.use_web
            print_system(f"Web search: {'ON' if self.use_web else 'OFF'}")

        elif base == "/status":
            try:
                from lyra.core.engine import engine
                from lyra.memory.vector_memory import memory
                from lyra.core.auto_learner import auto_learner
                from lyra.core.synthesis_engine import synthesizer
                from lyra.core.cognition_engine import cognition_engine
                stats = {
                    "Model": engine.loaded_model_name or "none",
                    "Persona": self.persona_id,
                    "Web Search": "on" if self.use_web else "off",
                    "Memory Facts": memory.get_stats().get("count", 0),
                    "Facts Learned": auto_learner.learned_count,
                    "Learning Activity": auto_learner.current_activity,
                    "Synthesis Cycles": synthesizer.synthesis_count,
                    "Last Synthesis": synthesizer.last_synthesis or "never",
                    "Cognition Questions": cognition_engine.questions_answered,
                    "Current Question": (cognition_engine.current_question[:60] + "...") if cognition_engine.current_question else "idle",
                    "Conversation Length": len(self.conversation),
                }
                print_status(stats)
            except Exception as e:
                print_error(str(e))

        elif base == "/memory":
            try:
                from lyra.memory.vector_memory import memory
                stats = memory.get_stats()
                print_status({
                    "Enabled": stats.get("enabled", False),
                    "Total Memories": stats.get("count", 0),
                    "Storage Path": stats.get("path", "N/A"),
                })
            except Exception as e:
                print_error(str(e))

        elif base == "/cognition":
            try:
                from lyra.core.cognition_engine import cognition_engine
                s = cognition_engine.get_status()
                print_status({
                    "Running": s["running"],
                    "Questions Generated": s["questions_generated"],
                    "Questions Answered": s["questions_answered"],
                    "Queue Depth": s["queue_depth"],
                    "Current Strategy": s["current_strategy"],
                    "Current Question": s["current_question"][:70] + "..." if s["current_question"] else "idle",
                })
                if s.get("recent_entries"):
                    print_system("\nRecent self-questions:")
                    for e in s["recent_entries"][:3]:
                        print_system(f"  [{e['strategy']}] {e['question'][:80]}")
            except Exception as e:
                print_error(str(e))

        elif base == "/save":
            try:
                save_path = ROOT / "data" / f"conversation_{self.conv_id}.json"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_text(json.dumps({
                    "conversation_id": self.conv_id,
                    "persona": self.persona_id,
                    "saved_at": datetime.now().isoformat(),
                    "messages": self.conversation,
                }, indent=2))
                print_system(f"Saved to {save_path}")
            except Exception as e:
                print_error(f"Save failed: {e}")

        else:
            print_error(f"Unknown command: {base}. Type /help for commands.")


# ════════════════════════════════════════════════════════════
#  SERVER-CONNECT MODE — talks to running Lyra server
# ════════════════════════════════════════════════════════════

class ServerLyraSession:
    """
    Connects to a running Lyra server at localhost:7860 via WebSocket.
    Used when the server is already running.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.persona_id = "lyra"
        self.use_web = False
        self.conv_id = datetime.now().strftime("%Y%m%d%H%M%S")
        self.base_url = f"http://{host}:{port}"
        self.ws_url = f"ws://{host}:{port}/api/chat/ws/{self.conv_id}"

    async def _get_status(self) -> dict:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/api/health")
                return r.json()
        except Exception:
            return {}

    async def start(self):
        status = await self._get_status()
        print_banner(
            status.get("current_model", "none"),
            status.get("memory_count", 0),
            status.get("questions_answered", 0),
        )
        print_system(f"Connected to Lyra server at {self.base_url}")
        await self._chat_loop()

    async def _chat_loop(self):
        try:
            import websockets
        except ImportError:
            print_error("websockets package not installed. Run: pip install websockets")
            return

        async with websockets.connect(self.ws_url) as ws:
            while True:
                try:
                    if RICH:
                        Console().print(f"\n[bold cyan]You:[/] ", end="")
                    else:
                        sys.stdout.write(f"\n{_c(_C.CYAN, _C.BOLD + 'You:')} ")
                        sys.stdout.flush()

                    user_input = input().strip()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{_c(_C.GRAY, 'Goodbye.')}")
                    break

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self._handle_command(user_input, ws)
                    continue

                await ws.send(json.dumps({
                    "message": user_input,
                    "model_id": self.persona_id,
                    "use_memory": True,
                    "use_web_search": self.use_web,
                    "stream": True,
                }))

                # Read streaming response
                full_response = ""
                started = False
                while True:
                    raw = await ws.recv()
                    msg = json.loads(raw)
                    mtype = msg.get("type")

                    if mtype == "status":
                        print_system(msg.get("content", ""))
                    elif mtype == "start":
                        print_user_prompt(self.persona_id)
                        started = True
                    elif mtype == "token":
                        token = msg.get("content", "")
                        stream_token(token)
                        full_response += token
                    elif mtype == "done":
                        print()
                        break
                    elif mtype == "error":
                        print_error(msg.get("content", "unknown error"))
                        break

    async def _handle_command(self, cmd: str, ws=None):
        parts = cmd.strip().split(maxsplit=1)
        base = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if base in ("/quit", "/exit", "/q"):
            print(_c(_C.GRAY, "\nGoodbye."))
            sys.exit(0)

        elif base == "/help":
            print_help()

        elif base == "/model":
            valid = ["lyra", "lyra-code", "lyra-research", "lyra-create", "lyra-web"]
            if arg in valid:
                self.persona_id = arg
                _, icon = PERSONA_COLORS.get(arg, (_C.WHITE, "✦"))
                print_system(f"Switched to {icon} {arg}")
            else:
                print_system(f"Current: {self.persona_id} | Available: {' | '.join(valid)}")

        elif base == "/web":
            self.use_web = not self.use_web
            print_system(f"Web search: {'ON' if self.use_web else 'OFF'}")

        elif base == "/status":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"{self.base_url}/api/health")
                    print_status(r.json())
            except Exception as e:
                print_error(str(e))

        elif base == "/cognition":
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5) as client:
                    r = await client.get(f"{self.base_url}/api/cognition/status")
                    s = r.json()
                    print_status({
                        "Questions Answered": s.get("questions_answered", 0),
                        "Queue Depth": s.get("queue_depth", 0),
                        "Current Question": (s.get("current_question", "")[:70] or "idle"),
                        "Current Strategy": s.get("current_strategy", ""),
                    })
                    for e in s.get("recent_entries", [])[:3]:
                        print_system(f"  [{e['strategy']}] {e['question'][:80]}")
            except Exception as e:
                print_error(str(e))

        elif base == "/clear":
            self.conv_id = datetime.now().strftime("%Y%m%d%H%M%S")
            self.ws_url = f"ws://{self.host}:{self.port}/api/chat/ws/{self.conv_id}"
            print_system("Conversation cleared (new session ID).")

        else:
            print_error(f"Unknown command: {base}. Type /help.")


# ════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════

def _server_is_running(host: str, port: int) -> bool:
    """Check if a Lyra server is already listening."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


async def main_async(args):
    sys.path.insert(0, str(ROOT))

    if args.direct:
        # Force direct mode (load model in-process)
        session = DirectLyraSession()
        await session.start()
        return

    host = args.host
    port = args.port

    if _server_is_running(host, port):
        print_system(f"Found Lyra server at {host}:{port} — connecting...")
        session = ServerLyraSession(host, port)
        await session.start()
    else:
        # No server running — use direct mode
        print_system("No Lyra server detected — running in direct mode.")
        session = DirectLyraSession()
        await session.start()


def main():
    parser = argparse.ArgumentParser(
        description="Lyra AI — Terminal Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  lyra-cli                     # auto-detect mode
  lyra-cli --direct            # load model directly (no server)
  lyra-cli --host localhost --port 7860
        """
    )
    parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=7860, help="Server port (default: 7860)")
    parser.add_argument("--direct", action="store_true", help="Direct mode: load model in-process")
    parser.add_argument("--persona", default="lyra",
                        choices=["lyra", "lyra-code", "lyra-research", "lyra-create", "lyra-web"],
                        help="Starting persona")
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print(f"\n{_C.GRAY}Goodbye.{_C.RESET}")


if __name__ == "__main__":
    main()
