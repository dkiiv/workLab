#!/usr/bin/env python3
"""work-skills-guard — enforcement layer for the shared skills folder.

the repo owner's Hermes agents share procedures through ``hermes-skills/`` in the private
``work-agent/workLab`` repo. The sync rules (pull before editing, commit + push after, never
commit secrets, no local copy shadowing a shared one) lived only as prose in
``hermes-skills/README.md`` — nothing checked them, so skill edits sat uncommitted or
unpushed where no other agent could ever see them. This makes the rules mechanical:

  git hooks    ``hooks/pre-commit`` + ``hooks/pre-push`` (enabled via core.hooksPath):
               every line entering history is scanned for secret-shaped text.
  Hermes hooks ``hooks.pre_llm_call`` -> first turn of a session: ff-only pull when the
               clone is clean, and ONE compact nudge when anything needs attention;
               ``hooks.post_tool_call`` (matcher skill_manage) -> scan + commit + push
               the shared-skill edit, so "the agent edited a skill" implies "pushed".
  check        read-only health report (also what the nudge prints): dirty/untracked
               skills, unpushed commits, behind origin, git identity, local copies that
               shadow shared skills, README index drift, missing wiring.

Bypasses exist on purpose: ``git --no-verify``, ``WORK_GUARD_OFF=1``, or deleting the
hook registrations. The guard must never lock anyone out of this repo, so it fail-opens
whenever it breaks and only ever blocks push/commit for tier-1 (credential-shaped) hits.

Run ``... install`` on every host whose Hermes agent uses this clone; it is idempotent.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_DEFAULT = "~/Git/work/workLab"
SKILLS_SUB = "hermes-skills"
SCAN_SUBS = ("hermes-skills", "docs", "files", "README.md")
REMOTE_DEFAULT = "git@github.com:dkiiv/workLab.git"
ID_NAME = "work-agent"
ID_EMAIL = "work-agent@users.noreply.github.com"
LOG_RELPATH = ".hermes/logs/work-guard.log"
STATE_RELPATH = ".hermes/cache/work-guard/state.json"
HOOK_MARK = "work_skills_guard.py"
GIT_TIMEOUT = 12
NET_TIMEOUT = 90
REMINDER_MAX_PER_SESSION_S = 6 * 3600
FETCH_FRESH_S = 6 * 3600
# This tool's own source and tests hold fake credentials on purpose: never scan them.
SELF_NAMES = ("work_skills_guard.py", "test_guard.py")


def _repo() -> Path:
    return Path(os.environ.get("WORK_REPO", REPO_DEFAULT)).expanduser().resolve()


def _off() -> bool:
    return os.environ.get("WORK_GUARD_OFF", "").lower() not in ("", "0", "false", "no")


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _log(msg: str) -> None:
    if os.environ.get("WORK_GUARD_LOG", "1") == "0":
        return
    try:
        p = Path.home() / LOG_RELPATH
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}\n")
    except OSError:
        pass


def _skip_path(rel: str) -> bool:
    return Path(rel).name in SELF_NAMES


# --------------------------------------------------------------------------- #
# secret scanning — tier 1 blocks history, tier 2 only reports
# --------------------------------------------------------------------------- #
# Pattern literals are written with a character class on the first char so this file
# never matches itself.
_TIER1 = (
    ("GitHub token", r"\b[g]hp_[A-Za-z0-9]{16,}|\b[g]ho[rps]?_[A-Za-z0-9]{16,}|[g]ithub_pat_[A-Za-z0-9_]{20,}"),
    ("AWS key id", r"\b[A]KIA[0-9A-Z]{16}\b"),
    ("Google API key", r"\b[A]Iza[0-9A-Za-z_\-]{30,}"),
    ("Slack token", r"\bxox[braprs]-[A-Za-z0-9\-]{10,}"),
    ("Stripe key", r"\bsk_(live|test)_[A-Za-z0-9]{16,}|\bpk_live_[A-Za-z0-9]{16,}"),
    ("OpenAI-style key", r"\bsk-[A-Za-z0-9_\-]{20,}|\bproxykey-[A-Za-z0-9]{16,}"),
    ("Telegram bot token", r"\b\d{8,10}:AA[A-Za-z0-9_\-]{30,}"),
    ("Private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    ("JWT", r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\."),
    ("URL with credentials", r"://[^/\s:@]{2,60}:[^/\s:@]{3,60}@"),
    ("Card number (Luhn)", r"(?<![0-9])[0-9]{15,16}(?![0-9])"),
    ("Secret-shaped assignment",
     r"(?i)\b(passw(?:or)?d|passwd|secret|token|api[_-]?k(?:ey)?|apikey|auth[_-]?k(?:ey)?"
     r"|access[_-]?key|client[_-]?secret|private[_-]?key|seed[_-]?(?:phrase|words)?)\b"
     r"['\"`]?\s*[:=]\s*['\"`]?\s*"
     r"(?!\$|\{|<|\*|REDACT|redact|PLACEHOLDER|your|YOUR|example|scrypt|\bxx)"
     r"[A-Za-z0-9+/=_\-.]{12,}"),
)
_TIER2 = (
    ("Personal email domain", r"(?i)@(gmail|outlook|hotmail|icloud|yahoo|proton(?:mail)?)\.(?:com|me)\b"),
    ("Piped sudo password", r"(?i)\bsudo\s+-" + r"S\b"),
    ("Account-number tail", r"(?i)\b(?:acct|account|card)\b[^0-9\n]{0,12}\d{4,}\b"),
)
_T1 = [(n, re.compile(p)) for n, p in _TIER1]
_T2 = [(n, re.compile(p)) for n, p in _TIER2]

# Lines shaped like secrets that are really code or docs: env lookups, placeholders,
# config *key* names, non-Luhn digit runs, commented-out examples. Skipping these keeps
# the scanner from crying wolf — an agent trained to bypass a noisy guard is how the one
# real secret eventually lands.
_FP = re.compile(
    r"(?i)"
    r"os\.environ|getenv|key_env|config get|settings\.|\.get\("
    r"|[:=]\s*(?:full-attention|none|null|true|false|auto|str|int|bool|dict|list|placeholder)\b"
    r"|^\s*(?:#|//|\*|--|>\s)"
    r"|\b(?:name|key|var|field|column|file|path|dir|env|mode|unit|service|table)\s*[:=]\s*\w+$"
)
_LINE_ALLOW = re.compile(r"guard:allow\b")  # per-line escape hatch for must-show docs


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _false_positive(line: str, rule: str) -> bool:
    if _LINE_ALLOW.search(line) or _FP.search(line):
        return True
    if rule.startswith("Card number"):
        # A real PAN satisfies the Luhn checksum; device/PCI/serial digit runs almost
        # never do, which is what actually fires this rule in infra notes.
        m = re.search(r"(?<![0-9])([0-9]{15,16})(?![0-9])", line)
        if not m or not _luhn_ok(m.group(1)):
            return True
    return False


def _mask(text: str) -> str:
    text = text.strip()
    return text if len(text) <= 24 else text[:10] + "…" + str(len(text)) + " chars"


def scan_text(text: str, *, origin: str = "text") -> list[dict]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, rx in _T1:
            for m in rx.finditer(line):
                if _false_positive(line, name):
                    continue
                hits.append({"tier": 1, "rule": name, "where": f"{origin}:{lineno}",
                             "snippet": _mask(m.group(0))})
        for name, rx in _T2:
            for m in rx.finditer(line):
                hits.append({"tier": 2, "rule": name, "where": f"{origin}:{lineno}",
                             "snippet": _mask(m.group(0))})
    return hits


def _scan_diff_added(out: str, origin: str) -> list[dict]:
    """Scan only the '+' side of a git diff; never the guard's own fake credentials."""
    added, cur = [], "?"
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and not _skip_path(cur):
            added.append(f"{cur}: {line[1:]}")
    return scan_text("\n".join(added), origin=origin)


def scan_staged(repo: Path) -> list[dict]:
    """Staged changes. Untracked-but-staged files have no diff hunk header, so fall back
    to scanning the staged blobs directly."""
    out = _git(repo, "diff", "--cached", "--unified=0")
    if out.strip():
        return _scan_diff_added(out, "staged diff")
    hits = []
    for f in _git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACM").splitlines():
        if _skip_path(f):
            continue
        hits += scan_text(_git(repo, "show", f":{f}", check=False), origin=f)
    return hits


def scan_range(repo: Path, rev_range: str) -> list[dict]:
    return _scan_diff_added(_git(repo, "diff", "--unified=0", rev_range, check=False), "commits")


def scan_worktree(repo: Path, rels: list[str]) -> list[dict]:
    hits = []
    for rel in rels:
        p = repo / rel
        if not p.is_file() or _skip_path(rel) or p.stat().st_size > 400_000:
            continue
        try:
            hits += scan_text(p.read_text(encoding="utf-8"), origin=rel)
        except (OSError, UnicodeDecodeError):
            pass
    return hits


def scan_tree(repo: Path, subs: tuple[str, ...] = SCAN_SUBS) -> list[dict]:
    """Scan the TRACKED tree (what a push would expose), not stray gitignored files."""
    rels = [f for f in _git(repo, "ls-files", *subs, check=False).splitlines() if f.strip()]
    return scan_worktree(repo, rels)


def _block_msg(hits: list[dict], where: str) -> str:
    lines = ["workLab skills guard: secret-shaped string(s) in " + where + ":"]
    lines += [f"  {h['rule']} @ {h['where']}: {h['snippet']}" for h in hits[:10]]
    lines.append("Put the real value in a gitignored path (``*.env`` is ignored) and write the "
                 "PATH in the doc, not the value. Bypass deliberately: git --no-verify or "
                 "WORK_GUARD_OFF=1. If a real secret reached GitHub, follow the scrub steps "
                 "in the hermes-shared-skills skill and rotate it.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# git helpers
# --------------------------------------------------------------------------- #
def _git(repo: Path, *args: str, check: bool = True, timeout: int = GIT_TIMEOUT) -> str:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                           timeout=timeout, check=False)
    except Exception as exc:
        if check:
            raise RuntimeError(f"git {' '.join(args)}: {exc}") from exc
        return ""
    if p.returncode != 0 and check:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()[:300]}")
    return (p.stdout or "").strip()


def _count(repo: Path, *args: str) -> int:
    v = _git(repo, *args, check=False)
    return int(v) if v.isdigit() else 0


def _porcelain(repo: Path, *pathspec: str) -> list[str]:
    # Own subprocess: _git() strips, and porcelain's FIRST line can legitimately start
    # with a status space (" M file") — stripping it shifts every parse by one char.
    try:
        p = subprocess.run(["git", "-C", str(repo), "status", "--porcelain",
                            *(["--", *pathspec] if pathspec else [])],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False)
    except Exception:
        return []
    return [ln for ln in (p.stdout or "").split("\n") if ln.strip()]


def _porcelain_path(ln: str) -> str:
    """Path from a porcelain line (XY + space + path; renames carry 'old -> new')."""
    p = ln[3:].split(" -> ")[-1].strip().strip('"')
    return p


# --------------------------------------------------------------------------- #
# health check
# --------------------------------------------------------------------------- #
def check_skills(repo: Path, *, fetch: bool = False) -> dict:
    """Repo + wiring health. ``problems`` block the nudge/exit code; ``notes`` inform."""
    r: dict = {"repo": str(repo), "ok": False, "problems": [], "notes": []}
    if not (repo / ".git").exists():
        r["problems"].append(f"no git clone at {repo}")
        return r

    if fetch:
        _git(repo, "fetch", "--quiet", "origin", check=False, timeout=NET_TIMEOUT)

    por = _porcelain(repo, SKILLS_SUB)
    mod = [ln for ln in por if not ln.startswith("??")]
    unt = [ln for ln in por if ln.startswith("??")]
    if mod:
        r["problems"].append(f"{len(mod)} uncommitted change(s) in {SKILLS_SUB}/ — no other agent can "
                             "see these: " + ", ".join(Path(_porcelain_path(ln)).name for ln in mod[:6]))
    if unt:
        r["problems"].append(f"{len(unt)} untracked file(s) in {SKILLS_SUB}/ (new references/ dirs are "
                             "invisible to every other agent): "
                             + ", ".join(Path(_porcelain_path(ln)).name for ln in unt[:6]))
    if mod or unt:
        dirty = [_porcelain_path(ln) for ln in por]
        t1 = [h for h in scan_worktree(repo, dirty) if h["tier"] == 1]
        if t1:
            r["problems"].append(f"{len(t1)} secret-shaped string(s) in the dirty skill files — a commit "
                                 "would be blocked: " + "; ".join(f"{h['rule']} @{h['where']}" for h in t1[:4]))
    other = _porcelain(repo, "docs", "files", "README.md")
    if other:
        r["problems"].append(f"{len(other)} uncommitted change(s) under docs//files/ — this repo is the "
                             "system of record: " + ", ".join(Path(_porcelain_path(ln)).name for ln in other[:5]))
    if (repo / ".git" / "rebase-apply").exists() or (repo / ".git" / "MERGE_HEAD").exists():
        r["problems"].append("an in-progress merge/rebase is unfinished — finish or abort it before anything else")

    if _count(repo, "rev-list", "--count", "@{u}..HEAD"):
        n = _count(repo, "rev-list", "--count", "@{u}..HEAD")
        r["problems"].append(f"{n} commit(s) not pushed to origin — other agents cannot pull them")
    behind = _count(repo, "rev-list", "--count", "HEAD..@{u}")
    if behind:
        r["problems"].append(f"clone is {behind} commit(s) behind origin: `git -C {repo} pull --ff-only` "
                             "before editing skills")
    ff = repo / ".git" / "FETCH_HEAD"
    if not ff.exists() or _now() - int(ff.stat().st_mtime) > FETCH_FRESH_S:
        r["notes"].append("origin not fetched in the last 6h — behind/after counts may be stale (check --fetch)")

    em = _git(repo, "config", "user.email", check=False)
    if em != ID_EMAIL:
        r["problems"].append(f"repo git user.email is {em or 'unset'}, expected {ID_EMAIL} "
                             "(personal email in commits lands in repo history; install fixes it)")
    if _git(repo, "config", "core.hooksPath", check=False) != "hooks":
        r["notes"].append("git hooks not wired (core.hooksPath != hooks): run `install`")
    hooks = _config_get("hooks") or {}
    for event, *_ in _hook_defs():
        entries = hooks.get(event) if isinstance(hooks, dict) else None
        if not any(HOOK_MARK in str(e.get("command", "")) for e in (entries or []) if isinstance(e, dict)):
            r["notes"].append(f"Hermes hooks.{event} guard is not registered: run `install`")

    # Shadowing: ~/.hermes/skills beats create_dir/external_dirs in precedence, so a
    # leftover local copy wins silently and its edits never reach git.
    shared = {p.parent.name for p in repo.glob(f"{SKILLS_SUB}/*/*/SKILL.md")}
    local_dir = Path.home() / ".hermes/skills"
    shadows = sorted({c.parent.name for pat in ("*/*/SKILL.md", "*/SKILL.md")
                      for c in local_dir.glob(pat) if c.parent.name in shared})
    if shadows:
        r["problems"].append(f"{len(shadows)} shared skill(s) ALSO exist in ~/.hermes/skills and shadow the "
                             "shared copy — edits there never reach git: " + ", ".join(shadows[:6])
                             + " (diff, merge, then delete the local dirs)")

    readme = repo / SKILLS_SUB / "README.md"
    if readme.exists():
        table = set(re.findall(r"\|\s*`([A-Za-z0-9._-]+)`\s*\|", readme.read_text(encoding="utf-8")))
        missing, ghost = sorted(shared - table), sorted(table - shared)
        if missing:
            r["problems"].append(f"skills missing from the {SKILLS_SUB}/README.md index: " + ", ".join(missing[:8]))
        if ghost:
            r["problems"].append("README index rows with no skill folder: " + ", ".join(ghost[:8]))
    else:
        r["problems"].append(f"{SKILLS_SUB}/README.md is missing")

    r["ok"] = not r["problems"]
    return r


def _fmt_report(r: dict) -> str:
    body = [f"  ! {p}" for p in r["problems"]] + [f"  - {n}" for n in r["notes"]]
    head = (f"workLab skills guard: OK — {r['repo']}" if r["ok"]
            else f"workLab skills guard: {len(r['problems'])} issue(s) in {r['repo']}")
    return head + ("\n" + "\n".join(body) if body else "")


# --------------------------------------------------------------------------- #
# reminder state (one nudge per session, not one per turn)
# --------------------------------------------------------------------------- #
def _state_load() -> dict:
    try:
        return json.loads((Path.home() / STATE_RELPATH).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _state_save(st: dict) -> None:
    try:
        p = Path.home() / STATE_RELPATH
        p.parent.mkdir(parents=True, exist_ok=True)
        cutoff = _now() - 7 * 86400
        st = {k: v for k, v in st.items() if isinstance(v, dict) and v.get("ts", 0) > cutoff}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Hermes shell-hook modes (payload JSON on stdin)
# --------------------------------------------------------------------------- #
def _payload() -> dict:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _field(payload: dict, key: str):
    if key in payload:
        return payload[key]
    extra = payload.get("extra")
    return extra.get(key) if isinstance(extra, dict) else None


def hook_pre_llm() -> None:
    """First turn of a session: pull if clean, nudge once if anything needs attention."""
    payload = _payload()
    if _off():
        return
    if not (_field(payload, "is_first_turn") or payload.get("is_first_turn")):
        return
    repo = _repo()
    if not (repo / ".git").exists():
        return
    try:
        if not _porcelain(repo):
            _git(repo, "pull", "--ff-only", "--quiet", "origin", check=False, timeout=NET_TIMEOUT)
        r = check_skills(repo)
    except Exception as exc:
        _log(f"pre-llm failed: {exc}")
        return
    if r["ok"]:
        return
    sid = str(payload.get("session_id") or "_noid")
    fp = "|".join(r["problems"])[:400]
    st = _state_load()
    seen = st.get(sid, {})
    if seen.get("fp") == fp and _now() - int(seen.get("ts", 0)) < REMINDER_MAX_PER_SESSION_S:
        return
    st[sid] = {"fp": fp, "ts": _now()}
    _state_save(st)
    guard = repo / "files" / "hermes-skills-git" / "work_skills_guard.py"
    ctx = ("[work-skills-guard] The shared skills clone needs attention (sync rules: "
           f"{SKILLS_SUB}/README.md; I changed nothing):\n"
           + "\n".join(f"  * {p}" for p in r["problems"][:8])
           + f"\n  Commit skill edits: python3 {guard} commit-skills"
           + "\n  Bypass everything: WORK_GUARD_OFF=1")
    out = ctx[:1800]
    _log(f"nudge session={sid} problems={len(r['problems'])}")
    print(json.dumps({"context": out}))


def hook_post_tool() -> None:
    """After skill_manage: an edit is only real once it is committed AND pushed."""
    if _off():
        return
    payload = _payload()
    if payload.get("tool_name") != "skill_manage":
        return
    res = payload.get("result")
    if isinstance(res, str):
        try:
            res = json.loads(res)
        except Exception:
            res = {}
    if isinstance(res, dict) and (res.get("error") or res.get("status") == "error"):
        return
    names = sorted({str(n) for k in ("skills", "targets", "names")
                    if isinstance(res, dict) for n in (res.get(k) or []) if n})
    reason = "skill_manage:" + (",".join(names)[:60] if names else "edited")
    try:
        code, msg = commit_skills(_repo(), reason, push=True)
        _log(f"post-tool rc={code}: {msg.splitlines()[0] if msg else ''}")
    except Exception as exc:
        _log(f"post-tool failed: {exc}")


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def commit_skills(repo: Path, reason: str = "manual", *, push: bool = True) -> tuple[int, str]:
    """Scan, commit (skills first, then docs/tools separately), push. Never --force.

    The repo is the system of record for the whole workLab, so dirty docs//files/ get
    their own commit too — but never mixed into the skill commit, and always scanned."""
    _ensure_identity(repo)
    out_lines = []
    t1_dirty = [h for h in scan_worktree(repo, [_porcelain_path(ln) for ln in
                _porcelain(repo, SKILLS_SUB, "docs", "files", "README.md")]) if h["tier"] == 1]
    if t1_dirty:
        return 2, _block_msg(t1_dirty, "the dirty worktree (nothing was staged)")
    for label, paths in (("skills", (SKILLS_SUB,)),
                         ("repo", ("docs", "files", "README.md"))):
        if not _porcelain(repo, *paths):
            continue
        _git(repo, "add", "-A", "--", *paths)
        hits = scan_staged(repo)
        t1 = [h for h in hits if h["tier"] == 1]
        if t1:
            _git(repo, "reset", "-q", "--", *paths, check=False)
            _log(f"refused commit ({len(t1)} tier-1): " + "; ".join(h["rule"] for h in t1[:4]))
            return 2, _block_msg(t1, f"the staged {label} changes")
        t2 = [h for h in hits if h["tier"] == 2]
        files = _git(repo, "diff", "--cached", "--name-only").splitlines()
        names = sorted({f.split("/")[2] for f in files if len(f.split("/")) > 2}) or ["repo"]
        host = subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip() or "?"
        if label == "skills":
            msg = f"{' + '.join(names[:3])}: shared skills edited on {host} ({reason})"
        else:
            top = sorted({"/".join(f.split("/")[:2]) for f in files})
            msg = f"{' + '.join(top[:3])}: repo updates on {host} ({reason})"
        if t2:
            msg += "\n\nGuard review notes (not secrets, check by eye): " \
                   f"{'; '.join(sorted({h['rule'] for h in t2})[:4])}"
        # We just scanned the staged tree ourselves; --no-verify keeps the repo hook
        # from scanning the same content twice.
        _git(repo, "-c", f"user.name={ID_NAME}", "-c", f"user.email={ID_EMAIL}",
             "commit", "-q", "--no-verify", "-m", msg)
        sha = _git(repo, "rev-parse", "--short", "HEAD")
        out_lines.append(f"committed {sha} ({len(files)} file(s)): {msg.splitlines()[0]}")
        if t2:
            out_lines.append("  review notes: "
                             + "; ".join(sorted({f"{h['rule']} @{h['where']}" for h in t2})[:6]))
    if not out_lines:
        return 0, "nothing to commit"
    if not push:
        guard = repo / "files" / "hermes-skills-git" / "work_skills_guard.py"
        return 0, "\n  ".join(out_lines) + f"\n  not pushed: python3 {guard} push"
    code, pmsg = do_push(repo)
    return (code if code else 0), "\n  ".join(out_lines) + "\n  " + pmsg.splitlines()[0]


def do_push(repo: Path, extra: list[str] | None = None) -> tuple[int, str]:
    if _count(repo, "rev-list", "--count", "@{u}..HEAD") == 0:
        return 0, "nothing to push"
    t1 = [h for h in scan_range(repo, "@{u}..HEAD") if h["tier"] == 1]
    if t1:
        return 2, _block_msg(t1, "the unpushed commits")
    try:
        p = subprocess.run(["git", "-C", str(repo), "push", *(extra or [])], capture_output=True,
                           text=True, timeout=NET_TIMEOUT, check=False)
        rc, err = p.returncode, ((p.stderr or "") + (p.stdout or "")).strip()
    except Exception as exc:
        return 1, f"push failed: {exc}"
    if rc == 0:
        _log("pushed ok")
        return 0, "pushed — other agents get this on their next pull"
    if "rejected" in err or "non-fast-forward" in err or "stale info" in err:
        rb = _git(repo, "pull", "--rebase", "origin", "main", check=False, timeout=NET_TIMEOUT)
        busy = (repo / ".git" / "rebase-apply").exists() or (repo / ".git" / "rebase-merge").exists()
        if busy:
            _git(repo, "rebase", "--abort", check=False)
            return 1, "push rejected and the rebase conflicted — merge by hand, never force-push. " + rb[:200]
        rc2 = subprocess.run(["git", "-C", str(repo), "push"], capture_output=True, text=True,
                             timeout=NET_TIMEOUT, check=False).returncode
        return (0, "rebased on origin and pushed") if rc2 == 0 else (1, "push rejected, rebase retry failed: " + rb[:200])
    _log(f"push failed: {err[:200]}")
    return 1, "push failed: " + err[:300]


def _ensure_identity(repo: Path) -> None:
    if _git(repo, "config", "user.email", check=False) != ID_EMAIL:
        _git(repo, "config", "user.name", ID_NAME)
        _git(repo, "config", "user.email", ID_EMAIL)


# --------------------------------------------------------------------------- #
# git-hook modes
# --------------------------------------------------------------------------- #
def git_hook_pre_commit() -> int:
    if _off():
        return 0
    t1 = [h for h in scan_staged(_repo()) if h["tier"] == 1]
    if t1:
        print(_block_msg(t1, "the staged changes"), file=sys.stderr)
        return 1
    return 0


def git_hook_pre_push() -> int:
    """stdin lines: <local_ref> <local_sha> <remote_ref> <remote_sha>."""
    if _off():
        return 0
    repo, bad = _repo(), []
    for line in sys.stdin:
        parts = line.split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if local_sha.startswith("0" * 40):
            continue  # branch deletion: nothing to scan
        if remote_sha.startswith("0" * 40):  # new branch on the remote
            has_parent = _git(repo, "rev-parse", "-q", "--verify", f"{local_sha}~1", check=False)
            rng = f"{local_sha}~1..{local_sha}" if has_parent else local_sha
        else:
            rng = f"{remote_sha}..{local_sha}"
        try:
            bad += [h for h in scan_range(repo, rng) if h["tier"] == 1]
        except Exception:
            return 0
    if bad:
        print(_block_msg(bad, "the commits being pushed"), file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# install / uninstall (per host + Hermes home)
# --------------------------------------------------------------------------- #
def _hook_defs() -> tuple[tuple[str, str, str | None, int], ...]:
    """(event, mode, matcher, timeout). No pre_tool_call hook: agents push through
    terminal/execute_code, which runs real git, which runs the repo's own pre-push hook
    — the scan already happens there."""
    return (
        ("pre_llm_call", "pre-llm", None, 45),
        ("post_tool_call", "post-tool", "^skill_manage$", 90),
    )


def _hook_command(mode: str) -> str:
    return f"{sys.executable or 'python3'} {Path(__file__).resolve()} --hook {mode}"


def install(repo: Path, *, clone_if_missing: bool = True, say=print) -> None:
    if not repo.exists() and clone_if_missing:
        repo.parent.mkdir(parents=True, exist_ok=True)
        say(f"cloning {REMOTE_DEFAULT} -> {repo}")
        if subprocess.run(["git", "clone", REMOTE_DEFAULT, str(repo)], check=False).returncode != 0:
            raise SystemExit("clone failed — this host needs a GitHub deploy key; ask the repo owner")
    if not (repo / ".git").exists():
        raise SystemExit(f"{repo} is not a git clone")
    _ensure_identity(repo)
    say(f"repo git identity: {ID_NAME} <{ID_EMAIL}>")

    hooks = repo / "hooks"
    for name in ("pre-commit", "pre-push"):
        f = hooks / name
        if f.exists():
            f.chmod(0o755)
        else:
            say(f"WARNING: {f} missing — pull this clone so the guard hooks exist")
    _git(repo, "config", "core.hooksPath", "hooks")
    say("git hooks wired (core.hooksPath=hooks): secret scan on every commit and push")

    existing = _config_get("hooks") or {}
    if not isinstance(existing, dict):
        raise SystemExit("hooks config is not a mapping — merge the guard entries in by hand")
    for event, mode, matcher, timeout in _hook_defs():
        want = _hook_command(mode)
        entries = [e for e in (existing.get(event) or []) if isinstance(e, dict)]
        entries = [e for e in entries if HOOK_MARK not in str(e.get("command", ""))]
        entry: dict = {"command": want, "timeout": timeout}
        if matcher:
            entry["matcher"] = matcher
        entries.append(entry)
        existing[event] = entries
        say(f"hooks.{event} -> --hook {mode}")
    _config_set("hooks", existing)
    _allowlist_add()
    say(f"consented {len(_hook_defs())} hook command(s) in shell-hooks-allowlist.json")
    if not os.environ.get("HERMES_DISABLE_SHELL_HOOKS"):
        say("start a NEW session: hooks and the skill index are read at session start")


def _allowlist_add() -> None:
    p = Path.home() / ".hermes" / "shell-hooks-allowlist.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"approvals": []}
    except Exception:
        data = {"approvals": []}
    if not isinstance(data.get("approvals"), list):
        data["approvals"] = []
    have = {(e.get("event"), e.get("command")) for e in data["approvals"] if isinstance(e, dict)}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    added = 0
    for event, mode, _m, _t in _hook_defs():
        cmd = _hook_command(mode)
        if (event, cmd) not in have:
            data["approvals"].append({"event": event, "command": cmd, "approved_at": now,
                                      "source": "work-skills-guard install"})
            added += 1
    if added:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)


def uninstall(repo: Path) -> None:
    existing = _config_get("hooks") or {}
    if isinstance(existing, dict):
        changed = False
        for event, entries in list(existing.items()):
            if not isinstance(entries, list):
                continue
            keep = [e for e in entries if not (isinstance(e, dict) and HOOK_MARK in str(e.get("command", "")))]
            if len(keep) != len(entries):
                existing[event] = keep
                changed = True
        if changed:
            _config_set("hooks", existing)
            print("removed guard entries from the hooks config")
    p = Path.home() / ".hermes" / "shell-hooks-allowlist.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        before = len(data.get("approvals", []))
        data["approvals"] = [e for e in data.get("approvals", [])
                             if not (isinstance(e, dict) and HOOK_MARK in str(e.get("command", "")))]
        if len(data["approvals"]) != before:
            p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"revoked {before - len(data['approvals'])} hook approval(s)")
    except (OSError, ValueError):
        pass
    print("git hooks left wired: git -C", repo, "config --unset core.hooksPath")


# --------------------------------------------------------------------------- #
# config helpers (through the hermes CLI — never hand-edit config.yaml)
# --------------------------------------------------------------------------- #
def _config_get(key: str):
    # --json first: the guard must stay stdlib-only, and stock python3 on some hosts
    # has no PyYAML to parse the default YAML output. Older CLIs without --json fall
    # back to the plain call (and the yaml import below, if available).
    p = subprocess.run(["hermes", "config", "get", "--json", key], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        p = subprocess.run(["hermes", "config", "get", key], capture_output=True, text=True, check=False)
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)
    except Exception:
        pass
    try:
        import yaml
        return yaml.safe_load(p.stdout)
    except Exception:
        raise SystemExit(f"could not parse `hermes config get {key}`; merge the hooks block by hand")


def _config_set(key: str, value) -> None:
    # The guard replaces the whole hooks section it just read (merged, incl. reserved
    # output_spill/outbound sub-sections); Hermes refuses an overwrite of an existing
    # section without --force. Nothing else may live under hooks.* that we drop: we
    # rebuild strictly from _config_get("hooks").
    p = subprocess.run(["hermes", "config", "set", "--force", key, json.dumps(value)],
                       capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise SystemExit(f"hermes config set {key} failed: {(p.stderr or p.stdout).strip()[:300]}")


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def doctor(repo: Path) -> int:
    r = check_skills(repo, fetch=True)
    print(_fmt_report(r))
    print("\nwiring:")
    print(f"  core.hooksPath    : {_git(repo, 'config', 'core.hooksPath', check=False) or 'MISSING'}")
    print(f"  git user.email    : {_git(repo, 'config', 'user.email', check=False) or 'unset'}")
    try:
        appr = json.loads((Path.home() / ".hermes" / "shell-hooks-allowlist.json").read_text(encoding="utf-8")).get("approvals", [])
    except (OSError, ValueError):
        appr = []
    hooks = _config_get("hooks") or {}
    for event, mode, matcher, _t in _hook_defs():
        mine = [e for e in (hooks.get(event) or []) if isinstance(e, dict) and HOOK_MARK in str(e.get("command", ""))]
        good = bool(mine) and all(re.search(rf"--hook {mode}\b", str(e.get("command"))) for e in mine)
        if matcher and mine:
            good = good and all(e.get("matcher") == matcher for e in mine)
        consented = any(isinstance(a, dict) and HOOK_MARK in str(a.get("command", "")) and a.get("event") == event
                        for a in appr)
        state = "ok" if good and consented else ("needs consent" if good else "MISSING — run install")
        print(f"  hooks.{event:<15}: {state}")
    print(f"  log               : ~/{LOG_RELPATH}")
    print(f"  bypass            : WORK_GUARD_OFF=1 | git --no-verify | hooks_auto_accept")
    return 0 if r["ok"] else 1


# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    args = list(argv)
    if args and args[0] == "--hook" and len(args) > 1:
        mode, rest = "hook:" + args[1], args[2:]
    elif args:
        mode, rest = args[0], args[1:]
    else:
        mode, rest = "check", []
    if _off():
        if mode.startswith("hook:") or mode.startswith("git-"):
            return 0  # hooks must stay silent: anything we print becomes agent context
        print("WORK_GUARD_OFF is set — doing nothing")
        return 0
    repo = _repo()
    try:
        if mode == "hook:pre-llm":
            hook_pre_llm(); return 0
        if mode == "hook:post-tool":
            hook_post_tool(); return 0
        if mode == "git-pre-commit":
            return git_hook_pre_commit()
        if mode == "git-pre-push":
            return git_hook_pre_push()
        if mode == "check":
            r = check_skills(repo, fetch="--fetch" in rest)
            print(_fmt_report(r))
            return 0 if r["ok"] else 1
        if mode == "doctor":
            return doctor(repo)
        if mode == "scan-text":
            hits = scan_text(sys.stdin.read(), origin="stdin")
            for h in hits:
                print(f"  T{h['tier']} {h['rule']} @ {h['where']}: {h['snippet']}")
            return 1 if any(h["tier"] == 1 for h in hits) else 0
        if mode == "scan-staged":
            return git_hook_pre_commit()
        if mode == "scan-tree":
            hits = scan_tree(repo)
            for h in hits:
                print(f"  T{h['tier']} {h['rule']} @ {h['where']}: {h['snippet']}")
            n1 = len([h for h in hits if h["tier"] == 1])
            print(f"{n1} tier-1 / {len(hits) - n1} tier-2 hit(s)")
            return 1 if n1 else 0
        if mode == "commit-skills":
            code, msg = commit_skills(repo, "commit-skills", push="--no-push" not in rest)
            print(msg)
            return code
        if mode == "push":
            code, msg = do_push(repo, rest)
            print(msg)
            return code
        if mode == "install":
            install(repo, clone_if_missing="--no-clone" not in rest)
            return 0
        if mode == "uninstall":
            uninstall(repo)
            return 0
    except SystemExit:
        raise
    except Exception as exc:  # a broken guard must never wedge a commit or a session
        _log(f"{mode} crashed: {type(exc).__name__}: {exc}")
        if mode.startswith("hook:") or mode.startswith("git-"):
            return 0
        print(f"guard error (fail-open): {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0
    print(__doc__)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
