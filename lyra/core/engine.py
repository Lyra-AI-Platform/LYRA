"""
Lyra AI Platform — Model Engine
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
    def __init__(self):
        self.loaded_model = None
        self.loaded_model_name = None
        self.model_type = None
        self.tokenizer = None
        self._lock = asyncio.Lock()
        self.user_active = asyncio.Event()

    def set_user_active(self): self.user_active.set()
    def set_user_idle(self): self.user_active.clear()

    async def wait_for_user_idle(self, poll_interval=0.5):
        while self.user_active.is_set():
            await asyncio.sleep(poll_interval)

    def get_available_models(self):
        models = []
        if not MODELS_DIR.exists(): return models
        for f in MODELS_DIR.iterdir():
            if f.suffix in (".gguf", ".bin") or f.is_dir():
                models.append({"name": f.name, "path": str(f), "loaded": f.name == self.loaded_model_name})
        return models

    async def load_model(self, model_name, model_config=None):
        async with self._lock:
            if self.loaded_model_name == model_name:
                return {"status": "already_loaded", "model": model_name}
            model_path = MODELS_DIR / model_name
            if not model_path.exists():
                return {"status": "error", "message": f"Model not found: {model_name}"}
            config = model_config or {}
            n_ctx = config.get("context_length", 8192)
            n_gpu = config.get("gpu_layers", -1)
            try:
                if model_path.suffix == ".gguf":
                    return await self._load_llama_cpp(model_path, n_ctx, n_gpu)
                else:
                    return await self._load_transformers(model_path, config)
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def _load_llama_cpp(self, path, n_ctx, n_gpu):
        loop = asyncio.get_event_loop()
        try:
            from llama_cpp import Llama
            def _load():
                return Llama(model_path=str(path), n_ctx=n_ctx, n_gpu_layers=n_gpu, n_threads=os.cpu_count(), verbose=False)
            self.loaded_model = await loop.run_in_executor(None, _load)
            self.loaded_model_name = path.name
            self.model_type = "llama_cpp"
            return {"status": "loaded", "model": path.name}
        except ImportError:
            return {"status": "error", "message": "llama-cpp-python not installed"}

    async def _load_transformers(self, path, config):
        loop = asyncio.get_event_loop()
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            def _load():
                tok = AutoTokenizer.from_pretrained(str(path))
                device = "cuda" if torch.cuda.is_available() else "cpu"
                mdl = AutoModelForCausalLM.from_pretrained(str(path), torch_dtype=torch.float16 if device == "cuda" else torch.float32, device_map="auto")
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

    async def generate(self, messages, system_prompt="", max_tokens=2048, temperature=0.7, top_p=0.9, stream=True):
        if not self.loaded_model:
            yield "[No model loaded]"
            return
        if self.model_type == "llama_cpp":
            async for t in self._gen_llama(messages, system_prompt, max_tokens, temperature, top_p):
                yield t
        elif self.model_type == "transformers":
            async for t in self._gen_transformers(messages, system_prompt, max_tokens, temperature):
                yield t

    async def _gen_llama(self, messages, system_prompt, max_tokens, temperature, top_p):
        loop = asyncio.get_event_loop()
        msgs = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages
        def _run():
            return self.loaded_model.create_chat_completion(messages=msgs, max_tokens=max_tokens, temperature=temperature, top_p=top_p, stream=True)
        stream_iter = await loop.run_in_executor(None, _run)
        for chunk in stream_iter:
            content = chunk["choices"][0].get("delta", {}).get("content", "")
            if content:
                yield content
                await asyncio.sleep(0)

    async def _gen_transformers(self, messages, system_prompt, max_tokens, temperature):
        import torch
        from transformers import TextIteratorStreamer
        from threading import Thread
        msgs = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages
        prompt = self.tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt")
        device = next(self.loaded_model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}
        streamer = TextIteratorStreamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True)
        thread = Thread(target=self.loaded_model.generate, kwargs={**inputs, "streamer": streamer, "max_new_tokens": max_tokens, "temperature": temperature, "do_sample": temperature > 0})
        thread.start()
        for token in streamer:
            yield token
            await asyncio.sleep(0)


engine = ModelEngine()
