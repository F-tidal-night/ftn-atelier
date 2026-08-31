# FTN Atelier

**生图引擎工作台** —— 面向 Windows 的 AI 生图引擎（reForge / Forge 等）启动器：
非侵入式管理引擎、开箱即用、可自由多开。

## 特性

- **开箱即用**：便携 zip 解压即用，自带嵌入式 Python 运行时，目标机无需安装 Python。
- **引擎启动即集成**：启动 webui.bat / launch.py 不再弹独立 cmd 窗口，输出自动挂载到
  内置控制台标签（每开一个自动新增、名字与引擎对应），关闭仅终止对应实例。
- **自由多开**：无互斥、无开关，任意引擎可叠加启动；端口冲突自动避开；首页显示各引擎
  内存/显存占用。
- **主引擎化管理**：默认单一「主引擎」，可指向 reForge / Forge 等；WD1.4 / LoRA / Tag 库
  按需「新增引擎」。
- **模型资产管理**：checkpoint / LoRA / Embedding / VAE 索引、预览图、LoRA 详情（触发词/基底）、
  剪切式添加、打开文件夹。
- **版本管理**：多基底（reForge / Forge）真实 git 下载 / 更新 / 回退，更新保护清单。
- **插件管理**：浏览 / 开关 / 市场（按主基底提供通用/专属插件）/ 下载 / 更新 / 卸载。
- **网络下载**：CivitAI / HuggingFace 搜索下载，自动入库。
- **主题 / 外观动画 / 自定义头图 / 日志控制台 / 疑难解答 / 环境检测 / 启动自检**。

## 使用

- **源码运行**：双击 `启动开发.bat`（需源码目录 + 系统 Python 已装后端依赖）。
- **打包发布**：双击 `打包.bat`，生成根目录 `FTN-Atelier-Portable-1.0.0.zip`。
- **重建内置运行时**（依赖变更时）：双击 `重建运行时.bat`。

## 技术栈

Electron + React + Vite + Tailwind CSS + Framer Motion ｜ Python FastAPI（内置运行时）｜ SQLite ｜ REST + WebSocket。仅面向 Windows。
