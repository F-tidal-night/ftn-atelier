# ============================================
# FTN Studio 全局配置模型 AppConfig
#
# 对应蓝图「三、AppConfig配置模型提前设计」：
#   M1 定义数据结构，M3 设置页面只是它的可视化编辑。
#
# 预留四类：
#   1. 引擎路径（各工具根目录）
#   2. 启动参数（显存/浏览器/GPU/端口/自定义）
#   3. 环境配置（Python/CUDA/镜像源）
#   4. 用户偏好（主题/默认模型/日志级别）
# ============================================

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class EnginePaths(BaseModel):
    """各引擎/工具根目录（蓝图可切换启动模式）。"""

    reforge: str = Field(
        "", description="reForge 根目录（webui 所在目录）"
    )
    wd_webui: str = Field(
        "", description="WD1.4-WebUI 根目录"
    )
    lora_scripts: str = Field(
        "", description="lora-scripts 根目录"
    )
    tag_db: str = Field(
        "", description="FTN-tag 库根目录"
    )

    # 未来扩展引擎
    extra: Dict[str, str] = Field(
        default_factory=dict, description="其他引擎路径（键名=引擎代号）"
    )


class StartArgs(BaseModel):
    """启动参数（对应蓝图高级选项）。"""

    gpu_index: int = Field(0, description="生成引擎/显卡选择(主显卡索引)")
    gpu_ids: List[int] = Field(default_factory=list, description="使用多 GPU(索引列表,空=单卡)")
    vram_mode: str = Field(
        "auto", description="显存模式: auto|low|high"
    )
    open_browser: bool = Field(True, description="启动后打开浏览器")
    port: int = Field(
        7860, description="webui 端口（ReForge 默认）"
    )

    # GPU 其他参数
    use_cpu: bool = Field(
        False, description="强制 CPU 模式(调试用)"
    )

    # 自定义启动参数（附加到 webui 命令）
    custom_args: List[str] = Field(
        default_factory=list, description="自定义额外启动参数"
    )


class EnvConfig(BaseModel):
    """环境配置。"""

    python_path: str = Field(
        "", description="Python 解释器路径(留空=自动探测)"
    )
    cuda_info: Dict[str, str] = Field(
        default_factory=dict, description="CUDA 版本信息(key=driver|runtime|cudnn)"
    )
    use_py_mirror: bool = Field(
        True, description="Py 国内镜像下载模式(默认开)"
    )
    use_git_mirror: bool = Field(
        True, description="Git 国内镜像下载模式(默认开)"
    )
    use_hf_mirror: bool = Field(
        True, description="HuggingFace 国内镜像下载模式(默认开)"
    )
    # 镜像源自定义
    pip_mirror: str = Field(
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        description="PyPI 镜像源",
    )
    hf_endpoint: str = Field(
        "https://hf-mirror.com", description="HuggingFace 镜像端点"
    )
    git_mirror: str = Field(
        "https://ghproxy.com/", description="Git/GitHub 下载镜像前缀（留空则不启用）"
    )


class UserPreference(BaseModel):
    """用户偏好。"""

    theme: str = Field(
        "dark", description="UI 主题标识（亮/暗/具体主题）"
    )
    hero_image: str = Field(
        "", description="首页自定义头图路径（留空=默认渐变）"
    )
    language: str = Field(
        "system", description="语言: system|zh-CN|en-US 等"
    )
    default_model: str = Field(
        "", description="默认 Checkpoint 模型名"
    )
    default_workflow: str = Field(
        "", description="默认工作流标识"
    )
    log_level: str = Field(
        "INFO", description="日志级别: DEBUG|INFO|WARN|ERROR"
    )
    ambient_effect: str = Field(
        "none",
        description="外观动画效果: none|particles|light|breath（窗口非活动时自动暂停）",
    )


class ApiKeys(BaseModel):
    """网站 API 凭据（CivitAI / HuggingFace 下载所需；A 阶段仅存储 + 界面提示）。

    - CivitAI：https://civitai.com/user/account
    - HuggingFace：https://huggingface.co/settings/tokens
    """

    civitai_api_key: str = Field(
        "", description="CivitAI API Key"
    )
    huggingface_token: str = Field(
        "", description="HuggingFace Access Token"
    )


class SelfCheckConfig(BaseModel):
    """软件修复更新相关配置。

    更新源（GitHub owner/repository）由配置项提供，开发环境留空则跳过更新检查，
    不硬编码 / 不假设仓库地址。正式发布时再填写真实 owner/repository。
    """

    run_on_startup: bool = Field(
        True, description="启动软件前是否执行自检引导"
    )
    check_update_on_startup: bool = Field(
        True, description="启动软件前是否自动检测 FTN Atelier 版本更新"
    )
    # 更新源（可配置；owner 与 repo 同时为空 = 跳过更新检查）
    update_owner: str = Field(
        "", description="更新源 GitHub 仓库 owner（正式发布时填写；留空跳过更新检查）"
    )
    update_repo: str = Field(
        "", description="更新源 GitHub 仓库 repo 名（空则跳过更新检查）"
    )
    update_mirror: str = Field(
        "", description="更新镜像地址（可选；优先于 GitHub，留空走 GitHub releases/latest）"
    )


class AppConfig(BaseModel):
    """FTN Studio 全局配置（M1 定义，M3 可视化编辑）。"""

    version: int = Field(1, description="配置文件版本（用于迁移）")
    engine_paths: EnginePaths = Field(default_factory=EnginePaths)
    start_args: StartArgs = Field(default_factory=StartArgs)
    env: EnvConfig = Field(default_factory=EnvConfig)
    preference: UserPreference = Field(default_factory=UserPreference)
    api_keys: ApiKeys = Field(default_factory=ApiKeys)
    selfcheck: SelfCheckConfig = Field(default_factory=SelfCheckConfig)

    # 首页快捷文件夹（默认 5 个，可改名/重指定路径，不可删除）
    home_folders: List[dict] = Field(
        default_factory=lambda: [
            {"key": "root", "label": "主引擎根目录", "mode": "root", "custom_path": ""},
            {"key": "txt1", "label": "文生图 · 单图", "mode": "txt", "custom_path": ""},
            {"key": "txtg", "label": "文生图 · 网格", "mode": "txt_grid", "custom_path": ""},
            {"key": "img1", "label": "图生图 · 单图", "mode": "img", "custom_path": ""},
            {"key": "imgg", "label": "图生图 · 网格", "mode": "img_grid", "custom_path": ""},
        ],
        description="首页快捷文件夹配置（默认 5 个，不可删除）",
    )

    check_deps: bool = Field(
        True, description="软件依赖完整性检测(默认开)"
    )
    detect_conflict: bool = Field(
        True, description="组件冲突检测(默认开)"
    )
    detect_dup_extension: bool = Field(
        True, description="重复插件检测(默认开)"
    )

    # 输出目录「不分日期」：后台整理（日期子目录自动上提）
    output_auto_organize: bool = Field(
        False, description="输出目录自动整理（把日期子目录内容上提，实现不分日期）"
    )

    # venv 共享策略：小版本复用共享环境（默认开），大版本依赖变化再询问重建
    venv_share: bool = Field(
        True, description="多版本间共享 venv 环境（小版本复用；大版本依赖大改自动重建）"
    )
