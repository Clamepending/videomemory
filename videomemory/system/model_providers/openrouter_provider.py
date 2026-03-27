"""OpenRouter model providers."""

import os
import time
import logging
from typing import Type
import httpx
from pydantic import BaseModel
from .base import BaseModelProvider

logger = logging.getLogger('OpenRouterProviders')


class RateLimiter:
    """Simple rate limiter to enforce requests per minute limit."""
    def __init__(self, requests_per_minute: float):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0
    
    def wait_if_needed(self):
        """Wait if necessary to respect rate limit."""
        current_time = time.time()
        if self.last_request_time > 0:
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                if sleep_time > 0:
                    time.sleep(sleep_time)
        self.last_request_time = time.time()


# Global rate limiter for OpenRouter (20 requests per minute for free models, use 18 to be conservative)
_openrouter_rate_limiter = RateLimiter(18.0)


class _BaseOpenRouterProvider(BaseModelProvider):
    """Base class for OpenRouter providers with shared functionality."""
    
    def __init__(self, api_key: str = None, model_name: str = None):
        """Initialize OpenRouter provider.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
            model_name: The model name to use (e.g., "molmo/molmo-2-8b-free")
        """
        if api_key is None:
            api_key = os.getenv("OPENROUTER_API_KEY")
        super().__init__(api_key)
        self._rate_limiter = _openrouter_rate_limiter
        self._model_name = model_name
        self._timeout = self._build_timeout()
        
        # Initialize the OpenRouter provider
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not found. OpenRouter provider will fail.")
        else:
            # Keep parity with providers that materialize a client during init so
            # VideoStreamIngestor does not treat this provider as uninitialized.
            self._client = object()
            logger.info(f"Initialized OpenRouter provider for {self._model_name}")

    @staticmethod
    def _build_timeout() -> httpx.Timeout:
        """Build a bounded timeout so slow upstream responses fail predictably."""
        total = float(os.getenv("VIDEOMEMORY_OPENROUTER_TIMEOUT_S", "45.0"))
        connect = float(os.getenv("VIDEOMEMORY_OPENROUTER_CONNECT_TIMEOUT_S", min(total, 10.0)))
        read = float(os.getenv("VIDEOMEMORY_OPENROUTER_READ_TIMEOUT_S", total))
        write = float(os.getenv("VIDEOMEMORY_OPENROUTER_WRITE_TIMEOUT_S", min(total, 10.0)))
        pool = float(os.getenv("VIDEOMEMORY_OPENROUTER_POOL_TIMEOUT_S", min(total, 10.0)))
        return httpx.Timeout(connect=connect, read=read, write=write, pool=pool)
    
    def _sync_generate_content(self, image_base64: str, prompt: str, response_model: Type[BaseModel]) -> BaseModel:
        """Generate content using OpenRouter API.
        
        Args:
            image_base64: Base64-encoded image string
            prompt: Text prompt
            response_model: Pydantic model class describing expected output
            
        Returns:
            Parsed and validated Pydantic model instance
        """
        if not self.api_key:
            raise RuntimeError("OpenRouter API key not set. Check OPENROUTER_API_KEY environment variable.")
        
        # Enforce rate limit
        self._rate_limiter.wait_if_needed()
        
        schema = response_model.model_json_schema()
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": schema,
            },
        }
        
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self._model_name,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                            {"type": "text", "text": prompt}
                        ]
                    }],
                    "response_format": response_format
                }
            )
            
            if response.status_code == 429:
                raise RuntimeError("Rate limit exceeded (429)")
            
            response.raise_for_status()
            result = response.json()

            message = (result.get("choices") or [{}])[0].get("message") or {}
            content = message.get("content")
            if content is None:
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    content = (tool_calls[0].get("function") or {}).get("arguments")

            if content is None:
                raise RuntimeError("OpenRouter returned empty content.")

            if isinstance(content, (dict, list)):
                return response_model.model_validate(content)

            s = str(content).strip()
            if s.startswith("```") and s.endswith("```"):
                lines = s.splitlines()
                if len(lines) >= 2:
                    s = "\n".join(lines[1:-1]).strip()

            return response_model.model_validate_json(s)


class OpenRouterMolmo28BProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Molmo 2 8B free model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Molmo 2 8B.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="molmo/molmo-2-8b-free")


class OpenRouterQwen2VL7BProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Qwen 2 VL 7B model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Qwen 2 VL 7B.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="qwen/qwen-2-vl-7b-instruct")


class OpenRouterPhi4MultimodalProvider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Microsoft Phi 4 Multimodal Instruct model."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Microsoft Phi 4 Multimodal Instruct.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="microsoft/phi-4-multimodal-instruct")


class OpenRouterMistralSmall31Provider(_BaseOpenRouterProvider):
    """Provider for OpenRouter Mistral Small 3.1 24B Instruct (vision-capable)."""
    
    def __init__(self, api_key: str = None):
        """Initialize OpenRouter provider for Mistral Small 3.1 24B Instruct.
        
        Args:
            api_key: OpenRouter API key. If None, will try to get from OPENROUTER_API_KEY env var.
        """
        super().__init__(api_key=api_key, model_name="mistralai/mistral-small-3.1-24b-instruct")


# Paid-tier rate limiter (higher than free-tier 18 RPM)
_openrouter_paid_rate_limiter = RateLimiter(120.0)



class OpenRouterQwen3VL8BProvider(_BaseOpenRouterProvider):

    def __init__(self, api_key=None):
        super().__init__(api_key=api_key, model_name="qwen/qwen3-vl-8b-instruct")
        self._rate_limiter = _openrouter_paid_rate_limiter

    @staticmethod
    def _repair_json(s):
        """Fix common JSON issues from small VLMs: unquoted keys, trailing
        commas, duplicate 'task_updates' keys, and truncation."""
        import re as _re
        # Strip thinking tags
        s = _re.sub(r"<think>[\s\S]*?</think>", "", s).strip()
        # Strip markdown fences
        if s.startswith("```"):
            slines = s.splitlines()
            end = len(slines)
            for j in range(len(slines) - 1, 0, -1):
                if slines[j].strip().startswith("```"):
                    end = j
                    break
            s = "\n".join(slines[1:end]).strip()
        # Quote unquoted keys
        s = _re.sub(r'(?<=[{,\[])\s*([a-zA-Z_]\w*)\s*:', r' "\1":', s)
        # Remove trailing commas
        s = _re.sub(r',\s*([}\]])', r'\1', s)
        # Merge duplicate "task_updates" arrays into one
        # Pattern: the model emits {"task_updates": [...], "task_updates": [...], ...}
        arrays = _re.findall(r'"task_updates"\s*:\s*(\[.*?\])', s, _re.DOTALL)
        if len(arrays) > 1:
            import json as _json
            merged = []
            for arr_str in arrays:
                try:
                    items = _json.loads(arr_str)
                    if isinstance(items, list):
                        merged.extend(items)
                except Exception:
                    pass
            if merged:
                return _json.dumps({"task_updates": merged})
        # Truncation repair: extract valid task_update objects via regex
        try:
            import json as _json
            _json.loads(s)
            return s
        except Exception:
            pass
        import json as _json
        pattern = _re.compile(
            r'\{\s*"task_number"\s*:\s*(\d+)\s*,\s*'
            r'"task_note"\s*:\s*"([^"]*?)"\s*,\s*'
            r'"task_done"\s*:\s*(true|false)\s*\}'
        )
        items = []
        for m in pattern.finditer(s):
            items.append({
                "task_number": int(m.group(1)),
                "task_note": m.group(2),
                "task_done": m.group(3) == "true",
            })
        if items:
            return _json.dumps({"task_updates": items})
        return '{"task_updates": []}'

    def _sync_generate_content(self, image_base64, prompt, response_model):
        if not self.api_key:
            raise RuntimeError("OpenRouter API key not set.")
        self._rate_limiter.wait_if_needed()
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model_name,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": prompt}
                    ]}],
                    "response_format": {"type": "json_object"},
                },
            )
            if resp.status_code == 429:
                raise RuntimeError("Rate limit exceeded (429)")
            resp.raise_for_status()
            result = resp.json()
            msg = (result.get("choices") or [{}])[0].get("message") or {}
            content = msg.get("content")
            if content is None:
                tc = msg.get("tool_calls") or []
                if tc:
                    content = (tc[0].get("function") or {}).get("arguments")
            if content is None:
                raise RuntimeError("OpenRouter returned empty content.")
            if isinstance(content, (dict, list)):
                return response_model.model_validate(content)
            s = self._repair_json(str(content))
            return response_model.model_validate_json(s)


class OpenRouterCustomModelProvider(OpenRouterQwen3VL8BProvider):
    """Provider for arbitrary OpenRouter model IDs supplied at runtime."""

    def __init__(self, model_name: str, api_key=None):
        super().__init__(api_key=api_key)
        self._model_name = model_name
