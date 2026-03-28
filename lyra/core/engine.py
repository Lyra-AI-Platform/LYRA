"""
Lyra AI Platform — Model Engine
Copyright (C) 2026 Lyra Contributors
Licensed under GNU AGPL v3. See LICENSE for details.

Handles loading, running, and managing local AI models.
Supports: llama-cpp-python (GGUF), HuggingFace Transformers
"""
import os
import asyncio
import logging
from typing import AsyncGenerator, Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "data" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


class ModelEngine:
    """Core AI model engine — loads and runs local models."""

    def __init__(self):
        self.loaded_model = None
        self.loaded_model_name = None
        self.model_type = None
        self.tokenizer = None
        self._lock = asyncio.Lock()
        # Priority flag: set True while a real user is being served.
        # Background cognition checks this and yields immediately.
        self.user_active = asyncio.Event()

    def set_user_active(self):
        """Signal that a real user request is in flight — background tasks must yield."""
        self.user_active.set()

    def set_user_idle(self):
        """Signal that the user request is done — background tasks may resume."""
        self.user_active.clear()

    async def wait_for_user_idle(self, poll_interval: float = 0.5):
        """Background tasks call this before each inference to respect user priority."""
        while self.user_active.is_set():
            await asyncio.sleep(poll_interval)

    def get_available_models(self) -> List[Dict[str, Any]]:
        models = []
        if not MODELS_DIR.exists():
            return models
        for f in MODELS_DIR.iterdir():
            if f.suffix in (".gguf", ".bin") or f.is_dir():
                models.append({
                    "name": f.name,
                    "path": str(f),
                    "type": "gguf" if f.suffix == ".gguf" else "transformers",
                    "size_gb": self._get_size(f),
                    "loaded": f.name == self.loaded_model_name,
                })
        return models

    def _get_size(self, path: Path) -> float:
        if path.is_file():
            return round(path.stat().st_size / 1e9, 2)
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return round(total / 1e9, 2)

    async def load_model(self, model_name: str, model_config: Dict = None) -> Dict:
        async with self._lock:
            if self.loaded_model_name == model_name:
                return {"status": "already_loaded", "model": model_name}
            model_path = MODELS_DIR / model_name
            if not model_path.exists():
                return {"status": "error", "message": f"Model not found: {model_name}"}
            if self.loaded_model:
                await self.unload_model()
            config = model_config or {}
            n_ctx = config.get("context_length", 8192)
            n_gpu_layers = config.get("gpu_layers", -1)
            try:
                if model_path.suffix == ".gguf":
                    return await self._load_llama_cpp(model_path, n_ctx, n_gpu_layers)
                else:
                    return await self._load_transformers(model_path, config)
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                return {"status": "error", "message": str(e)}

    async def _load_llama_cpp(self, path: Path, n_ctx: int, n_gpu_layers: int) -> Dict:
        loop = asyncio.get_event_loop()
        try:
            from llama_cpp import Llama
            def _load():
                return Llama(
                    model_path=str(path), n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers, n_threads=os.cpu_count(),
                    verbose=False, flash_attn=True,
                )
            self.loaded_model = await loop.run_in_executor(None, _load)
            self.loaded_model_name = path.name
            self.model_type = "llama_cpp"
            return {"status": "loaded", "model": path.name, "context_length": n_ctx}
        except ImportError:
            return {"status": "error", "message": "llama-cpp-python not installed. Run: pip install llama-cpp-python"}

    async def _load_transformers(self, path: Path, config: Dict) -> Dict:
        loop = asyncio.get_event_loop()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            def _load():
                tok = AutoTokenizer.from_pretrained(str(path))
                device = "cuda" if torch.cuda.is_available() else "cpu"
                dtype = torch.float16 if device == "cuda" else torch.float32
                mdl = AutoModelForCausalLM.from_pretrained(str(path), torch_dtype=dtype, device_map="auto")
                return mdl, tok
            self.loaded_model, self.tokenizer = await loop.run_in_executor(None, _load)
            self.loaded_model_name = path.name
            self.model_type = "transformers"
            return {"status": "loaded", "model": path.name}
        except ImportError:
            return {"status": "error", "message": "transformers not installed"}

    async def unload_model(self):
        if self.loaded_model:
            del self.loaded_model
            self.loaded_model = None
            self.loaded_model_name = None
            self.tokenizer = None
            import gc; gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    async def generate(
        self, messages: List[Dict[str, str]], system_prompt: str = "",
        max_tokens: int = 2048, temperature: float = 0.7,
        top_p: float = 0.9, stream: bool = True,
    ) -> AsyncGenerator[str, None]:
        if not self.loaded_model:
            yield "[ERROR] No model loaded. Please load a model first."
            return
        if self.model_type == "llama_cpp":
            async for token in self._generate_llama_cpp(messages, system_prompt, max_tokens, temperature, top_p, stream):
                yield token
        elif self.model_type == "transformers":
            async for token in self._generate_transformers(messages, system_prompt, max_tokens, temperature):
                yield token

    async def _generate_llama_cpp(self, messages, system_prompt, max_tokens, temperature, top_p, stream):
        loop = asyncio.get_event_loop()
        chat_messages = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(messages)
        def _run_stream():
            return self.loaded_model.create_chat_completion(
                messages=chat_messages, max_tokens=max_tokens,
                temperature=temperature, top_p=top_p, stream=True,
            )
        try:
            stream_iter = await loop.run_in_executor(None, _run_stream)
            for chunk in stream_iter:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
                    await asyncio.sleep(0)
        except Exception as e:
            yield f"\n[ERROR] {str(e)}"

    async def _generate_transformers(self, messages, system_prompt, max_tokens, temperature):
        import torch
        from transformers import TextIteratorStreamer
        from threading import Thread
        chat_messages = []
        if system_prompt:
            chat_messages.append({"role": "system", "content": system_prompt})
        chat_messages.extend(messages)
        prompt = self.tokenizer.apply_chat_template(chat_messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt")
        device = next(self.loaded_model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs = {**inputs, "streamer": streamer, "max_new_tokens": max_tokens, "temperature": temperature, "do_sample": temperature > 0}
        thread = Thread(target=self.loaded_model.generate, kwargs=gen_kwargs)
        thread.start()
        for token in streamer:
            yield token
            await asyncio.sleep(0)


engine = ModelEngine()
