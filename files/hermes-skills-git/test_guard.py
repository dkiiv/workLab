#!/usr/bin/env python3
"""Tests for work_skills_guard — run: python3 test_guard.py  (exit 0 = all pass).

Isolation rules, all learned the hard way:
* throwaway clones + local bare remotes in a temp dir; never the real repo, never GitHub;
* HOME pointed at a fake hermes home, so shadow/README checks see a controlled world;
* the fixture skill is one that already exists and is already indexed, so a green-check
  assertion isn't broken by the README-index rule;
* every subprocess gets WORK_REPO — forget it and the hooks scan the REAL clone.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "work_skills_guard.py"
SRC = Path(__file__).resolve().parents[2]
FAIL: list[str] = []

SECRET = 'api_key = "ghp_AAAAAAAAAAAA1111111111"\n'
SECRET2 = 'password = "SuperSecret42424242424"\n'
SKILL_DIR = "hermes-skills/autonomous-ai-agents/work-shared-skills"   # exists + indexed
SKILL = f"{SKILL_DIR}/SKILL.md"


def ok(cond: bool, label: str, detail: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"  [{detail[:230]}]" if detail and not cond else ""))
    if not cond:
        FAIL.append(label)


def run(repo: str | None, *args: str, stdin: str = "", env: dict | None = None,
        hook: str | None = None, git: bool = False, home: str | None = None):
    if git:
        cmd = ["git", "-C", repo or ".", *args]
    elif hook:
        cmd = [sys.executable, str(GUARD), "--hook", hook, *args]
    else:
        cmd = [sys.executable, str(GUARD), *args]
    e = {**os.environ, "WORK_GUARD_LOG": "0", **({"WORK_REPO": repo} if repo else {}),
         **({"HOME": home} if home else {}), **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, input=stdin, env=e,
                          timeout=180, check=False)


def g(repo: str, *args: str, **kw):
    return run(repo, *args, git=True, **kw)


def text(cp) -> str:
    return ((cp.stdout or "") + (cp.stderr or "")).strip()


def make_repo(tmp: str, name: str, share_origin_of: str | None = None) -> str:
    """Clone of SRC with a local bare origin, wired like `install` does, then a setup
    commit so the clone starts clean/aligned with the guard + hooks tracked inside it.
    share_origin_of=<name> joins that fixture's remote — how a second agent is faked."""
    base = Path(tmp) / name
    base.mkdir(parents=True)
    if share_origin_of:
        origin = str(Path(tmp) / share_origin_of / "origin.git")
    else:
        origin = str(base / "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True, capture_output=True)
    dst = str(base / "clone")
    subprocess.run(["git", "clone", "-q", str(SRC), dst], check=True, capture_output=True)
    g(dst, "remote", "set-url", "origin", origin)
    hooks = Path(dst) / "hooks"
    hooks.mkdir(exist_ok=True)
    for h in ("pre-commit", "pre-push"):
        shutil.copy(SRC / "hooks" / h, hooks / h)
        os.chmod(hooks / h, 0o755)
    gd = Path(dst) / "files" / "hermes-skills-git"
    gd.mkdir(parents=True, exist_ok=True)
    shutil.copy(GUARD, gd / GUARD.name)  # a real clone gets this from git; tests predate the commit
    g(dst, "config", "core.hooksPath", "hooks")
    g(dst, "add", "-f", "--", "files/hermes-skills-git", "hooks")
    subprocess.run(["git", "-C", dst, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit",
                    "-q", "--no-verify", "-m", "test: wire guard"], capture_output=True)
    (Path(dst) / ".git" / "FETCH_HEAD").touch()
    g(dst, "fetch", "-q", "origin")
    if share_origin_of:
        g(dst, "checkout", "-q", "-B", "main", "origin/main")
    else:  # align a private origin without the repo hooks (their paths resolve inside this clone)
        subprocess.run(["git", "-C", dst, "push", "-q", "--force", "--no-verify", "origin",
                        "HEAD:refs/heads/main"], check=True, capture_output=True)
        g(dst, "fetch", "-q", "origin")
        g(dst, "reset", "-q", "--hard", "origin/main")
    g(dst, "branch", "--set-upstream-to=origin/main", "-q", "main")
    g(dst, "config", "user.name", "work-agent")
    g(dst, "config", "user.email", "work-agent@users.noreply.github.com")
    return dst


def fake_home(tmp: str, name: str) -> str:
    """A hermes home with an empty skills dir: the outside world cannot skew check()."""
    home = Path(tmp) / f"{name}-home"
    (home / ".hermes/skills").mkdir(parents=True, exist_ok=True)
    return str(home)


def edit_skill(repo: str, n: int) -> Path:
    f = Path(repo) / SKILL
    f.write_text(f.read_text(encoding="utf-8") + f"<!-- test edit {n} -->\n", encoding="utf-8")
    return f


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="guard-test-", dir=os.environ.get("TMPDIR") or "/tmp")
    try:
        print("scanner")
        sys.path.insert(0, str(GUARD.parent))
        import work_skills_guard as gr
        ok(not [h for h in gr.scan_text(GUARD.read_text()) if h["tier"] == 1],
           "the guard's own source never self-flags")
        for pos in (SECRET.strip(), 'password = "SuperSecret12345678"', "aws = AKIAIOSFODNN7EXAMPLE",
                    "sk-abcdefghijklmnopqrstuvwxyz1234", "x: postgres://usr:secretword@host/db",
                    SECRET2.strip(), "card 4242424242424242"):
            ok(bool([h for h in gr.scan_text(pos) if h["tier"] == 1]), f"blocks: {pos[:36]}")
        for neg in ('token = os.environ.get("X_TOKEN")', "key_env: SOME_SERVICE_KEY",
                    "# password lives in /etc/app/app.env", "0500000000000001",
                    "password_hash: scrypt$abc", "token: full-attention",
                    'token = "ghp_AAAAAAAAAAAA1111111111"  # guard:allow'):
            ok(not [h for h in gr.scan_text(neg) if h["tier"] == 1], f"ignores: {neg[:42]}")
        ok(gr._luhn_ok("4242424242424242") and not gr._luhn_ok("1234567890123456"), "luhn gate")

        print("commit-skills + push")
        repo, home = make_repo(tmp, "main"), None
        home = fake_home(tmp, "main")
        p = run(repo, "commit-skills", home=home)
        ok(p.returncode == 0 and "nothing to commit" in p.stdout, "clean repo -> nothing to commit", text(p))
        edit_skill(repo, 1)
        p = run(repo, "commit-skills", home=home)
        ok(p.returncode == 0 and "committed" in p.stdout and "pushed" in p.stdout,
           "clean skill edit commits AND pushes", text(p))
        ok(g(repo, "log", "-1", "--format=%ae").stdout.strip() == "work-agent@users.noreply.github.com",
           "commit uses the noreply identity")
        ok(g(repo, "log", "-1", "--format=%an").stdout.strip() == "work-agent", "commit uses the work-agent name")
        pc = run(repo, "check", home=home)
        ok(pc.returncode == 0, "check green after commit+push", pc.stdout + pc.stderr)
        leaked = Path(repo) / SKILL_DIR / "leaked.md"
        leaked.write_text(SECRET)
        p = run(repo, "commit-skills", home=home)
        ok(p.returncode == 2 and "secret-shaped" in p.stdout, "secret edit is refused", text(p))
        ok(not g(repo, "diff", "--cached", "--name-only").stdout.strip(),
           "refused commit stages nothing (no half-staged tree)")
        ok(leaked.exists(), "refused file stays on disk (work not lost)")
        leaked.unlink()
        edit_skill(repo, 2)
        ok(run(repo, "commit-skills", home=home).returncode == 0, "a later clean edit still commits")
        p = run(repo, "push", home=home)
        ok(p.returncode == 0, "push with nothing to push is a clean no-op", text(p))

        print("git hooks fire on plain git")
        r2 = make_repo(tmp, "hooks")
        bad = Path(r2) / SKILL_DIR / "bad.md"
        bad.write_text(SECRET)
        g(r2, "add", "-A")
        p = g(r2, "commit", "-m", "raw with secret")
        ok(p.returncode != 0 and "secret-shaped" in text(p), "pre-commit blocks a raw git commit", text(p))
        ok(bad.exists(), "a blocked commit leaves the files on disk untouched")
        p = g(r2, "commit", "-m", "raw with secret", "--no-verify")
        ok(p.returncode == 0, "--no-verify bypasses (documented escape hatch)", text(p))
        p = g(r2, "push", "origin", "main")
        ok(p.returncode != 0 and "secret-shaped" in text(p), "pre-push blocks the push of that commit", text(p))
        p = run(r2, "push", home=fake_home(tmp, "hooks"))
        ok(p.returncode == 2 and "secret-shaped" in p.stdout, "guard push action blocks too", text(p))

        print("session hook (pre_llm_call -> nudge once)")
        edit_skill(repo, 3)
        run(repo, "commit-skills", "--no-push", home=home)
        p = run(repo, "--hook", "pre-llm", home=home,
                stdin=json.dumps({"session_id": "s1", "is_first_turn": True}))
        ctx = (json.loads(p.stdout) if p.stdout.strip() else {}).get("context", "")
        ok(p.returncode == 0 and "not pushed" in ctx, "first turn gets a nudge naming the problem", text(p))
        ok(len(ctx) < 1800 and ctx.count("\n") < 16, "nudge is compact (safe for every turn's context)")
        p2 = run(repo, "--hook", "pre-llm", home=home,
                 stdin=json.dumps({"session_id": "s1", "is_first_turn": True}))
        ok(p2.stdout.strip() == "", "the same session is not nudged twice")
        p3 = run(repo, "--hook", "pre-llm", home=home,
                 stdin=json.dumps({"session_id": "s2", "is_first_turn": False}))
        ok(p3.stdout.strip() == "", "later turns are silent")
        p4 = run(repo, "--hook", "pre-llm", home=home, env={"WORK_GUARD_OFF": "1"},
                 stdin=json.dumps({"session_id": "s3", "is_first_turn": True}))
        ok(p4.returncode == 0 and not p4.stdout.startswith("{"), "WORK_GUARD_OFF=1 silences the hook")
        p5 = run(repo, "--hook", "pre-llm", home=home, stdin="{ not json")
        ok(p5.returncode == 0, "malformed stdin fails open (never breaks a session)")

        print("auto-commit hook (post_tool_call / skill_manage)")
        edit_skill(repo, 4)
        run(repo, "--hook", "post-tool", home=home, stdin=json.dumps(
            {"tool_name": "skill_manage", "tool_input": {}, "result": {"skills": ["work-shared-skills"]}}))
        subj = g(repo, "log", "-1", "--format=%s").stdout.strip()
        ok("work-shared-skills" in subj, "skill_manage success auto-commits with a named reason", subj)
        pa = run(repo, "check", home=home)
        ok(pa.returncode == 0, "repo back to green after auto-commit (pushed)", pa.stdout + pa.stderr)
        edit_skill(repo, 5)
        run(repo, "--hook", "post-tool", home=home,
            stdin=json.dumps({"tool_name": "skill_manage", "result": {"error": "boom"}}))
        ok(run(repo, "check", home=home).returncode == 1,
           "a failed skill_manage commits nothing (dirty stays dirty)")
        run(repo, "commit-skills", home=home)
        run(repo, "--hook", "post-tool", home=home,
            stdin=json.dumps({"tool_name": "terminal", "result": {}}))
        ok(True, "other tools ignored by post-tool (no crash)")

        print("check detections")
        r3, h3 = make_repo(tmp, "check"), fake_home(tmp, "check")
        edit_skill(r3, 1)
        p = run(r3, "check", home=h3)
        ok("uncommitted" in p.stdout and p.returncode == 1, "detects uncommitted skill edits", p.stdout[:250])
        g(r3, "checkout", "-q", "--", SKILL)
        shadow = Path(h3) / ".hermes/skills/devops/work-shared-skills"
        shadow.mkdir(parents=True)
        (shadow / "SKILL.md").write_text("local copy\n")
        (Path(r3) / SKILL_DIR / "newref.md").write_text("untracked\n")
        p = run(r3, "check", home=h3)
        ok("shadow" in p.stdout and "work-shared-skills" in p.stdout,
           "detects a local copy shadowing a shared skill", p.stdout[:300])
        ok("untracked" in p.stdout, "detects untracked files under the skills dir", p.stdout[:250])
        (Path(r3) / SKILL_DIR / "secret.md").write_text(SECRET)
        p = run(r3, "check", home=h3)
        ok("secret-shaped" in p.stdout, "flags secrets sitting in the dirty worktree", p.stdout[:300])
        g(r3, "clean", "-qfd", "hermes-skills")
        shutil.rmtree(shadow)
        pc2 = run(r3, "check", home=h3)
        ok(pc2.returncode == 0, "green after cleanup", pc2.stdout + pc2.stderr)
        edit_skill(r3, 9)
        run(r3, "commit-skills", "--no-push", home=h3)
        p = run(r3, "check", home=h3)
        ok("not pushed" in p.stdout and p.returncode == 1, "detects unpushed commits", p.stdout[:250])
        # a second agent pushes to the same origin
        r4 = make_repo(tmp, "second", share_origin_of="check")
        (Path(r4) / SKILL_DIR / "from-second.md").write_text("from agent 2\n")
        pr = run(r4, "commit-skills", home=fake_home(tmp, "second"))
        ok(pr.returncode == 0 and "pushed" in pr.stdout, "second clone commits+pushes through the guard",
           text(pr))
        g(r3, "fetch", "-q", "origin")
        p = run(r3, "check", home=h3)
        ok("behind" in p.stdout and "pull --ff-only" in p.stdout, "detects clone behind origin + hint",
           p.stdout[:300])
        g(r3, "pull", "--rebase", "-q", "origin", "main")
        run(r3, "push", home=h3)
        pc3 = run(r3, "check", home=h3)
        ok(pc3.returncode == 0, "green again once synced", pc3.stdout + pc3.stderr)
        g(r3, "config", "user.email", "someone@gmail.com")
        p = run(r3, "check", home=h3)
        ok("user.email" in p.stdout and p.returncode == 1, "detects a personal git identity", p.stdout[:250])
        g(r3, "config", "user.email", "work-agent@users.noreply.github.com")
        ok(run(r3, "check", home=h3).returncode == 0, "green again once identity is fixed")

        print("real repo (read-only)")
        hits = gr.scan_tree(SRC)  # tracked files only: what a push would actually expose
        t1 = [h for h in hits if h["tier"] == 1]
        ok(not t1, "no tier-1 hits in the tracked tree of the real repo", "; ".join(
            f"{h['rule']} @{h['where']}" for h in t1[:6]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + (f"{len(FAIL)} FAILED: {FAIL}" if FAIL else "ALL PASS"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
