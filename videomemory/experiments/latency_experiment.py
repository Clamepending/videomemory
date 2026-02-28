"""Latency benchmarking script for comparing different model providers and models.

This script tests latency across Google, OpenAI, Anthropic, and OpenRouter models
using the same prompt and image size as the video streamer (640x480).

Required Environment Variables:
    - GOOGLE_API_KEY: For Google models (gemini-2.5-flash, etc.)
    - OPENAI_API_KEY: For OpenAI models (gpt-4o, etc.)
    - ANTHROPIC_API_KEY: For Anthropic models (claude-3-5-sonnet, etc.)
    - OPENROUTER_API_KEY: For OpenRouter models (qwen/qwen-2-vl-72b-instruct, etc.)

Usage:
    python latency_experiment.py
"""

import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, NamedTuple, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import cv2
import numpy as np
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from tqdm import tqdm

# Add parent directory to path to import from video_stream_ingestor
sys.path.insert(0, str(Path(__file__).parent.parent))
from system.stream_ingestors.video_stream_ingestor import VideoIngestorOutput, VideoStreamIngestor
from system.task_types import Task
from system.model_providers import get_VLM_provider

# Load .env file from the same directory as this script
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    print(f"Warning: .env file not found at {env_path}. Using system environment variables.")
    load_dotenv(override=True)  # Fallback to default .env search

from google import genai
from google.genai import types as genai_types
from openai import OpenAI
import anthropic
import httpx

# Configuration
SAMPLE_SIZE = 5  # Number of runs per model for averaging
API_TIMEOUT = 20.0  # Timeout in seconds for API calls (increased for slower models)

# OpenRouter rate limits: 20 requests per minute for free models
# Use 18 requests/min to be conservative and avoid hitting the limit
OPENROUTER_RATE_LIMIT = 18  # requests per minute (conservative)
OPENROUTER_MIN_INTERVAL = 60.0 / OPENROUTER_RATE_LIMIT  # ~3.33 seconds between requests


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


# Global rate limiter for OpenRouter
openrouter_rate_limiter = RateLimiter(OPENROUTER_RATE_LIMIT)


def with_timeout(func: Callable, timeout: float, *args, **kwargs):
    """Execute a function with a timeout using ThreadPoolExecutor."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            raise TimeoutError(f"Function {func.__name__} exceeded timeout of {timeout}s")


class ModelResult(NamedTuple):
    """Result from a model test."""
    latency: float
    input_tokens: int
    output_tokens: int
    error: Optional[str] = None


def load_test_image(width: int = 640, height: int = 480) -> np.ndarray:
    """Load and resize test image to match video streamer format."""
    image_path = Path(__file__).parent / "cat_on_a_mat.jpg"
    if not image_path.exists():
        raise FileNotFoundError(f"Test image not found: {image_path}")
    
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Failed to load image: {image_path}")
    
    # Resize to match video streamer format (640x480)
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)


def build_test_prompt(ingestor: VideoStreamIngestor) -> str:
    """Build prompt using VideoStreamIngestor's method."""
    task = Task(task_number=0, task_desc="Count the number of cats", task_note=[], done=False)
    ingestor.add_task(task)
    return ingestor._build_prompt()


# Provider configurations
# Note: All models listed below support image+text inputs (vision multimodal)
PROVIDER_CONFIGS = {
    
    "OpenRouter": {
        # Fast vision models verified to support image+text inputs (as of Jan 2026)
        "models": [
            "qwen/qwen-2.5-vl-7b-instruct",
            # OpenAI models (all support vision)
            "openai/gpt-4o-mini",  # Fastest OpenAI vision model
            
            # Google Gemini models (all support vision)
            "google/gemini-3-flash-preview",  # Latest fast Gemini (Dec 2025)
            "google/gemini-2.5-flash",  # Fast and efficient
            "google/gemini-2.5-flash-lite",  # Even faster, lighter
            "google/gemini-2.0-flash-exp:free",  # Free tier option
            
            # Anthropic Claude models (all support vision)
            "anthropic/claude-3.5-haiku",  # Fastest Claude vision model
            "anthropic/claude-3.5-sonnet",  # Balanced speed/quality
            
            # Qwen models (all support vision)
            "qwen/qwen-2-vl-7b-instruct",  # Fast 7B vision model
            "qwen/qwen-2.5-omni-7b",  # Multimodal omni model (Mar 2025)
            # "qwen/qwen-2.5-vl-7b-instruct:free",  # Free tier option
            # "qwen/qwen2.5-vl-3b-instruct",  # doesnt work
            
            "qwen/qwen3-vl-8b-instruct",  # Fast 8B vision model
            "qwen/qwen3-vl-30b-a3b-instruct",  # Fast 30B vision model?
            
            # Meta Llama models (support vision)
            "meta-llama/llama-3.2-11b-vision-instruct",  # Fast vision model
            # "meta-llama/llama-3.1-8b-instruct",  # Images not supported
            
            # Microsoft models
            "microsoft/phi-4-multimodal-instruct",  # Fast multimodal (Mar 2025)
            
            # Mistral models
            "mistralai/pixtral-12b-2409",  # Fast 12B vision model
            
            "allenai/molmo-2-8b:free", # Fast 8B vision model
            
        ],
        "api_key": "OPENROUTER_API_KEY",
    },
    "Anthropic": {
        # All Claude 3.5+ models support vision (text + image inputs)
        "models": [
            "claude-sonnet-4-5-20250929",  # Latest Sonnet (supports vision) ✓
            "claude-haiku-4-5-20251001",  # Fastest Claude vision model ✓
        ],
        "api_key": "ANTHROPIC_API_KEY",
    },
    "OpenAI": {
        # Vision support: gpt-4o, gpt-4o-mini, gpt-4-turbo support vision
        # Note: gpt-5.x models may not all support vision - verify before use
        "models": [
            "gpt-4o",  # Fast multimodal (supports vision) ✓
            "gpt-4o-mini-2024-07-18",  # Fastest OpenAI vision model ✓
            # "gpt-4-turbo",  # Alternative vision option ✓
            # Uncomment below if verified to support vision:
            "gpt-5.2-2025-12-11",
            "gpt-5-nano-2025-08-07",
            "gpt-5-mini-2025-08-07",
            "gpt-4.1-nano-2025-04-14",
        ],
        "api_key": "OPENAI_API_KEY",
    },
    
    "Google": {
        # All Gemini models support vision (text, image, video, audio)
        "models": [
            # "gemini-3-pro-preview",  # Latest flagship (Nov 2025)
            "gemini-3-flash-preview",  # Latest fast model (Dec 2025)
            "gemini-2.5-flash",  # Fast and efficient
            "gemini-2.5-flash-lite",  # Even faster, lighter
            # "gemini-2.5-pro",  # More capable
            "gemini-2.0-flash",  # Previous generation
            "gemini-2.0-flash-lite",  # Previous generation lite
        ],
        "api_key": "GOOGLE_API_KEY",
    }
}


def call_google(model_name: str, image_base64: str, prompt: str, api_key: str) -> ModelResult:
    """Call Google API."""
    def _call():
        client = genai.Client(api_key=api_key)
        image_part = genai_types.Part(inline_data=genai_types.Blob(
            data=base64.b64decode(image_base64), mime_type="image/jpeg"))
        return client.models.generate_content(
            model=model_name,
            contents=[image_part, genai_types.Part(text=prompt)],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VideoIngestorOutput.model_json_schema())
        )
    
    try:
        start = time.time()
        response = with_timeout(_call, API_TIMEOUT)
        latency = time.time() - start
        input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) if hasattr(response, 'usage_metadata') and response.usage_metadata else 0
        output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) if hasattr(response, 'usage_metadata') and response.usage_metadata else 0
        # Return timing results - don't validate JSON, just measure latency
        return ModelResult(latency, input_tokens, output_tokens, None)
    except TimeoutError:
        # Don't print warning for timeout - it's expected for some slow models
        error_msg = f"Google API error: Function _call exceeded timeout of {API_TIMEOUT}s"
        return ModelResult(0, 0, 0, error_msg)
    except Exception as e:
        error_msg = f"Google API error: {str(e)}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)


def call_openai(model_name: str, image_base64: str, prompt: str, api_key: str) -> ModelResult:
    """Call OpenAI API."""
    def _call():
        client = OpenAI(api_key=api_key)
        return client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                {"type": "text", "text": prompt}
            ]}],
            response_format={"type": "json_object"}
        )
    
    try:
        start = time.time()
        response = with_timeout(_call, API_TIMEOUT)
        latency = time.time() - start
        input_tokens = response.usage.prompt_tokens if hasattr(response, 'usage') and response.usage else 0
        output_tokens = response.usage.completion_tokens if hasattr(response, 'usage') and response.usage else 0
        # Return timing results - don't validate JSON, just measure latency
        return ModelResult(latency, input_tokens, output_tokens, None)
    except Exception as e:
        error_msg = f"OpenAI API error: {str(e)}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)


def call_anthropic(model_name: str, image_base64: str, prompt: str, api_key: str) -> ModelResult:
    """Call Anthropic API."""
    def _call():
        client = anthropic.Anthropic(api_key=api_key)
        return client.messages.create(
            model=model_name,
            max_tokens=4096,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_base64}},
                {"type": "text", "text": prompt + "\n\nPlease respond with valid JSON matching this schema: {\"task_updates\": []}"}
            ]}]
        )
    
    try:
        start = time.time()
        message = with_timeout(_call, API_TIMEOUT)
        latency = time.time() - start
        
        # Extract token usage if available
        input_tokens = message.usage.input_tokens if hasattr(message, 'usage') and message.usage else 0
        output_tokens = message.usage.output_tokens if hasattr(message, 'usage') and message.usage else 0
        
        # Return timing results - don't validate JSON, just measure latency
        return ModelResult(latency, input_tokens, output_tokens, None)
    except TimeoutError:
        error_msg = f"Anthropic API error: Function _call exceeded timeout of {API_TIMEOUT}s"
        return ModelResult(0, 0, 0, error_msg)
    except anthropic.APIError as api_err:
        # Handle Anthropic-specific API errors
        error_msg = f"Anthropic API error: {api_err.status_code} {api_err.message}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)
    except Exception as e:
        error_msg = f"Anthropic API error: {str(e)}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)


def call_openrouter(model_name: str, image_base64: str, prompt: str, api_key: str) -> ModelResult:
    """Call OpenRouter API with rate limiting."""
    # Enforce rate limit (20 requests per minute)
    openrouter_rate_limiter.wait_if_needed()
    
    try:
        start = time.time()
        with httpx.Client(timeout=API_TIMEOUT) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                        {"type": "text", "text": prompt + "\n\nPlease respond with valid JSON matching this schema: {\"task_updates\": []}"}
                    ]}],
                    "response_format": {"type": "json_object"}
                }
            )
            # Check for rate limit errors before raising
            if response.status_code == 429:
                error_msg = "Rate limit exceeded (429)"
                # Don't print warning for 429 - rate limiter should prevent most of these
                return ModelResult(0, 0, 0, error_msg)
            
            response.raise_for_status()
            result = response.json()
            input_tokens = result["usage"].get("prompt_tokens", 0) if "usage" in result else 0
            output_tokens = result["usage"].get("completion_tokens", 0) if "usage" in result else 0
        latency = time.time() - start
        # Return timing results - don't validate JSON, just measure latency
        return ModelResult(latency, input_tokens, output_tokens, None)
    except httpx.HTTPStatusError as e:
        # Suppress 429 errors (rate limiting) - they're expected
        if e.response.status_code == 429:
            error_msg = "Rate limit exceeded (429)"
            return ModelResult(0, 0, 0, error_msg)
        error_msg = f"OpenRouter API error: {str(e)}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)
    except Exception as e:
        error_msg = f"OpenRouter API error: {str(e)}"
        print(f"\n⚠️  {error_msg}", flush=True)
        return ModelResult(0, 0, 0, error_msg)


# Provider function mapping
PROVIDER_FUNCTIONS = {
    "Google": call_google,
    "OpenAI": call_openai,
    "Anthropic": call_anthropic,
    "OpenRouter": call_openrouter,
}


def run_benchmark(num_runs: int = SAMPLE_SIZE) -> Dict[str, Dict[str, Dict]]:
    """Run latency benchmark for all models."""
    print("=" * 80)
    print("LATENCY BENCHMARK - Model Provider Comparison")
    print("=" * 80)
    print(f"Image size: 640x480 | Runs per model: {num_runs}")
    print("=" * 80)
    
    # Load image and create ingestor to reuse its methods
    test_image = load_test_image(640, 480)
    model_provider = get_VLM_provider()
    ingestor = VideoStreamIngestor(camera_index=0, action_runner=None, model_provider=model_provider, session_service=None)
    image_base64 = ingestor._frame_to_base64(test_image)
    prompt = build_test_prompt(ingestor)
    results = {}
    
    # Filter providers that have API keys and count total models
    providers_with_keys = []
    total_models = 0
    for provider, config in PROVIDER_CONFIGS.items():
        api_key = os.getenv(config["api_key"])
        if api_key:
            providers_with_keys.append((provider, config))
            total_models += len(config["models"])
        else:
            print(f"\n{'='*80}\nSkipping {provider} - {config['api_key']} not set\n{'='*80}")
    
    # Create overall progress bar
    overall_progress = tqdm(total=total_models, desc="Overall progress", unit="model")
    
    for provider_idx, (provider, config) in enumerate(providers_with_keys):
        if provider_idx > 0:
            time.sleep(2.0)
        
        api_key = os.getenv(config["api_key"])
        call_func = PROVIDER_FUNCTIONS[provider]
        print(f"\n{'='*80}\nTesting {provider} models...\n{'='*80}")
        results[provider] = {}
        
        for model_name in tqdm(config["models"], desc=f"{provider} models", leave=False):
            latencies, input_tokens, output_tokens = [], [], []
            
            for run_idx in tqdm(range(num_runs), desc=f"{model_name} runs", leave=False):
                result = call_func(model_name, image_base64, prompt, api_key)
                if result.latency > 0:
                    latencies.append(result.latency)
                    input_tokens.append(result.input_tokens)
                    output_tokens.append(result.output_tokens)
                time.sleep(0.5)
            
            overall_progress.update(1)
            
            if latencies:
                # Store individual measurements for error bars
                results[provider][model_name] = {
                    "latency": sum(latencies) / len(latencies),
                    "latency_std": np.std(latencies) if len(latencies) > 1 else 0.0,
                    "latency_samples": latencies,  # Store all samples for error bars
                    "input_tokens": int(sum(input_tokens) / len(input_tokens)),
                    "output_tokens": int(sum(output_tokens) / len(output_tokens)),
                }
                print(f"✓ {model_name}: {results[provider][model_name]['latency']:.3f}s ± {results[provider][model_name]['latency_std']:.3f}s | "
                      f"Input: {results[provider][model_name]['input_tokens']} tokens | "
                      f"Output: {results[provider][model_name]['output_tokens']} tokens")
            else:
                results[provider][model_name] = None
                print(f"✗ {model_name}: Failed")
    
    overall_progress.close()
    
    return results


def create_bar_graph(results: Dict[str, Dict[str, Dict]], output_path: str = "latency_comparison.png"):
    """Create bar graph comparing latencies with error bars."""
    data = [(f"{p}\n{m}", r["latency"], r.get("latency_std", 0.0), p) 
            for p, models in results.items() 
            for m, r in models.items() if r is not None]
    
    if not data:
        print("No valid results to plot.")
        return
    
    data.sort(key=lambda x: x[1])
    names, latencies, stds, providers = zip(*data)
    
    colors_map = {"Google": "#4285F4", "OpenAI": "#10A37F", "Anthropic": "#D4A574", "OpenRouter": "#FF6B6B"}
    colors = [colors_map.get(p, "#999999") for p in providers]
    
    plt.figure(figsize=(16, 10))
    bars = plt.barh(names, latencies, xerr=stds, color=colors, alpha=0.8, 
                    edgecolor='black', linewidth=0.5, capsize=3, error_kw={'elinewidth': 1.5})
    
    for bar, lat, std in zip(bars, latencies, stds):
        plt.text(bar.get_width() + std + 0.05, bar.get_y() + bar.get_height()/2, 
                f'{lat:.3f}s', ha='left', va='center', fontsize=9, fontweight='bold')
    
    plt.xlabel('Latency (seconds)', fontsize=12, fontweight='bold')
    plt.ylabel('Model', fontsize=12, fontweight='bold')
    plt.title(f'Model Latency Comparison (n={SAMPLE_SIZE})\n(640x480 image, same prompt as video streamer)', 
              fontsize=14, fontweight='bold', pad=20)
    plt.grid(axis='x', alpha=0.3, linestyle='--')
    
    legend = [mpatches.Patch(facecolor=c, label=p, alpha=0.8) 
              for p, c in colors_map.items() if p in providers]
    plt.legend(handles=legend, loc='lower right', fontsize=10)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"\n✓ Bar graph saved to: {output_path}")
    
    try:
        plt.show()
    except Exception:
        pass
    finally:
        plt.close()


def main():
    """Main function."""
    print("\nStarting latency benchmark...\n")
    results = run_benchmark(num_runs=SAMPLE_SIZE)
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_results = [(p, m, r["latency"], r["input_tokens"], r["output_tokens"]) 
                   for p, models in results.items() 
                   for m, r in models.items() if r is not None]
    all_results.sort(key=lambda x: x[2])
    
    if all_results:
        print("\nFastest to slowest:")
        print(f"{'Rank':<6} {'Provider':<12} {'Model':<40} {'Latency':<10} {'Input Tokens':<15} {'Output Tokens':<15}")
        print("-" * 100)
        for i, (p, m, lat, in_tok, out_tok) in enumerate(all_results, 1):
            print(f"{i:<6} {p:<12} {m:<40} {lat:<10.3f}s {in_tok:<15} {out_tok:<15}")
    
    output_path = Path(__file__).parent / "latency_comparison.png"
    create_bar_graph(results, str(output_path))
    
    json_path = Path(__file__).parent / "latency_results.json"
    with open(json_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"✓ Results saved to: {json_path}")


if __name__ == "__main__":
    main()
