# ============================================
# FTN Studio 插件库 (PluginLibrary)
#
# 内置常见扩展列表，供「插件市场」展示、搜索、下载/更新。
# 每个插件：
#   - key: 唯一标识（扩展目录名）
#   - name: 显示名
#   - desc: 简短描述
#   - repo: git 仓库 URL
#   - base: "通用" 或 具体基底 reforge / forge（标注归属；通用表示对多基底适用）
#   - group: 分类标签（用于筛选）
#   - recommended: 是否推荐
#
# 与现有插件比对，区分：
#   - 未装        → 「下载」
#   - 已装同版本   → 「已装」/ 可更新
#   - 已装旧版本   → 「更新」
#   - URL 抓的同名 → 按版本提示「回退」或「更新」
# ============================================

# 插件库条目
PLUGIN_LIBRARY = [
    # ---- 视觉辅助 / ControlNet 类（通用型） ----
    {"key": "sd-webui-controlnet", "name": "ControlNet", "desc": "姿态/深度/线稿等可控生成（核心扩展）",
     "repo": "https://github.com/Mikubill/sd-webui-controlnet", "base": "通用", "group": "控制"},
    {"key": "a1111-sd-webui-tagcomplete", "name": "Tag 自动补全", "desc": "提示词标签自动补全",
     "repo": "https://github.com/DominikDoom/a1111-sd-webui-tagcomplete", "base": "通用", "group": "提示词"},
    {"key": "sd-webui-additional-networks", "name": "Additional Networks", "desc": "LoRA/HyperNetwork 精确控制",
     "repo": "https://github.com/kohya-ss/sd-webui-additional-networks", "base": "通用", "group": "模型"},
    {"key": "sd-dynamic-prompts", "name": "Dynamic Prompts", "desc": "动态提示词 / 组合 / 随机",
     "repo": "https://github.com/adieyal/sd-dynamic-prompts", "base": "通用", "group": "提示词"},
    {"key": "a1111-sd-webui-lycoris", "name": "LyCORIS", "desc": "LyCORIS 微调 LoRA 加载",
     "repo": "https://github.com/KohakuBlueleaf/a1111-sd-webui-lycoris", "base": "通用", "group": "模型"},
    {"key": "sd-webui-reactors", "name": "ReActor", "desc": "换脸 (ReActor Face Swap)",
     "repo": "https://github.com/Gourieff/sd-webui-reactors", "base": "通用", "group": "实用"},
    {"key": "ultimate-upscale-for-automatic1111", "name": "Ultimate Upscale", "desc": "高质量放大重绘",
     "repo": "https://github.com/Coyote-A/ultimate-upscale-for-automatic1111", "base": "通用", "group": "放大"},

    # ---- Forge / reForge 通用（Forge 生态，reForge 兼容） ----
    {"key": "sd-webui-forge-controlnet", "name": "Forge ControlNet", "desc": "reForge/Forge 集成版 ControlNet",
     "repo": "https://github.com/lllyasviel/ControlNet-v1-1-nightly", "base": "通用", "group": "控制", "recommended": True},
    {"key": "sd-forge-lora", "name": "Forge LoRA", "desc": "Forge/reForge 内置 LoRA 加载增强",
     "repo": "https://github.com/lllyasviel/sd-forge-lora", "base": "通用", "group": "模型", "recommended": True},
    {"key": "sd-forge-latent-upscale", "name": "Forge Latent Upscale", "desc": "Latent 放大（Forge/reForge）",
     "repo": "https://github.com/lllyasviel/sd-forge-latent-upscale", "base": "通用", "group": "放大"},
]


def library():
    """返回内置插件库（深拷贝，避免外部修改）。"""
    import copy
    return copy.deepcopy(PLUGIN_LIBRARY)


def find_by_key(key):
    """按 key 查找插件库条目；未找到返回 None。"""
    for p in PLUGIN_LIBRARY:
        if p["key"] == key or p["name"].lower() == key.lower():
            return p
    return None


def groups():
    """返回可用分类标签集合（按出现顺序）。"""
    seen = []
    for p in PLUGIN_LIBRARY:
        if p["group"] not in seen:
            seen.append(p["group"])
    return seen
