# ============================================
# FTN Studio 模型检测层（独立、可测试）
#
# 职责：统一判定模型的
#   category（分类） / architecture（架构） / format（格式）
#   base_model（具体基础模型/系列） / detection_source / confidence
#   sha256（内容指纹，由调用方缓存复用）
#
# 检测优先级（严禁文件名覆盖高置信度结构判断）：
#   1. modelspec 标准 metadata（high）
#   2. LoRA 训练 metadata（medium）
#   3. safetensors tensor keys / shapes（high/medium）
#   4. 路径分类（category 用，reForge 目录约定）
#   5. 文件名（low，仅兜底；不允许决定架构）
#   6. Unknown（允许存在，不硬猜）
#
# .ckpt 约定：不加载 torch、不读 pickle tensor；按
#   metadata → 文件名（low）→ Unknown 处理，绝不按文件体积猜架构。
# ============================================

import os
import re
import json
import struct
import hashlib

ARCH_UNKNOWN = "Unknown"
ARCH_SD1 = "SD1"
ARCH_SD2 = "SD2"
ARCH_SDXL = "SDXL"
ARCH_SDXL_REFINER = "SDXL_Refiner"
ARCH_SD3 = "SD3"
ARCH_FLUX = "Flux"

# 目录名 → 分类（与 asset_manager._DIR_TYPE_MAP 一致）
_DIR_CATEGORY = {
    "stable-diffusion": "checkpoint",
    "lora": "lora",
    "lora_plugin": "lora_plugin",
    "embeddings": "embedding",
    "embedding": "embedding",
    "textual_inversion": "embedding",
    "vae": "vae",
}


def read_safetensors_header(path):
    """读取 safetensors 头部（8 字节长度 + JSON header），返回 (metadata, tensors)。

    只读头部，不加载权重；损坏/超长头部返回空。
    """
    if not str(path).lower().endswith(".safetensors") or not os.path.isfile(path):
        return {}, {}
    try:
        with open(path, "rb") as f:
            nbytes = struct.unpack("<Q", f.read(8))[0]
            if nbytes <= 0 or nbytes > 64 * 1024 * 1024:
                return {}, {}
            header = json.loads(f.read(nbytes))
        if not isinstance(header, dict):
            return {}, {}
        meta = header.get("__metadata__") or {}
        tensors = {k: v for k, v in header.items() if k != "__metadata__"}
        return meta if isinstance(meta, dict) else {}, tensors
    except Exception:
        return {}, {}


def sha256_file(path, chunk=1024 * 1024):
    """整文件 SHA256（分块读，不整载内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _map_arch_string(s):
    """modelspec.architecture 等标准架构字符串 → 统一架构。"""
    s = (s or "").lower()
    if "xl" in s and "refiner" in s:
        return ARCH_SDXL_REFINER
    if "xl" in s:
        return ARCH_SDXL
    if "flux" in s:
        return ARCH_FLUX
    if "sd3" in s or "stable-diffusion-3" in s:
        return ARCH_SD3
    if "stable-diffusion-2" in s or "sd2" in s:
        return ARCH_SD2
    if "stable-diffusion-v1" in s or "sd1" in s or "v1" in s:
        return ARCH_SD1
    return ARCH_UNKNOWN


def _arch_from_training(meta_value):
    """LoRA 训练 metadata（ss_base_model_version / ss_sd_model_name）→ 架构。"""
    s = (str(meta_value or "")).lower()
    if any(k in s for k in ("xl", "sdxl", "pony", "illustrious", "noobai", "juggernaut_xl")):
        return ARCH_SDXL
    if "flux" in s:
        return ARCH_FLUX
    if "sd3" in s or "stable-diffusion-3" in s or "3.5" in s:
        return ARCH_SD3
    if re.match(r"^2(\.| )", s) or "sd2" in s:
        return ARCH_SD2
    if re.match(r"^1(\.| )", s) or "sd1" in s or "v1" in s:
        return ARCH_SD1
    return ARCH_UNKNOWN


def _arch_from_filename(filename):
    """文件名兜底（low）。只认明确关键词；无关键词 → Unknown。"""
    s = (filename or "").lower()
    if any(k in s for k in ("xl", "sdxl", "pony", "illustrious", "noobai")):
        return ARCH_SDXL
    if "flux" in s:
        return ARCH_FLUX
    if "sd3" in s or "stable-diffusion-3" in s:
        return ARCH_SD3
    if "sd2" in s or re.search(r"(^|[^0-9])2\.[0-9]", s):
        return ARCH_SD2
    if "sd1" in s or re.search(r"(^|[^0-9])1\.[0-9]", s) or re.search(r"v1[.\-]", s):
        return ARCH_SD1
    return ARCH_UNKNOWN


def _arch_from_tensors(tensors):
    """tensor keys/shapes → 架构（不加载权重）。返回 (arch, confidence)。"""
    keys = list(tensors.keys())
    joined = " ".join(keys)
    if any(k.startswith("lora_") for k in keys):
        # LoRA：双文本编码器（te1+te2）→ SDXL；单编码器 → SD1
        if "lora_te2" in joined:
            return ARCH_SDXL, "high"
        if "lora_te_text_model" in joined or "lora_te1" in joined:
            return ARCH_SD1, "medium"
        return ARCH_UNKNOWN, "low"
    if "joint_transformer_blocks" in joined or "model.diffusion_model.joint_blocks" in joined:
        return ARCH_SD3, "high"
    if "transformer_blocks" in joined and "conditioner.embedders" not in joined \
            and any(k in joined for k in ("txt_in", "img_in", "guidance_embedder")):
        return ARCH_FLUX, "high"
    if "conditioner.embedders.1" in joined:
        return ARCH_SDXL, "high"
    if "conditioner.embedders.0" in joined:
        return ARCH_SDXL_REFINER, "medium"
    if "cond_stage_model.model" in joined:
        return ARCH_SD2, "high"
    if "cond_stage_model.transformer" in joined:
        return ARCH_SD1, "high"
    return ARCH_UNKNOWN, "low"


def classify_by_tensors(tensors):
    """按 tensor keys 判分类别（无路径依据时兜底）。返回 category 或 None。"""
    keys = list(tensors.keys())
    joined = " ".join(keys)
    if any(k.startswith("lora_") for k in keys):
        return "lora"
    if "control_model" in joined or any(k.startswith("control_") for k in keys):
        return "controlnet"
    if "string_to_param" in joined:
        return "embedding"
    # VAE：裸 encoder/decoder/mid_block（无 model./cond_stage/first_stage 前缀）
    bare = all(
        not k.startswith(("model.", "cond_stage_model.", "first_stage_model.", "lora_", "control_"))
        for k in keys
    )
    if bare and ("decoder.conv_out" in joined or "encoder.conv_in" in joined):
        return "vae"
    if ("model.diffusion_model" in joined or "conditioner.embedders" in joined
            or "transformer_blocks" in joined):
        return "checkpoint"
    return None


def _category_from_dir(path):
    """按父目录名判分类别（reForge 目录约定）。"""
    parent = os.path.basename(os.path.dirname(str(path) or "")).lower()
    return _DIR_CATEGORY.get(parent)


def _detect_base_model(meta, filename):
    """具体基础模型/系列（NoobAI / Pony / Illustrious…）：只信 metadata，不猜。"""
    if not isinstance(meta, dict) or not meta:
        return ""
    for k in ("modelspec.title", "ss_sd_model_name", "ss_base_model_version"):
        v = meta.get(k)
        if v:
            return str(v)[:120]
    return ""


def detect(file_path, forced_category=None, cached=None):
    """统一模型检测入口。返回检测结果字典。cached 可携带已缓存 sha256。"""
    path = str(file_path or "")
    lower = path.lower()
    if lower.endswith(".safetensors"):
        fmt = "safetensors"
    elif lower.endswith(".ckpt"):
        fmt = "ckpt"
    elif lower.endswith((".pt", ".pth")):
        fmt = "pt"
    elif lower.endswith(".bin"):
        fmt = "bin"
    else:
        fmt = "other"

    meta, tensors = ({}, {})
    if fmt == "safetensors":
        meta, tensors = read_safetensors_header(path)

    # ---- category ----
    category = forced_category or _category_from_dir(path)
    if not category:
        category = classify_by_tensors(tensors) or "other"

    # ---- architecture 级联 ----
    filename = os.path.basename(path)
    arch, source, confidence = ARCH_UNKNOWN, "unknown", "low"
    if isinstance(meta, dict):
        spec = meta.get("modelspec.sai_model_spec") or meta.get("modelspec.architecture")
        if spec:
            a = _map_arch_string(meta.get("modelspec.architecture"))
            if a != ARCH_UNKNOWN:
                arch, source, confidence = a, "modelspec_metadata", "high"
    if arch == ARCH_UNKNOWN and isinstance(meta, dict):
        bm = meta.get("ss_base_model_version") or meta.get("ss_sd_model_name") or ""
        if bm:
            a = _arch_from_training(bm)
            if a != ARCH_UNKNOWN:
                arch, source, confidence = a, "metadata", "medium"
    if arch == ARCH_UNKNOWN and tensors:
        a, conf = _arch_from_tensors(tensors)
        if a != ARCH_UNKNOWN:
            arch, source, confidence = a, "tensor_structure", conf
    if arch == ARCH_UNKNOWN:
        a = _arch_from_filename(filename)
        if a != ARCH_UNKNOWN:
            arch, source, confidence = a, "filename", "low"

    error = None
    if fmt == "safetensors" and os.path.isfile(path) and not meta and not tensors:
        error = "无法读取 safetensors 头部（可能损坏）"

    return {
        "category": category,
        "architecture": arch,
        "format": fmt,
        "base_model": _detect_base_model(meta, filename),
        "detection_source": source,
        "confidence": confidence,
        "metadata": json.dumps(meta, ensure_ascii=False, default=str)[:8000] if meta else None,
        "sha256": (cached or {}).get("sha256") or None,
        "error": error,
    }
