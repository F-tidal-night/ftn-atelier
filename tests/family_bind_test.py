# ============================================
# 引擎家族识别 / 外部 ZIP 手动绑定 / 候选语义化 回归测试
#
# 覆盖：
#   1. base_registry.family_of：reforge / comfyui / a1111 / unknown
#   2. engine_registry 引擎条目的 family 字段 + set_primary 受限模式（切回后还原）
#   3. 外部 ZIP 手动绑定版本身份（bind.json → _read_version.user_bound）
#   4. download_candidates 候选 = main（最新）+ 正式 tag + previous（按仓库）
#   5. git_candidates：更新=分支最新 commit；回退=正式 tag + previous
# ============================================

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Source", "backend")))

from core.base_registry import base_registry  # noqa: E402
from core.engine_registry import engine_registry  # noqa: E402
from core.version_manager import VersionManager, _promote_download_if_needed, ENGINES_ROOT  # noqa: E402
from core.db import db  # noqa: E402
from core.config_manager import config_manager  # noqa: E402


def main():
    vm = VersionManager()
    base = tempfile.mkdtemp(prefix="ftn_famtest_")
    custom_bak = db.get_meta("engine_custom") or {}
    try:
        # ---------- 1) 家族识别 ----------
        comfy = os.path.join(base, "ComfyUI")
        os.makedirs(os.path.join(comfy, "comfy"))
        a1111 = os.path.join(base, "stable-diffusion-webui")
        os.makedirs(os.path.join(a1111, "modules"))
        open(os.path.join(a1111, "launch.py"), "w").close()
        open(os.path.join(a1111, "webui.py"), "w").close()
        unknown = os.path.join(base, "my_stuff")
        os.makedirs(unknown)
        assert base_registry.family_of(comfy) == "comfyui"
        assert base_registry.family_of(a1111) == "a1111"
        assert base_registry.family_of(unknown) == "unknown"
        assert base_registry.family_of("") == ""
        print("[1] family_of OK: comfyui / a1111 / unknown")

        # ---------- 2) 引擎条目 family + set_primary 受限模式 ----------
        r = engine_registry.add_engine("comfy-test", "ComfyUI 测试", kind="webui", root=comfy)
        assert r["ok"], r
        eng = next((e for e in engine_registry.list_engines() if e["key"] == "comfy-test"), None)
        assert eng and eng["family"] == "comfyui", eng
        sr = engine_registry.set_primary("comfy-test")
        assert sr["ok"] and sr.get("limited") and sr.get("family") == "comfyui", sr
        back = engine_registry.set_primary("reforge")
        assert back["ok"] and not back.get("limited"), back
        print("[2] 引擎 family 字段 + set_primary 受限模式 OK")

        # ---------- 3) 外部 ZIP 手动绑定 ----------
        ext = os.path.join(base, "external-webui-main")
        os.makedirs(ext)
        br = vm.bind_external(ext, commit="739b2e1", branch="main")
        assert br["ok"], br
        v = vm._read_version(ext)
        assert v["git_commit"] == "739b2e1" and v["user_bound"] and v["install_source"] == "external", v
        assert v["date"], v
        # 没有绑定的外部实例：目录名 -main 只推断 branch，不猜版本
        ext2 = os.path.join(base, "another-webui-main")
        os.makedirs(ext2)
        v2 = vm._read_version(ext2)
        assert v2["branch"] == "main" and not v2["git_commit"] and not v2["user_bound"], v2
        print("[3] 外部 ZIP 手动绑定 / 未绑定不猜版本 OK")

        # ---------- 4) download_candidates 候选语义 ----------
        import core.version_manager as vmod
        orig_all = vmod._fetch_all_tags

        def fake_all(repo_url, timeout=25):
            tags = ["latest", "v1.7.0d"]
            if "webui-forge" in str(repo_url).lower():
                tags.append("previous")
            return tags

        vmod._fetch_all_tags = fake_all
        try:
            cands = vm.download_candidates("reforge", fetch=True)
            assert cands["versions"][0] == "main" and "v1.7.0d" in cands["versions"], cands["versions"]
            assert "previous" not in cands["versions"], cands["versions"]  # reForge 无 previous
            cands_f = vm.download_candidates("forge", fetch=True)
            assert cands_f["versions"][0] == "main" and "previous" in cands_f["versions"], cands_f["versions"]
            print("[4] download_candidates main + tag + previous OK:", cands_f["versions"])
        finally:
            vmod._fetch_all_tags = orig_all

        # ---------- 5) git_candidates：更新=分支最新；回退=tag + previous ----------
        g = os.path.join(base, "git-clone-main")
        os.makedirs(os.path.join(g, ".git"))
        orig_branch = vm._git_branch
        orig_commit = vm._git_commit
        orig_gh = vm._gh_commit_sha
        orig_all2 = vmod._fetch_all_tags
        orig_base_of = vmod._base_of_path
        vm._git_branch = lambda d: "main"
        vm._git_commit = lambda d: "a" * 40
        vm._gh_commit_sha = lambda repo, ref: "b" * 40
        vmod._fetch_all_tags = fake_all
        vmod._base_of_path = lambda d: "reforge" if d == g else orig_base_of(d)
        try:
            gc = vm.git_candidates(g)
            assert gc["ok"], gc
            assert gc["update"] and gc["update"][0]["label"] == "main @ bbbbbbb", gc["update"]
            rb = [u["label"] for u in gc["rollback"]]
            assert "v1.7.0d" in rb, rb
            # forge 家族：previous 也进入回退候选
            vmod._base_of_path = lambda d: "forge" if d == g else orig_base_of(d)
            gc_f = vm.git_candidates(g)
            rb_f = [u["label"] for u in gc_f["rollback"]]
            assert "v1.7.0d" in rb_f and "previous（上一版）" in rb_f, rb_f
            print("[5] git_candidates OK: 更新", gc["update"][0]["label"], "| reForge 回退", rb, "| Forge 回退", rb_f)
        finally:
            vm._git_branch = orig_branch
            vm._git_commit = orig_commit
            vm._gh_commit_sha = orig_gh
            vmod._fetch_all_tags = orig_all2
            vmod._base_of_path = orig_base_of

        # ---------- 6) 下载后自动设为主引擎（主引擎为空时） ----------
        conf_path = config_manager.CONFIG_PATH
        conf_bak = json.load(open(conf_path, encoding="utf-8"))
        reforge_root = os.path.join(ENGINES_ROOT, "reforge")
        reforge_existed = os.path.isdir(reforge_root)
        os.makedirs(reforge_root, exist_ok=True)
        fake_inst = os.path.join(reforge_root, "__promote_fake__")
        os.makedirs(os.path.join(fake_inst, "modules_forge"))
        try:
            engine_registry.set_path(engine_registry.primary_engine()["key"], "")
            _promote_download_if_needed(fake_inst)
            e2 = engine_registry.primary_engine()
            assert e2["root"] == fake_inst, e2
            assert base_registry.primary() == "forge", base_registry.primary()
            cur = vm.current()
            assert cur and cur["id"] == fake_inst, (cur, fake_inst)
            print("[6] 下载后自动设为主引擎 + 激活 OK:", e2["root"], "| active:", cur["id"])
        finally:
            with open(conf_path, "w", encoding="utf-8") as f:
                json.dump(conf_bak, f, ensure_ascii=False, indent=2)
            config_manager._config = None  # 清缓存，确保后续读回原配置
            db.set_meta("active_engine", "")
            shutil.rmtree(fake_inst, ignore_errors=True)
            if not reforge_existed:
                shutil.rmtree(reforge_root, ignore_errors=True)
    finally:
        custom = dict(custom_bak)
        custom["added"] = [a for a in custom.get("added", []) if a.get("key") != "comfy-test"]
        custom["primary_key"] = custom_bak.get("primary_key", "")
        db.set_meta("engine_custom", custom)
        conf = config_manager.load()
        conf.engine_paths.extra.pop("comfy-test", None)
        config_manager.save(conf)
        shutil.rmtree(base, ignore_errors=True)
    print("\n=== 家族识别 / 绑定 / 候选语义 回归全部通过 ===")


if __name__ == "__main__":
    main()
