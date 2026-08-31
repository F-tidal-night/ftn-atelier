# ============================================
# Update Engine · UpdateService（编排层）
#
# 把「检测结果 → 断点恢复 → 选源 → 下载(实时进度) → 校验 → 就绪」串成一条流程，
# 产出与现有后台任务兼容的状态流：yield (message, percent)。
# 消息为富文本，前端轮询任务日志即可看到「寻找源 / 连接 / 下载进度/速度/ETA / 切换 / 校验」。
# ============================================

import os

from core.update.models import DownloadTask
from core.update import resume as resume_mod
from core.update.downloader import download_generator
from core.update.verifier import verify


def _mb(n):
    return n / 1048576.0


class UpdateService:
    """更新流程编排器（单例见 core.update.update_service）。"""

    def start_download(self, task):
        """下载流程生成器：yield (message, percent)。失败抛 RuntimeError（任务转 error）。"""
        # 0) 断点恢复
        part_path, start_byte = resume_mod.find_resume(os.path.dirname(task.part_path), task)
        if start_byte > 0:
            yield f"发现未完成的下载（{_mb(start_byte):.1f} MB），正在从断点继续…", 2
        else:
            if part_path and os.path.isfile(part_path):
                # 有 .part 但版本/URL 不一致：弃用（不删，避免误删用户数据由清理逻辑处理）
                yield "检测到不匹配的旧下载片段，将重新下载", 1
            yield "正在寻找可用下载源…", 1

        # 1) 下载（内部含探测/切源/续传；产出 DownloadProgress）
        final = None
        for prog in download_generator(task, start_byte=start_byte):
            if prog.phase == "probing":
                yield prog.message, 2
            elif prog.phase == "connecting":
                yield prog.message, 3
            elif prog.phase == "downloading":
                pct = int(prog.percent)
                speed = _mb(prog.speed_bps)
                avg = _mb(prog.avg_speed_bps)
                eta = prog.eta_sec
                msg = (f"正在下载 {_mb(prog.received):.1f} / {_mb(prog.total):.1f} MB · {pct}%"
                       f" · {speed:.1f} MB/s" + (f" · 预计剩余 {int(eta)} 秒" if eta > 0 else ""))
                yield msg, pct
            elif prog.phase == "switching":
                yield prog.message, max(3, int(prog.percent))
            elif prog.phase == "done":
                final = task.part_path
            elif prog.phase == "error":
                raise RuntimeError(prog.message)

        if not final or not os.path.isfile(final):
            raise RuntimeError("下载未完成")

        # 2) 校验（未通过绝不进入安装阶段）
        yield "下载完成，正在校验更新包…", 96
        result = verify(task, part_path=final)
        if not result.ok:
            raise RuntimeError(f"更新包校验失败：{result.reason}（文件已保留，可重试）")

        # 3) 校验通过 → .part → .zip
        try:
            os.replace(final, task.dest_zip)
        except OSError as e:
            raise RuntimeError(f"更新包就位失败：{e}")
        yield "校验通过，更新包已就绪（将自动备份并替换程序）", 100
