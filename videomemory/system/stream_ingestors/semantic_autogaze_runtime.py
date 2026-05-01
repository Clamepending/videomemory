"""Runtime loader for the released semantic-autogaze scorer.

This module is the production/shared boundary for the trained patch scorer.
It keeps heavyweight dependencies lazy so VideoMemory can start even when the
optional semantic-filter stack is not installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import urllib.request

import cv2
import numpy as np


GRID = 14
IM_MEAN = (0.485, 0.456, 0.406)
IM_STD = (0.229, 0.224, 0.225)
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
INSTALL_COMMAND = "uv pip install torch timm open_clip_torch"
MODEL_NAME = "phase19-atto"
RELEASE_TAG = "v0.6.0-phase19-pi-demo"
CHECKPOINT_NAME = "phase19b_convnext_atto_perquery_best_v060.pt"
RELEASE_URL = (
    "https://github.com/Clamepending/semantic-autogaze/releases/download/"
    f"{RELEASE_TAG}/{CHECKPOINT_NAME}"
)
DEFAULT_CHECKPOINT_PATH = Path.home() / ".cache" / "videomemory" / "semantic-autogaze" / CHECKPOINT_NAME

_TIMM_BACKBONES = {
    "convnext-atto": "convnext_atto.d2_in1k",
    "convnext-femto": "convnext_femto.d1_in1k",
    "convnext-pico": "convnext_pico.d1_in1k",
    "convnext-nano": "convnext_nano.in12k_ft_in1k",
    "convnext-tiny": "convnext_tiny.in12k_ft_in1k",
    "fastvit-t8": "fastvit_t8.apple_in1k",
    "mobilevit-xs": "mobilevit_xs.cvnets_in1k",
    "repvit-m1": "repvit_m1.dist_in1k",
    "efficientformerv2-s0": "efficientformerv2_s0.snap_dist_in1k",
}


@dataclass
class SemanticAutogazeRuntime:
    """Loaded scorer runtime plus reusable text encoder."""

    torch: object
    functional: object
    backbone: object
    head: object
    multi_query: object
    clip_model: object
    clip_tokenizer: object
    mean: tuple[float, float, float]
    std: tuple[float, float, float]
    kind: str
    device: object

    def encode_texts(self, keywords: list[str]):
        with self.torch.no_grad():
            tokens = self.clip_tokenizer(keywords).to(self.device)
            return self.functional.normalize(self.clip_model.encode_text(tokens), dim=-1)

    def score_image(self, image_rgb: np.ndarray, keywords: list[str]) -> np.ndarray:
        return self.score_image_embeddings(image_rgb, self.encode_texts(keywords))

    def score_image_embeddings(self, image_rgb: np.ndarray, text_embs) -> np.ndarray:
        frame_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
        with self.torch.no_grad():
            inputs = _normalize_frame(frame_bgr, self.mean, self.std, self.device, self.torch, self.functional)
            if self.kind == "clip-visual":
                _, features = self.clip_model.visual(inputs)
            else:
                features = _adapt_features(self.backbone.forward_features(inputs), self.functional)
            scores = self.multi_query(features, text_embs, reduce="none", apply_sigmoid=True)
        return scores.squeeze(0).detach().cpu().numpy().T.astype(np.float32)


def load_runtime(checkpoint_path: Path | None = None, device_name: str = "auto") -> SemanticAutogazeRuntime:
    """Load the released scorer and matching CLIP text encoder."""

    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as functional
        import open_clip
        import timm
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "torch/timm/open_clip_torch"
        raise RuntimeError(
            f"Missing optional dependency '{missing_name}'. Install the trained-model backend with: {INSTALL_COMMAND}"
        ) from exc

    device = _select_device(torch, device_name)
    checkpoint = _ensure_checkpoint(checkpoint_path or DEFAULT_CHECKPOINT_PATH)
    backbone, head, mean, std, kind = _build_model(checkpoint, device, torch=torch, nn=nn, timm=timm)
    multi_query = _build_multi_query_scorer(head, torch)

    clip_model, _, _ = open_clip.create_model_and_transforms("ViT-B-16", pretrained="openai")
    clip_tokenizer = open_clip.get_tokenizer("ViT-B-16")
    clip_model = clip_model.to(device).eval()
    if kind == "clip-visual":
        clip_model.visual.output_tokens = True

    return SemanticAutogazeRuntime(
        torch=torch,
        functional=functional,
        backbone=backbone,
        head=head,
        multi_query=multi_query,
        clip_model=clip_model,
        clip_tokenizer=clip_tokenizer,
        mean=mean,
        std=std,
        kind=kind,
        device=device,
    )


def _ensure_checkpoint(path: Path) -> Path:
    if path.exists():
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(RELEASE_URL, str(path))
    except Exception as url_error:
        try:
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    RELEASE_TAG,
                    "--repo",
                    "Clamepending/semantic-autogaze",
                    "--pattern",
                    CHECKPOINT_NAME,
                    "--dir",
                    str(path.parent),
                    "--clobber",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as gh_error:
            raise RuntimeError(
                "Could not download the semantic-autogaze checkpoint from the release URL "
                "or via authenticated `gh release download`."
            ) from gh_error
        if not path.exists():
            raise RuntimeError(f"`gh release download` completed, but {path} was not created") from url_error
    return path


def _select_device(torch, device_name: str):
    if device_name == "auto":
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    return torch.device(device_name)


def _build_model(checkpoint_path: Path, device, *, torch, nn, timm):
    checkpoint = torch.load(str(checkpoint_path), map_location=device, weights_only=False)
    checkpoint_args = checkpoint.get("args", {}) or {}
    arch = checkpoint_args.get("model") if isinstance(checkpoint_args, dict) else None
    arch = arch or MODEL_NAME

    patch_dim = checkpoint.get("embed_dim", 768)
    if "head" in checkpoint and "patch_proj.0.weight" in checkpoint["head"]:
        patch_dim = int(checkpoint["head"]["patch_proj.0.weight"].shape[1])
    if arch == "v1":
        patch_dim = 768

    head = _build_text_scorer_head_class(torch, nn)(
        patch_dim=patch_dim,
        text_dim=512,
        hidden_dim=checkpoint_args.get("head_hidden_dim", 384),
        n_attn_heads=checkpoint_args.get("head_attn_heads", 6),
        n_attn_layers=checkpoint_args.get("head_attn_layers", 2),
        grid_size=GRID,
        use_spatial=checkpoint_args.get("head_use_spatial", True),
    ).to(device).eval()
    head.load_state_dict(checkpoint["head"])
    head._siglip_t = 1.0
    head._siglip_bias = 0.0
    head._siglip_bias_mlp = None
    if "sb" in checkpoint:
        sb = checkpoint["sb"]
        log_t = sb["log_t"].item() if hasattr(sb["log_t"], "item") else float(sb["log_t"])
        head._siglip_t = float(np.exp(log_t))
        if "bias" in sb:
            bias = sb["bias"].item() if hasattr(sb["bias"], "item") else float(sb["bias"])
            head._siglip_bias = float(bias)
        elif "bias_mlp.0.weight" in sb:
            bias_mlp = nn.Sequential(
                nn.Linear(512, 64),
                nn.GELU(),
                nn.Linear(64, 1),
            ).to(device).eval()
            bias_mlp.load_state_dict(
                {
                    key.replace("bias_mlp.", "", 1): value
                    for key, value in sb.items()
                    if key.startswith("bias_mlp.")
                }
            )
            head._siglip_bias_mlp = bias_mlp

    if arch == "v1":
        return None, head, CLIP_MEAN, CLIP_STD, "clip-visual"

    backbone_name = _TIMM_BACKBONES.get(arch) or checkpoint.get("backbone", "")
    if not backbone_name:
        backbone_name = "vit_tiny_patch16_224.augreg_in21k_ft_in1k" if arch == "v2-tiny" else "mobilenetv3_small_100"
    backbone = timm.create_model(backbone_name, pretrained=True, num_classes=0).to(device).eval()
    return backbone, head, IM_MEAN, IM_STD, "timm"


def _build_text_scorer_head_class(torch, nn):
    class TextScorerHead(nn.Module):
        def __init__(
            self,
            patch_dim=768,
            text_dim=512,
            hidden_dim=384,
            n_attn_heads=6,
            n_attn_layers=2,
            grid_size=14,
            use_spatial=True,
        ):
            super().__init__()
            self.grid_size = grid_size
            self.patch_proj = nn.Sequential(nn.Linear(patch_dim, hidden_dim), nn.GELU(), nn.LayerNorm(hidden_dim))
            self.pos_embed = nn.Parameter(torch.randn(1, grid_size * grid_size, hidden_dim) * 0.02)
            self.self_attn_layers = nn.ModuleList(
                [
                    nn.ModuleDict(
                        {
                            "attn": nn.MultiheadAttention(hidden_dim, n_attn_heads, batch_first=True),
                            "norm1": nn.LayerNorm(hidden_dim),
                            "ffn": nn.Sequential(
                                nn.Linear(hidden_dim, hidden_dim * 2),
                                nn.GELU(),
                                nn.Linear(hidden_dim * 2, hidden_dim),
                            ),
                            "norm2": nn.LayerNorm(hidden_dim),
                        }
                    )
                    for _ in range(n_attn_layers)
                ]
            )
            self.text_proj = nn.Sequential(nn.Linear(text_dim, hidden_dim), nn.GELU(), nn.LayerNorm(hidden_dim))
            self.cross_attn = nn.MultiheadAttention(hidden_dim, n_attn_heads, batch_first=True)
            self.cross_norm = nn.LayerNorm(hidden_dim)
            self.score_mlp = nn.Sequential(nn.Linear(hidden_dim, hidden_dim // 2), nn.GELU(), nn.Linear(hidden_dim // 2, 1))
            self.spatial = (
                nn.Sequential(
                    nn.Conv2d(1, 64, kernel_size=3, padding=1),
                    nn.GELU(),
                    nn.Conv2d(64, 64, kernel_size=3, padding=1),
                    nn.GELU(),
                    nn.Conv2d(64, 1, kernel_size=3, padding=1),
                )
                if use_spatial
                else None
            )

    return TextScorerHead


def _build_multi_query_scorer(head, torch):
    class MultiQueryScorer:
        def __init__(self, scorer_head):
            self.head = scorer_head
            self.grid_size = scorer_head.grid_size

        @torch.no_grad()
        def encode_patches(self, patch_feats):
            h = self.head
            x = h.patch_proj(patch_feats) + h.pos_embed
            for layer in h.self_attn_layers:
                residual = x
                x = layer["norm1"](x)
                attended, _ = layer["attn"](x, x, x)
                x = residual + attended
                residual = x
                x = layer["norm2"](x)
                x = residual + layer["ffn"](x)
            return x

        @torch.no_grad()
        def __call__(self, patches, text_embs, reduce="max", apply_sigmoid=True):
            x = self.encode_patches(patches)
            h = self.head
            batch_size, patch_count, hidden_dim = x.shape
            query_count = text_embs.shape[0]
            x_rep = x.unsqueeze(1).expand(batch_size, query_count, patch_count, hidden_dim)
            x_rep = x_rep.reshape(batch_size * query_count, patch_count, hidden_dim)
            text_rep = text_embs.unsqueeze(0).expand(batch_size, query_count, -1)
            text_rep = text_rep.reshape(batch_size * query_count, -1)
            q_proj = h.text_proj(text_rep).unsqueeze(1)
            cross_out, _ = h.cross_attn(x_rep, q_proj, q_proj)
            x_q = h.cross_norm(x_rep + cross_out)
            scores = h.score_mlp(x_q).squeeze(-1)
            if h.spatial is not None:
                grids = scores.reshape(batch_size * query_count, 1, self.grid_size, self.grid_size)
                scores = (grids + h.spatial(grids)).reshape(batch_size * query_count, patch_count)
            scores = scores.reshape(batch_size, query_count, patch_count)
            if hasattr(h, "_siglip_t"):
                if getattr(h, "_siglip_bias_mlp", None) is not None:
                    bias = h._siglip_bias_mlp(text_embs).reshape(1, query_count, 1)
                    scores = scores * h._siglip_t + bias
                elif h._siglip_t != 1.0 or h._siglip_bias != 0.0:
                    scores = scores * h._siglip_t + h._siglip_bias
            if apply_sigmoid:
                scores = torch.sigmoid(scores)
            if reduce == "max":
                return scores.amax(dim=1)
            if reduce == "min":
                return scores.amin(dim=1)
            if reduce == "mean":
                return scores.mean(dim=1)
            if reduce == "sum":
                return scores.sum(dim=1)
            if reduce == "softmax":
                weights = scores.softmax(dim=1)
                return (weights * scores).sum(dim=1)
            return scores

    return MultiQueryScorer(head)


def _normalize_frame(frame_bgr: np.ndarray, mean, std, device, torch, functional, size=224):
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    tensor = torch.from_numpy(rgb).permute(2, 0, 1).float().to(device) / 255.0
    tensor = functional.interpolate(tensor.unsqueeze(0), size=(size, size), mode="bilinear", align_corners=False)
    mean_t = torch.tensor(mean, device=device)[None, :, None, None]
    std_t = torch.tensor(std, device=device)[None, :, None, None]
    return (tensor - mean_t) / std_t


def _adapt_features(features, functional):
    if features.dim() == 4:
        features = functional.interpolate(features, size=(GRID, GRID), mode="bilinear", align_corners=False)
        return features.permute(0, 2, 3, 1).reshape(features.shape[0], GRID * GRID, features.shape[1])
    if features.shape[1] == 197:
        return features[:, 1:, :]
    return features
