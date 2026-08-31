# ============================================
# 模型检测层测试（core/model_detect）
# 用「合成 safetensors 头部」构造样本，不下载真实模型。
# 覆盖：
#   1. 正常 SD1.5 checkpoint          2. 正常 SD2.x checkpoint
#   3. SDXL（文件名无 xl）             4. 文件名含 sdxl 但结构是 SD1（结构优先）
#   5. 无 metadata 的 SDXL             6. 带 modelspec metadata 的 SDXL
#   7. 无 metadata SDXL（结构）         8. SDXL LoRA
#   9. SD1.5 LoRA                     10. SDXL VAE
#   11. 同内容不同路径（副本）           12. 同名不同内容（不得误判重复）
#   13. .safetensors                  14. .ckpt（不读 tensor，文件名低置信度→Unknown）
#   15. 无法识别                       16. 损坏/无法读取
# ============================================

import os
import sys
import json
import struct
import shutil
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Source', 'backend')))

from core import model_detect  # noqa: E402


def make_st(path, meta=None, tensors=None):
    """生成最小合法 safetensors：8 字节长度 + JSON header（不含真实权重数据）。"""
    header = {"__metadata__": meta or {}}
    for k, shape in (tensors or {}).items():
        header[k] = {"dtype": "F32", "shape": list(shape), "data_offsets": [0, 4]}
    blob = json.dumps(header, ensure_ascii=False).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)))
        f.write(blob)
        f.write(b"\x00" * 16)


def make_broken_st(path):
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", 0))  # 头部长度 0 → 判损坏
        f.write(b"")


# ---- tensor 模板 ----
SD1_T = {
    "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
    "cond_stage_model.transformer.text_model.encoder.layers.0.self_attn.q_proj.weight": [768, 768],
    "first_stage_model.decoder.conv_out.weight": [3, 4, 1, 1],
}
SD2_T = {
    "model.diffusion_model.input_blocks.0.0.weight": [320, 4, 3, 3],
    "cond_stage_model.model.transformer.encoder.layers.0.self_attn.q_proj.weight": [1024, 1024],
    "first_stage_model.decoder.conv_out.weight": [3, 4, 1, 1],
}
SDXL_T = {
    "conditioner.embedders.0.transformer.text_model.encoder.layers.0.self_attn.q_proj.weight": [768, 768],
    "conditioner.embedders.1.transformer.text_model.encoder.layers.0.self_attn.q_proj.weight": [1280, 1280],
    "model.diffusion_model.input_blocks.0.0.weight": [1280, 4, 3, 3],
}
SDXL_LORA_T = {
    "lora_te1_text_model_encoder_layers_0_self_attn_q_proj.lora_down.weight": [4, 768],
    "lora_te2_text_model_encoder_layers_0_self_attn_q_proj.lora_down.weight": [4, 1280],
    "lora_unet_input_blocks_0_0_conv.weight.lora_down.weight": [4, 320],
}
SD1_LORA_T = {
    "lora_te_text_model_encoder_layers_0_self_attn_q_proj.lora_down.weight": [4, 768],
    "lora_unet_input_blocks_0_0_conv.weight.lora_down.weight": [4, 320],
}
VAE_T = {
    "decoder.conv_out.weight": [3, 4, 1, 1],
    "encoder.conv_in.weight": [4, 3, 3, 3],
    "mid_block.0.0.weight": [4, 4, 3, 3],
}
EMBED_T = {"string_to_param.emb_params": [768]}

MODELSPEC_SDXL = {
    "modelspec.sai_model_spec": "1.0.0",
    "modelspec.architecture": "stable-diffusion-xl-v1-base",
    "modelspec.title": "NoobAI",
}


def main():
    tmp = tempfile.mkdtemp()
    try:
        # 1) SD1.5 checkpoint（文件名无关）
        p = os.path.join(tmp, "whatever.safetensors")
        make_st(p, tensors=SD1_T)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SD1" and d["detection_source"] == "tensor_structure"
        assert d["category"] == "checkpoint" and d["format"] == "safetensors"
        print("[1] SD1.5 checkpoint 结构识别 ✅")

        # 2) SD2.x
        p = os.path.join(tmp, "anything.safetensors")
        make_st(p, tensors=SD2_T)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SD2", d
        print("[2] SD2.x 结构识别 ✅")

        # 3) SDXL 文件名不含 xl（核心回归）
        p = os.path.join(tmp, "NoobAI.safetensors")
        make_st(p, tensors=SDXL_T)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SDXL" and d["detection_source"] == "tensor_structure", d
        print("[3] 无 xl 文件名 SDXL → 结构识别 SDXL ✅")

        # 4) 文件名含 sdxl 但结构是 SD1 → 结构优先
        p = os.path.join(tmp, "sdxl_style_model.safetensors")
        make_st(p, tensors=SD1_T)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SD1", d
        print("[4] 文件名 sdxl 不覆盖结构（结构优先）✅")

        # 5/7) 无 metadata 的 SDXL（123456 文件名）
        p = os.path.join(tmp, "123456.safetensors")
        make_st(p, tensors=SDXL_T)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SDXL" and d["detection_source"] == "tensor_structure", d
        print("[5/7] 无 metadata + 无关键词文件名 → SDXL（结构）✅")

        # 6) modelspec metadata
        p = os.path.join(tmp, "modelspec_sd.safetensors")
        make_st(p, meta=MODELSPEC_SDXL, tensors=SD1_T)  # 结构故意 SD1，metadata 应优先
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "SDXL" and d["detection_source"] == "modelspec_metadata"
        assert d["base_model"] == "NoobAI", d
        print("[6] modelspec metadata → SDXL（覆盖结构证据）✅")

        # 8) SDXL LoRA
        p = os.path.join(tmp, "sd_xl_lora.safetensors")
        make_st(p, tensors=SDXL_LORA_T)
        d = model_detect.detect(p, forced_category="lora")
        assert d["category"] == "lora" and d["architecture"] == "SDXL", d
        print("[8] SDXL LoRA（te1+te2 → SDXL）✅")

        # 9) SD1.5 LoRA（metadata + 结构）
        p = os.path.join(tmp, "sd15_lora.safetensors")
        make_st(p, meta={"ss_base_model_version": "v1.5.0"}, tensors=SD1_LORA_T)
        d = model_detect.detect(p, forced_category="lora")
        assert d["architecture"] == "SD1" and d["detection_source"] == "metadata", d
        print("[9] SD1.5 LoRA（训练 metadata → SD1）✅")

        # 10) VAE（裸 encoder/decoder → vae；架构不硬猜）
        p = os.path.join(tmp, "vae_fp16.safetensors")
        make_st(p, tensors=VAE_T)
        d = model_detect.detect(p, forced_category="vae")
        assert d["category"] == "vae" and d["architecture"] == "Unknown", d
        print("[10] VAE 分类正确 / 架构 Unknown ✅")

        # 11) 同内容不同路径 → sha256 相同
        a = os.path.join(tmp, "copy_a.safetensors")
        b = os.path.join(tmp, "copy_b.safetensors")
        make_st(a, meta={"modelspec.title": "Same"}, tensors=SDXL_T)
        shutil.copyfile(a, b)
        assert model_detect.sha256_file(a) == model_detect.sha256_file(b)
        print("[11] 同内容副本 sha256 一致 ✅")

        # 12) 同名不同内容 → sha256 不同，不得误判重复
        d1, d2 = os.path.join(tmp, "dirA"), os.path.join(tmp, "dirB")
        os.makedirs(d1, exist_ok=True)
        os.makedirs(d2, exist_ok=True)
        c1 = os.path.join(d1, "same.safetensors")
        c2 = os.path.join(d2, "same.safetensors")
        make_st(c1, meta={"modelspec.title": "A"}, tensors=SD1_T)
        make_st(c2, meta={"modelspec.title": "B"}, tensors=SDXL_T)
        assert model_detect.sha256_file(c1) != model_detect.sha256_file(c2)
        print("[12] 同名不同内容 sha256 不同 ✅")

        # 14) .ckpt：不读 tensor；文件名低置信度 → Unknown
        p = os.path.join(tmp, "123456.ckpt")
        open(p, "wb").write(b"\x80\x02\x00" * 100)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["format"] == "ckpt" and d["architecture"] == "Unknown" \
            and d["detection_source"] == "unknown", d
        p2 = os.path.join(tmp, "sdxl_base.ckpt")
        open(p2, "wb").write(b"\x80\x02\x00" * 100)
        d2 = model_detect.detect(p2, forced_category="checkpoint")
        assert d2["architecture"] == "SDXL" and d2["detection_source"] == "filename", d2
        print("[14] .ckpt 处理：无关键词→Unknown / 关键词→filename 低置信度 ✅")

        # 15) 无法识别（无结构无元数据无关键词）
        p = os.path.join(tmp, "random.safetensors")
        make_st(p, tensors={"weird.key": [2, 2]})
        d = model_detect.detect(p, forced_category="other")
        assert d["architecture"] == "Unknown" and d["category"] == "other", d
        print("[15] 无法识别 → Unknown/other ✅")

        # 16) 损坏文件
        p = os.path.join(tmp, "broken.safetensors")
        make_broken_st(p)
        d = model_detect.detect(p, forced_category="checkpoint")
        assert d["architecture"] == "Unknown" and d["error"], d
        print("[16] 损坏文件 → Unknown + error 提示 ✅")

        print("\n=== model_detect 16 项全部通过 ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
