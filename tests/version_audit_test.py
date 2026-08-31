# ============================================
# 版本板块检修回归测试
#
# 覆盖：
#   1. 仓库分离：reforge/forge 各指向官方仓库
#   2. _fetch_tags 直连失败 → 镜像兜底
#   3. download_candidates 跳过未知（空版本）已装实例
#   4. update_version / rollback_version 对 Core/Engines 外实例用 infer 兜底基底，仓库不取空
# ============================================

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.version_manager import (  # noqa: E402
    VersionManager, _repo_of, _fetch_tags, ENGINES_ROOT,
)


def main():
    vm = VersionManager()
    base = tempfile.mkdtemp(prefix="ftn_veraudit_")
    try:
        # ---------- 1) 仓库分离 ----------
        assert "Panchovix/stable-diffusion-webui-reForge" in _repo_of("reforge")
        assert "lllyasviel/stable-diffusion-webui-forge" in _repo_of("forge")
        print("[1] 仓库分离 OK:", _repo_of("reforge"), "|", _repo_of("forge"))

        # ---------- 2) _fetch_tags 直连→镜像兜底 ----------
        fake_out = (
            "abc\trefs/tags/v1.2.0\n"
            "def\trefs/tags/v1.7.0d\n"
            "def\trefs/tags/1.1.0\n"
            "ghi\trefs/tags/1.1.1\n"
            "zzz\trefs/tags/latest\n"
        )
        calls = []
        orig_check = subprocess.check_output

        def fake_check(cmd, **kw):
            calls.append(cmd)
            url = cmd[-1]
            if url.startswith("https://github.com/"):
                raise subprocess.CalledProcessError(128, cmd, output=b"fatal: unable to access")
            if "ghproxy.com" in url:
                return fake_out
            raise AssertionError(f"unexpected url: {url}")

        subprocess.check_output = fake_check
        try:
            tags = _fetch_tags("https://github.com/Panchovix/stable-diffusion-webui-reForge")
            assert tags[0] == "v1.7.0d", tags  # 带字母尾缀且数值最大 → 排序第一
            # 带字母尾缀的版本 tag（如 reForge 的 v1.7.0d）必须保留
            assert "v1.7.0d" in tags, tags
            # 浮动/非版本 tag（latest）不算版本，必须排除
            assert "latest" not in tags, tags
            # 并行探测（直连失败 → 镜像成功）：存在镜像调用且无双重拼接
            urls = [c[-1] for c in calls]
            assert any("ghproxy.com" in u for u in urls), urls
            assert all(u.count("github.com") == 1 for u in urls), urls  # 绝不双重拼接
            print("[2] _fetch_tags 直连→镜像兜底 OK:", tags[:3])
        finally:
            subprocess.check_output = orig_check

        # ---------- 3) download_candidates 跳过空版本已装实例 ----------
        reforge_root = os.path.join(ENGINES_ROOT, "reforge")
        reforge_existed = os.path.isdir(reforge_root)
        os.makedirs(reforge_root, exist_ok=True)
        fake_inst = os.path.join(reforge_root, "__veraudit_empty__")
        os.makedirs(fake_inst)
        try:
            info = vm.download_candidates("reforge", limit=6, fetch=False)
            assert "" not in info["installed"], info["installed"]
            assert not any(str(v).strip() == "" for v in info["versions"]), info["versions"]
            print("[3] download_candidates 跳过空版本 OK, installed =", info["installed"])
        finally:
            shutil.rmtree(fake_inst, ignore_errors=True)
            if not reforge_existed:
                shutil.rmtree(reforge_root, ignore_errors=True)

        # ---------- 4) 外部 git 实例更新：infer 兜底基底，仓库不取空 ----------
        ext = os.path.join(base, "stable-diffusion-webui-reForge-external")
        os.makedirs(os.path.join(ext, ".git"))
        captured = {}
        repo_seen = []
        import core.version_manager as vmod
        orig_new_task = vmod._new_task
        orig_resolve = vmod._resolve_remote_tag
        orig_cands = vm.download_candidates
        vmod._new_task = lambda name, job, *a, **k: captured.update(name=name, args=a) or f"fake-{name}"
        vmod._resolve_remote_tag = lambda repo, ver: repo_seen.append(repo) or f"tag:{ver}"
        vm.download_candidates = lambda b, limit, fetch: {"versions": ["9.9.9"]}
        try:
            r = vm.update_version(ext)
            # 更新语义：默认更新到所属分支（main）最新 commit，不再解析 tag
            assert r["ok"] and r.get("target") == "main（最新）", r
            print("[4] 外部 git 实例 update 分支兜底 OK:", r.get("target"))
            captured.clear()
            r2 = vm.rollback_version(ext, "1.0.0")
            assert r2["ok"], r2
            assert repo_seen and repo_seen[0] == _repo_of("reforge"), repo_seen
            print("[5] 外部 git 实例 rollback 基底兜底 OK:", repo_seen[0])
        finally:
            vmod._new_task = orig_new_task
            vmod._resolve_remote_tag = orig_resolve
            vm.download_candidates = orig_cands

        # ---------- 5) Atelier Managed：候选检测 + tag 选择式更新 ----------
        managed = os.path.join(base, "managed-engine")
        os.makedirs(os.path.join(managed, ".ftn"))
        rec = {
            "engine": "reforge",
            "repository": "https://github.com/Panchovix/stable-diffusion-webui-reForge",
            "branch": "main",
            "tag": "v1.1.0",
            "commit": "a" * 40,
            "install_source": "atelier_managed",
        }
        with open(os.path.join(managed, ".ftn", "engine.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        orig_gh = vm._gh_commit_sha
        orig_fetch = vmod._fetch_tags
        orig_new_task2 = vmod._new_task
        vmod._fetch_tags = lambda repo_url, timeout=25: ["v1.2.0", "v1.1.0", "v1.0.0", "v0.9.9d", "v1.7.0d"]
        vmod._new_task = lambda name, job, *a, **k: captured.update(name=name, args=a) or f"fake-{name}"
        vm._gh_commit_sha = lambda repo, ref: "b" * 40
        try:
            cands = vm.managed_candidates(managed)
            assert cands["ok"], cands
            assert cands["current"]["tag"] == "v1.1.0"
            upd_targets = [u["target"] for u in cands["update"]]
            assert "latest" in upd_targets and "v1.2.0" in upd_targets, upd_targets
            rb_targets = [u["target"] for u in cands["rollback"]]
            assert "v1.0.0" in rb_targets and "v0.9.9d" in rb_targets, rb_targets
            print("[6] managed_candidates 候选检测 OK: 更新", upd_targets, "| 回退", rb_targets)

            # 接管后的引擎（无 tag，仅 branch+commit）：所有正式 tag 都应进入回退候选
            rec2 = dict(rec)
            rec2["tag"] = ""
            rec2["commit"] = "739b2e1d9ab63160eaff9c8f73172c8da68424e1"
            with open(os.path.join(managed, ".ftn", "engine.json"), "w", encoding="utf-8") as f:
                json.dump(rec2, f)
            vm._gh_commit_sha = lambda repo, ref: "739b2e1d9ab63160eaff9c8f73172c8da68424e1"
            cands2 = vm.managed_candidates(managed)
            assert cands2["ok"], cands2
            assert not cands2["update"], cands2["update"]  # 已是最新分支 commit，无更新候选
            rb2 = [u["target"] for u in cands2["rollback"]]
            assert "v1.7.0d" in rb2 and "v0.9.9d" in rb2, rb2
            print("[6b] 接管实例（无 tag）回退候选 OK:", rb2)

            captured.clear()
            r = vm.managed_update(managed, "v1.0.0")
            assert r["ok"] and captured["args"][2] == "refs/tags/v1.0.0" and captured["args"][4] == "tag", (r, captured["args"])
            captured.clear()
            r2 = vm.managed_update(managed, "latest")
            assert r2["ok"] and captured["args"][2] == "refs/heads/main" and captured["args"][4] == "branch", (r2, captured["args"])
            print("[7] managed_update 分支/tag 选择式更新 OK")
        finally:
            vm._gh_commit_sha = orig_gh
            vmod._fetch_tags = orig_fetch
            vmod._new_task = orig_new_task2
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("\n=== 版本板块检修回归全部通过 ===")


if __name__ == "__main__":
    main()
