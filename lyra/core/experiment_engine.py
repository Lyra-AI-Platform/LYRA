"""
Lyra AI Platform — Autonomous Experiment Engine
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Gives Lyra the ability to autonomously:
  1. Form a hypothesis
  2. Write Python code to test it
  3. Execute in a restricted sandbox
  4. Analyze results
  5. Store conclusions and chain to the next experiment

This is genuine AI-driven scientific experimentation — Lyra forms ideas,
tests them with real code execution, and learns from the results.
"""
import asyncio
import json
import logging
import os
import resource
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
EXPERIMENTS_DIR = DATA_DIR / "experiments"
EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Safety limits for sandboxed execution
SANDBOX_TIMEOUT_SECONDS = 15
SANDBOX_MAX_OUTPUT_BYTES = 32_768   # 32 KB
SANDBOX_MAX_MEMORY_MB = 256


@dataclass
class ExperimentRecord:
    id: str
    hypothesis: str
    code: str
    output: str
    error: str
    success: bool
    conclusion: str
    follow_up_questions: List[str]
    timestamp: float
    domain: str
    duration_ms: int


@dataclass
class ExperimentCycle:
    """One complete autonomous experiment cycle."""
    domain: str
    hypothesis: str
    code: str
    raw_output: str
    conclusion: str
    follow_ups: List[str]
    success: bool
    duration_ms: int


class CodeSandbox:
    """
    Restricted Python execution environment.
    No network, limited memory, timeout enforced, no dangerous imports.
    """

    BLOCKED_IMPORTS = {
        "socket", "requests", "urllib", "http", "ftplib", "smtplib",
        "subprocess", "os.system", "shutil.rmtree", "ctypes",
        "importlib", "multiprocessing",
    }

    ALLOWED_IMPORTS = {
        "math", "cmath", "random", "statistics", "itertools", "functools",
        "collections", "heapq", "bisect", "re", "json", "csv",
        "datetime", "time", "string", "hashlib", "struct",
        "numpy", "scipy", "sympy", "matplotlib",
        "typing", "dataclasses", "abc", "enum",
    }

    SAFETY_PREAMBLE = textwrap.dedent("""\
        import sys, signal

        # Block dangerous builtins
        _orig_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
        _BLOCKED = {
            'socket', 'requests', 'urllib', 'http.client', 'ftplib',
            'smtplib', 'subprocess', 'ctypes', 'multiprocessing',
        }
        def _safe_import(name, *args, **kwargs):
            if name.split('.')[0] in _BLOCKED:
                raise ImportError(f"Import blocked in sandbox: {name}")
            return _orig_import(name, *args, **kwargs)
        __builtins__.__import__ = _safe_import

        # Redirect file writes to /dev/null awareness
        import builtins
        _orig_open = builtins.open
        def _safe_open(path, mode='r', *args, **kwargs):
            if any(c in str(mode) for c in ('w', 'a', 'x')):
                raise PermissionError("File writes blocked in sandbox")
            return _orig_open(path, mode, *args, **kwargs)
        builtins.open = _safe_open

    """)

    async def execute(self, code: str, timeout: int = SANDBOX_TIMEOUT_SECONDS) -> Dict[str, Any]:
        """Execute code in a subprocess sandbox and return output."""
        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir=str(EXPERIMENTS_DIR)
        )
        try:
            full_code = self.SAFETY_PREAMBLE + "\n" + code
            tmp.write(full_code)
            tmp.flush()
            tmp.close()

            start = time.monotonic()

            def _set_limits():
                # Memory limit
                limit_bytes = SANDBOX_MAX_MEMORY_MB * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
                except Exception:
                    pass

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [sys.executable, tmp.name],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    preexec_fn=_set_limits,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "HOME": os.environ.get("HOME", "/tmp"),
                        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                    },
                ),
            )

            duration_ms = int((time.monotonic() - start) * 1000)
            stdout = result.stdout[:SANDBOX_MAX_OUTPUT_BYTES]
            stderr = result.stderr[:4096]

            return {
                "success": result.returncode == 0,
                "output": stdout,
                "error": stderr if result.returncode != 0 else "",
                "returncode": result.returncode,
                "duration_ms": duration_ms,
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Execution timed out after {timeout}s",
                "returncode": -1,
                "duration_ms": timeout * 1000,
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "returncode": -2,
                "duration_ms": 0,
            }
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass


class AutonomousExperimentEngine:
    """
    Lyra's self-directed scientific experimentation system.

    Lyra autonomously:
    - Generates hypotheses from its knowledge gaps
    - Writes Python code to test them
    - Executes in sandboxed environment
    - Analyzes results with LLM
    - Chains findings into further experiments
    - Stores conclusions in memory as synthesized_wisdom
    """

    def __init__(self):
        self.sandbox = CodeSandbox()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.experiments_completed = 0
        self.recent_experiments: Deque[ExperimentRecord] = deque(maxlen=50)
        self.current_experiment: str = ""
        self._experiment_interval = 300  # 5 minutes between autonomous cycles

        # Domains Lyra experiments in
        self.experiment_domains = [
            "mathematics",
            "algorithms",
            "physics_simulation",
            "statistics",
            "information_theory",
            "cryptography",
            "optimization",
            "number_theory",
            "chaos_theory",
            "neural_patterns",
        ]

    def start(self):
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("Experiment Engine: autonomous experimentation active")

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()

    async def _loop(self):
        """Autonomous experiment loop."""
        await asyncio.sleep(120)  # Initial delay — let system warm up
        while self.running:
            try:
                from lyra.core.engine import engine
                await engine.wait_for_user_idle()

                domain = self.experiment_domains[
                    self.experiments_completed % len(self.experiment_domains)
                ]
                await self._run_autonomous_cycle(domain)
                await asyncio.sleep(self._experiment_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Experiment loop error: {e}")
                await asyncio.sleep(60)

    async def _run_autonomous_cycle(self, domain: str):
        """Run one full hypothesis → code → execute → analyze cycle."""
        from lyra.core.engine import engine
        from lyra.memory.vector_memory import memory

        if not engine.loaded_model:
            return

        self.current_experiment = f"Generating {domain} hypothesis..."

        # Step 1: Generate hypothesis using LLM
        try:
            hypothesis_prompt = self._build_hypothesis_prompt(domain)
            hypothesis_text = ""
            async for token in engine.generate(
                messages=[{"role": "user", "content": hypothesis_prompt}],
                system_prompt="You are Lyra's experimental reasoning module. Be precise and scientific.",
                max_tokens=400,
                temperature=0.8,
            ):
                hypothesis_text += token

            if not hypothesis_text.strip():
                return

            # Extract hypothesis and code
            hypothesis, code = self._parse_hypothesis_response(hypothesis_text)
            if not code or len(code) < 20:
                return

            self.current_experiment = f"Running {domain} experiment..."

        except Exception as e:
            logger.debug(f"Hypothesis generation failed: {e}")
            return

        # Step 2: Execute in sandbox
        exec_result = await self.sandbox.execute(code)

        # Step 3: Analyze results with LLM
        try:
            analysis_prompt = self._build_analysis_prompt(
                domain, hypothesis, code,
                exec_result["output"], exec_result["error"]
            )
            analysis_text = ""
            async for token in engine.generate(
                messages=[{"role": "user", "content": analysis_prompt}],
                system_prompt="You analyze experimental results concisely. Extract key insights.",
                max_tokens=350,
                temperature=0.4,
            ):
                analysis_text += token

            conclusion, follow_ups = self._parse_analysis(analysis_text)

        except Exception as e:
            conclusion = f"Experiment ran. Output: {exec_result['output'][:200]}"
            follow_ups = []

        # Step 4: Store findings
        record = ExperimentRecord(
            id=str(uuid.uuid4())[:8],
            hypothesis=hypothesis,
            code=code,
            output=exec_result["output"],
            error=exec_result["error"],
            success=exec_result["success"],
            conclusion=conclusion,
            follow_up_questions=follow_ups,
            timestamp=time.time(),
            domain=domain,
            duration_ms=exec_result["duration_ms"],
        )
        self.recent_experiments.appendleft(record)
        self.experiments_completed += 1
        self.current_experiment = ""

        # Store in memory
        if conclusion:
            try:
                summary = (
                    f"[EXPERIMENT — {domain}]\n"
                    f"Hypothesis: {hypothesis[:200]}\n"
                    f"Result: {conclusion[:400]}"
                )
                memory.store(
                    content=summary,
                    memory_type="learned_knowledge",
                    metadata={"source": "experiment", "domain": domain},
                )
            except Exception:
                pass

        # Inject follow-ups into cognition queue
        if follow_ups:
            try:
                from lyra.core.cognition_engine import cognition_engine
                for q in follow_ups[:2]:
                    cognition_engine.inject_question(q, priority=7)
            except Exception:
                pass

        logger.info(f"Experiment complete [{domain}]: {hypothesis[:60]}")

    async def run_experiment_now(
        self, description: str, code: Optional[str] = None
    ) -> ExperimentRecord:
        """Run a specific experiment immediately (user or cognition triggered)."""
        from lyra.core.engine import engine
        from lyra.memory.vector_memory import memory

        # If no code provided, generate it
        if not code:
            prompt = (
                f"Write Python code to investigate: {description}\n"
                "Use only: math, random, statistics, itertools, numpy (if available).\n"
                "Print clear results. Keep code under 50 lines.\n"
                "Format:\n```python\n# code here\n```"
            )
            code_text = ""
            async for token in engine.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You write clean, focused experimental Python code.",
                max_tokens=500,
                temperature=0.4,
            ):
                code_text += token
            code = self._extract_code_block(code_text) or code_text

        exec_result = await self.sandbox.execute(code)

        analysis = f"Output: {exec_result['output'][:300]}"
        follow_ups = []
        if engine.loaded_model:
            try:
                analysis_text = ""
                async for token in engine.generate(
                    messages=[{"role": "user", "content": (
                        f"Experiment: {description}\n"
                        f"Code output: {exec_result['output'][:500]}\n"
                        f"Errors: {exec_result['error'][:200]}\n"
                        "In 2-3 sentences: what did we learn? List 1-2 follow-up questions."
                    )}],
                    system_prompt="Analyze experiment results scientifically.",
                    max_tokens=200,
                    temperature=0.3,
                ):
                    analysis_text += token
                conclusion, follow_ups = self._parse_analysis(analysis_text)
                analysis = conclusion
            except Exception:
                pass

        record = ExperimentRecord(
            id=str(uuid.uuid4())[:8],
            hypothesis=description,
            code=code,
            output=exec_result["output"],
            error=exec_result["error"],
            success=exec_result["success"],
            conclusion=analysis,
            follow_up_questions=follow_ups,
            timestamp=time.time(),
            domain="user_directed",
            duration_ms=exec_result["duration_ms"],
        )
        self.recent_experiments.appendleft(record)
        self.experiments_completed += 1

        if analysis:
            try:
                memory.store(
                    content=f"[EXPERIMENT] {description}\nResult: {analysis}",
                    memory_type="learned_knowledge",
                    metadata={"source": "user_experiment"},
                )
            except Exception:
                pass

        return record

    def _build_hypothesis_prompt(self, domain: str) -> str:
        return (
            f"Generate a {domain} experiment hypothesis and code.\n\n"
            "Format your response EXACTLY as:\n"
            "HYPOTHESIS: [one sentence hypothesis]\n"
            "```python\n"
            "# Experiment code here\n"
            "# Use: math, random, statistics, numpy\n"
            "# Print clear results showing the pattern\n"
            "# Maximum 40 lines\n"
            "```\n\n"
            f"Focus on: a genuinely interesting {domain} pattern, formula, or phenomenon. "
            "Something that produces surprising or illuminating numerical results when computed."
        )

    def _parse_hypothesis_response(self, text: str) -> tuple:
        hypothesis = ""
        if "HYPOTHESIS:" in text:
            lines = text.split("\n")
            for line in lines:
                if line.startswith("HYPOTHESIS:"):
                    hypothesis = line.replace("HYPOTHESIS:", "").strip()
                    break

        code = self._extract_code_block(text)
        return hypothesis or text[:100], code or ""

    def _extract_code_block(self, text: str) -> str:
        """Extract ```python ... ``` block from text."""
        if "```python" in text:
            start = text.index("```python") + 9
            end = text.index("```", start) if "```" in text[start:] else len(text)
            return text[start:end].strip()
        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            return text[start:end].strip()
        return ""

    def _build_analysis_prompt(
        self, domain: str, hypothesis: str,
        code: str, output: str, error: str
    ) -> str:
        return (
            f"Domain: {domain}\n"
            f"Hypothesis: {hypothesis}\n"
            f"Execution output:\n{output[:600]}\n"
            f"Errors: {error[:200]}\n\n"
            "Respond with:\n"
            "CONCLUSION: [2-3 sentence insight from the results]\n"
            "FOLLOW_UP_1: [specific follow-up question]\n"
            "FOLLOW_UP_2: [another follow-up question]"
        )

    def _parse_analysis(self, text: str) -> tuple:
        conclusion = ""
        follow_ups = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("CONCLUSION:"):
                conclusion = line.replace("CONCLUSION:", "").strip()
            elif line.startswith("FOLLOW_UP_"):
                q = line.split(":", 1)[-1].strip()
                if q:
                    follow_ups.append(q)
        if not conclusion:
            conclusion = text[:300]
        return conclusion, follow_ups

    def get_status(self) -> Dict:
        return {
            "running": self.running,
            "experiments_completed": self.experiments_completed,
            "current_experiment": self.current_experiment,
            "recent_count": len(self.recent_experiments),
        }

    def get_recent_summary(self, n: int = 5) -> List[Dict]:
        results = []
        for exp in list(self.recent_experiments)[:n]:
            results.append({
                "id": exp.id,
                "domain": exp.domain,
                "hypothesis": exp.hypothesis[:120],
                "conclusion": exp.conclusion[:200],
                "success": exp.success,
                "follow_ups": exp.follow_up_questions[:2],
                "duration_ms": exp.duration_ms,
            })
        return results


# Singleton
experiment_engine = AutonomousExperimentEngine()
