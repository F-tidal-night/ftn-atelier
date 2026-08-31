# ============================================
# 引擎主引擎 / 自定义路径 / 接管安装例程 回归测试
#
# 覆盖（均为沙箱，不碰真实 reForge / 不发网络）：
#   1. 自定义引擎路径持久化（dict(extra) 副本 bug）
#   2. 新增引擎自动生成内部 key（中文 / 英文 / 重名）
#   3. 主引擎置顶（primary 永远第一个）
#   4. takeover 预检：外部目录基底解析 / 仓库 / 分支（monkeypatch _new_task，不真正启动任务）
#   5. _install_job 成功路径：新程序 + 用户数据还原 + .ftn/engine.json
#   6. _install_job 校验失败：引擎目录原封不动
#   7. _install_job 还原失败：用户数据备份被救出临时目录（绝不随 tmp 删除）
# ============================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.db import db  # noqa: E402
from core.config_manager import config_manager  # noqa: E402
from core.engine_registry import engine_registry  # noqa: E402
from core.version_manager import VersionManager, _base_of_path, ENGINES_ROOT  # noqa: E402


def _make_zip(src, dest):
    with zipfile.ZipFile(dest, "w") as zf:
        for root, _dirs, files in os.walk(src):
            for f in files:
                full = os.path.join(root, f)
                zf.write(full, os.path.relpath(full, src))


def _snapshot_state():
    return {
        "engine_custom": db.get_meta("engine_custom", None),
        "primary_base": db.get_meta("primary_base", None),
        "extra": dict(config_manager.load().engine_paths.extra),
    }


def _restore_state(st):
    if st["engine_custom"] is None:
        db.execute("DELETE FROM app_meta WHERE key = 'engine_custom'")
    else:
        db.set_meta("engine_custom", st["engine_custom"])
    if st["primary_base"] is None:
        db.execute("DELETE FROM app_meta WHERE key = 'primary_base'")
    else:
        db.set_meta("primary_base", st["primary_base"])
    cfg = config_manager.load()
    cfg.engine_paths.extra = dict(st["extra"])
    config_manager.save(cfg)


def main():
    st = _snapshot_state()
    vm = VersionManager()
    base = tempfile.mkdtemp(prefix="ftn_regress_")
    clone = os.path.join(base, "stable-diffusion-webui-reForge-test")
    os.makedirs(clone)
    open(os.path.join(clone, "webui.bat"), "w").write("@echo off\n")
    open(os.path.join(clone, "launch.py"), "w").write("print(1)\n")
    try:
        # ---------- 1) 自定义引擎路径持久化 ----------
        r = engine_registry.add_engine("", "回归测试引擎", "webui", root="")
        assert r["ok"], r
        key = r["key"]
        r = engine_registry.set_path(key, clone)
        assert r["ok"], r
        assert config_manager.load().engine_paths.extra.get(key) == clone
        eng = next((e for e in engine_registry.list_engines() if e["key"] == key), None)
        assert eng and eng["root"] == clone and "webui.bat" in eng["entry"], eng
        print("[1] 自定义引擎路径持久化 + 入口自动检测 OK")

        # ---------- 2) 自动 key（英文 / 重名）----------
        r2 = engine_registry.add_engine("", "Forge 测试", "webui", root=clone)
        assert r2["ok"] and r2["key"] == "forge", r2
        r3 = engine_registry.add_engine("", "Forge 测试", "webui", root=clone)
        assert r3["ok"] and r3["key"] != r2["key"], r3
        print("[2] 自动 key OK:", r2["key"], "/", r3["key"])

        # ---------- 3) 主引擎置顶 ----------
        engine_registry.set_primary(r3["key"])
        lst = engine_registry.list_engines()
        assert lst[0]["key"] == r3["key"] and lst[0]["primary"], [(e["key"], e["primary"]) for e in lst]
        print("[3] 主引擎置顶 OK")

        # ---------- 4) takeover 预检（不真正启动下载）----------
        captured = {}
        import core.version_manager as vmod
        orig_new_task = vmod._new_task
        vmod._new_task = lambda name, job, *a, **k: captured.update(name=name, args=a) or f"fake-{name}"
        try:
            rr = vm.takeover_external(clone)
            assert rr["ok"] and rr["task_id"] == "fake-takeover", rr
            assert captured["args"][0] == clone
            assert captured["args"][1].startswith("http") and captured["args"][2] == "refs/heads/main", captured["args"]
        finally:
            vmod._new_task = orig_new_task
        print("[4] takeover 预检 OK:", captured["args"][1], "@", captured["args"][2])

        # ---------- 5) _install_job 成功路径 ----------
        newproj = os.path.join(base, "newproj")
        os.makedirs(os.path.join(newproj, "models", "Stable-diffusion"))
        open(os.path.join(newproj, "models", "Stable-diffusion", "m.safetensors"), "wb").write(b"DATA")
        open(os.path.join(newproj, "launch.py"), "w").write("new launch\n")
        open(os.path.join(newproj, "webui.py"), "w").write("new webui\n")
        fake_zip = os.path.join(base, "fake.zip")
        _make_zip(newproj, fake_zip)
        orig_gh = vm._gh_commit_sha
        orig_dl = vm._download_zip
        vm._gh_commit_sha = lambda repo, branch: "a" * 40
        vm._download_zip = lambda repo, branch, dest: shutil.copyfile(fake_zip, dest)

        # 真实目录：先放用户数据
        real = os.path.join(base, "real-engine")
        os.makedirs(os.path.join(real, "models", "Stable-diffusion"))
        os.makedirs(os.path.join(real, "outputs", "txt2img-images"))
        open(os.path.join(real, "models", "Stable-diffusion", "user.safetensors"), "wb").write(b"USER")
        open(os.path.join(real, "outputs", "txt2img-images", "a.png"), "wb").write(b"PNG")
        open(os.path.join(real, "config.json"), "w").write('{"keep": true}')
        open(os.path.join(real, "launch.py"), "w").write("old\n")
        list(vm._install_job(real, "test/repo", "refs/heads/main", "接管", "branch"))
        assert open(os.path.join(real, "launch.py")).read().strip() == "new launch"
        assert open(os.path.join(real, "models", "Stable-diffusion", "user.safetensors"), "rb").read() == b"USER"
        assert json.load(open(os.path.join(real, "config.json"))) == {"keep": True}
        rec = vm._read_managed_record(real)
        assert rec and rec["install_source"] == "atelier_managed" and rec["branch"] == "main", rec
        print("[5] _install_job 成功路径 OK")

        # ---------- 6) 校验失败：引擎原封不动 ----------
        bad = os.path.join(base, "bad-engine")
        os.makedirs(bad)
        open(os.path.join(bad, "keep.txt"), "w").write("keep")
        bad_zip = os.path.join(base, "bad.zip")
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("noentry/readme.txt", "x")
        vm._download_zip = lambda repo, branch, dest: shutil.copyfile(bad_zip, dest)
        try:
            list(vm._install_job(bad, "test/repo", "refs/heads/main", "接管", "branch"))
            raise AssertionError("应校验失败")
        except RuntimeError as e:
            assert "校验失败" in str(e), e
        assert os.path.exists(os.path.join(bad, "keep.txt"))
        print("[6] 校验失败 OK：引擎目录未动")

        # ---------- 7) 还原失败：备份救出临时目录 ----------
        ro = os.path.join(base, "ro-engine")
        os.makedirs(os.path.join(ro, "models", "Stable-diffusion"))
        open(os.path.join(ro, "models", "Stable-diffusion", "m.bin"), "wb").write(b"DATA")
        open(os.path.join(ro, "launch.py"), "w").write("old")
        zip2 = os.path.join(base, "fake2.zip")
        _make_zip(newproj, zip2)
        vm._download_zip = lambda repo, branch, dest: shutil.copyfile(zip2, dest)
        orig_move = shutil.move

        def flaky_move(src, dst):
            d = str(dst).replace("\\", "/")
            if d.endswith("/ro-engine/models") and os.path.isdir(src):
                raise PermissionError("simulated restore failure")
            return orig_move(src, dst)

        shutil.move = flaky_move
        try:
            try:
                list(vm._install_job(ro, "test/repo", "refs/heads/main", "接管", "branch"))
                raise AssertionError("应还原失败")
            except RuntimeError as e:
                assert "备份保留在" in str(e), e
            rescues = [n for n in os.listdir(base) if n.startswith(".ftn-userdata-backup-")]
            assert rescues, "应存在救援备份"
            assert os.path.exists(os.path.join(base, rescues[0], "models", "Stable-diffusion", "m.bin"))
            print("[7] 还原失败救备份 OK:", rescues[0])
        finally:
            shutil.move = orig_move

        vm._gh_commit_sha = orig_gh  # 恢复真实方法，供 [8] 兜底逻辑测试使用
        vm._download_zip = orig_dl

        # ---------- 8) commit/ZIP 获取：直连失败 → 镜像兜底 → 都失败才报错 ----------
        class _FakeResp:
            def __init__(self, body):
                self._b = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                if n is None or n < 0:
                    return self._b
                out, self._b = self._b[:n], self._b[n:]
                return out

        orig_urlopen = urllib.request.urlopen
        orig_check_output = subprocess.check_output
        import core.mirrors as mirrors_mod
        orig_prefix = mirrors_mod.configured_prefix
        calls = []

        def fake_check_output(cmd, **kw):
            url = cmd[-2]
            calls.append(("git", url))
            if url.startswith("https://github.com/"):
                raise subprocess.CalledProcessError(128, cmd, output=b"fatal: unable to access")
            if url.startswith("https://ghproxy.com/"):
                raise subprocess.CalledProcessError(128, cmd, output=b"mirror down")
            if url.startswith("https://gh-proxy.com/https://github.com/"):
                return "b" * 40 + "\trefs/heads/main\n"
            raise AssertionError(f"unexpected git url: {url}")

        def fake_urlopen(req, timeout=15):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append(("http", url))
            if url.startswith("https://github.com/"):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            if url.startswith("https://ghproxy.com/https://github.com/"):
                return _FakeResp(b"ZIPDATA")
            raise AssertionError(f"unexpected url: {url}")

        subprocess.check_output = fake_check_output
        urllib.request.urlopen = fake_urlopen
        mirrors_mod.configured_prefix = lambda: "https://ghproxy.com"
        try:
            # 真实调用传的是完整仓库 URL（来自 _repo_of / 接管记录）
            sha = vm._gh_commit_sha("https://github.com/Panchovix/stable-diffusion-webui-reForge", "refs/heads/main")
            assert sha == "b" * 40, sha
            git_calls = [u for k, u in calls if k == "git"]
            # 并行探测（直连/配置镜像失败 → gh-proxy 成功），顺序不固定
            assert any("gh-proxy.com" in u for u in git_calls), git_calls
            assert not any("github.com/github.com" in u for u in git_calls), git_calls  # 绝不双重拼接
            assert len(git_calls) >= 2, git_calls
            zip_dest = os.path.join(base, "dl.zip")
            vm._download_zip("https://github.com/Panchovix/stable-diffusion-webui-reForge", "main", zip_dest)
            assert open(zip_dest, "rb").read() == b"ZIPDATA"
            print("[8] commit/ZIP 获取：直连→配置镜像→内置镜像轮换 OK")

            # 都失败 → 明确报错（不甩 JSON 解析异常）
            def fake_check_both_fail(cmd, **kw):
                raise subprocess.CalledProcessError(128, cmd, output=b"fatal")
            subprocess.check_output = fake_check_both_fail
            try:
                try:
                    vm._gh_commit_sha("https://github.com/Panchovix/stable-diffusion-webui-reForge", "refs/heads/main")
                    raise AssertionError("应报错")
                except RuntimeError as e:
                    assert "直连与镜像均不可用" in str(e), e
                print("[9] commit 获取全部失败 → 明确报错 OK")
            finally:
                subprocess.check_output = fake_check_output
        finally:
            urllib.request.urlopen = orig_urlopen
            subprocess.check_output = orig_check_output
            mirrors_mod.configured_prefix = orig_prefix
            mirrors_mod.clear_success()
    finally:
        for k in list(config_manager.load().engine_paths.extra):
            engine_registry.remove_engine(k)
        engine_registry.set_primary("reforge")
        _restore_state(st)
        shutil.rmtree(base, ignore_errors=True)
    print("\n=== 引擎主引擎 / 自定义路径 / 接管安装例程 全部回归通过 ===")


if __name__ == "__main__":
    main()
