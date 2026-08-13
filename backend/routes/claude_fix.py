"""Fase 4: Claude Code Control via Telegram (2026-08-13, PRD "Owner Control Center"
§26-32, permintaan Agus). Owner trigger Claude Code lewat command Telegram utk
diagnose+fix satu bug di PMS atau ai-chat-bot, WAJIB lolos regression gate repo terkait,
lalu deploy MAJU setelah tap konfirmasi eksplisit - TIDAK ADA rollback otomatis (sengaja
ditunda, keputusan Agus - lihat plan lengkap di riwayat sesi).

Prinsip desain (jangan dilanggar tanpa alasan kuat):
1. Controller (modul ini) pegang kendali penuh - `claude` CLI cuma boleh baca/edit file
   + beberapa command diagnostik read-only di worktree sekali pakai. Commit/push/deploy/
   restart SELALU dilakukan controller sendiri secara deterministik, TIDAK PERNAH oleh
   agent.
2. Isolasi STRUKTURAL - `claude -p` jalan di `git worktree` terpisah (bukan folder live
   yang sedang melayani request), tidak pernah dikasih tahu path folder live/kredensial.
3. Profil izin (settings_*.json) hidup di luar worktree yang diaturnya.
4. Exit code regression gate = SATU-SATUNYA sumber kebenaran lolos/gagal.
5. 1 job berat sekaligus (_claude_run_lock) + resource cap OS-level (systemd-run --scope
   -p MemoryMax/-p CPUQuota tiap subprocess) - jawaban langsung insiden ffmpeg 2026-08-13
   yang menghabiskan semua RAM/swap VPS ini & bikin 504 di semua layanan.
"""
from core import *
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # /root/agusta/backend
CC_DIR = ROOT / "claude_code_control"
LOG_DIR = CC_DIR / "logs"

# Path absolut ke npm nvm - JANGAN pakai `bash -lc 'source nvm...'` (systemd-run --scope
# tidak reliable source shell profile), path ini SUDAH diverifikasi langsung dipakai &
# berhasil build ai-chat-bot frontend di sesi yang sama (2026-08-13).
_NPM_BIN = "/root/.nvm/versions/node/v20.20.2/bin/npm"

REPO_CONFIG = {
    "pms": {
        "label": "Pelangi PMS",
        "live_dir": Path("/root/agusta"),
        "worktree_base": Path("/root/agusta_cc_worktrees"),
        "venv_sub": "backend/venv",
        "gate_module": "scripts.test_regresi",
        "gate_cwd_sub": "backend",
        "gate_timeout_sec": 240,
        "gate_env_file": None,  # proses controller sendiri (pms-backend) SUDAH punya semua env via systemd Environment=
        "settings_profile": CC_DIR / "settings_pms.json",
        "claude_timeout_sec": 900,
        "deploy_mode": "github_actions",
        "service_name": "pms-backend",
    },
    "aichatbot": {
        "label": "AI Chat Bot",
        "live_dir": Path("/root/ai-chat-bot"),
        "worktree_base": Path("/root/ai-chat-bot_cc_worktrees"),
        "venv_sub": "backend/venv",
        "gate_module": "scripts.test_hallucination_guards",
        "gate_cwd_sub": "backend",
        "gate_timeout_sec": 900,  # skenario live-LLM, lambat
        "gate_env_file": Path("/root/ai-chat-bot/backend/.env"),  # repo terpisah, kredensial beda dari pms-backend
        "settings_profile": CC_DIR / "settings_aichatbot.json",
        "claude_timeout_sec": 900,
        "deploy_mode": "manual",  # repo ini TIDAK punya GitHub Actions
        "service_name": "ai-chat-bot-backend",
        "frontend_build_dir": Path("/root/ai-chat-bot/frontend"),
        "frontend_deploy_dir": Path("/var/www/ai-chat-bot/build"),
    },
}

ACTIVE_STATUSES = ["preparing", "diagnosing", "gate_running", "deploying"]

_claude_run_lock = asyncio.Lock()


def _telegram():
    """Import deferred (dalam fungsi, bukan top-level) - hindari circular import,
    trik yang sama dipakai routes/incidents.py utk _push_incident_urgent."""
    from routes.telegram_bot import _kirim_pesan, _kirim_pesan_dengan_tombol, _edit_pesan, BOT_CONFIG
    return _kirim_pesan, _kirim_pesan_dengan_tombol, _edit_pesan, BOT_CONFIG


async def _run(argv: list, cwd: Optional[Path] = None, env: Optional[dict] = None,
                timeout: Optional[float] = None) -> tuple:
    """Jalankan subprocess - argv LIST (bukan shell string), aman thd shell injection
    apa pun isi argumennya (instruksi fix ini teks mentah ketikan owner via Telegram).
    Return (exit_code, stdout, stderr) UTUH (tidak dipotong di sini - potong di titik
    tampil/simpan, bukan di sini, supaya JSON --output-format tidak pernah terpotong)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd) if cwd else None, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return -1, "", str(e)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "(timeout)"


async def _run_scoped(unit: str, argv: list, cwd: Optional[Path], env: Optional[dict],
                       timeout: float, memory_max: str, cpu_quota: str) -> tuple:
    """Sama seperti _run, dibungkus systemd-run --scope dgn cgroup resource cap sendiri -
    jawaban konkret insiden ffmpeg (2026-08-13): 1 subprocess fitur ini TIDAK BOLEH bisa
    menghabiskan RAM/CPU seluruh VPS walau in-process lock somehow terlewat. Timeout
    mematikan lewat `systemctl stop <unit>.scope` - itu mematikan SELURUH process tree
    cgroup-nya (bukan cuma child langsung - `claude` itu proses Node yang bisa punya
    anak proses, `proc.kill()` saja tidak cukup)."""
    full_argv = [
        "systemd-run", "--scope", "--quiet", "--unit", unit,
        "-p", f"MemoryMax={memory_max}", "-p", f"CPUQuota={cpu_quota}", "--",
        *argv,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_argv, cwd=str(cwd) if cwd else None, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return -1, "", str(e)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
    except asyncio.TimeoutError:
        await _run(["systemctl", "stop", f"{unit}.scope"], timeout=15)
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
        return -1, "", "(timeout - proses dihentikan paksa via systemd-run scope)"


def _parse_dotenv(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# Worktree isolation
# ---------------------------------------------------------------------------

async def _create_worktree(cfg: dict, run_id: str) -> tuple:
    live = cfg["live_dir"]
    branch = f"claude-fix/{run_id}"
    wt = cfg["worktree_base"] / run_id
    cfg["worktree_base"].mkdir(parents=True, exist_ok=True)

    rc, _, err = await _run(["git", "-C", str(live), "fetch", "origin", "main"], timeout=60)
    if rc != 0:
        raise RuntimeError(f"Gagal fetch origin/main: {err[-500:]}")
    rc, _, err = await _run(
        ["git", "-C", str(live), "worktree", "add", "-b", branch, str(wt), "origin/main"], timeout=60,
    )
    if rc != 0:
        raise RuntimeError(f"Gagal bikin git worktree: {err[-500:]}")

    # Symlink venv (reuse, JANGAN reinstall - berat di box 2 core/3.8GB ini).
    # node_modules SENGAJA TIDAK disentuh - gate keduanya backend-only, build frontend
    # cuma terjadi di folder live saat deploy nanti, bukan di worktree diagnose.
    venv_source = (live / cfg["venv_sub"]).resolve()
    venv_target = wt / cfg["venv_sub"]
    venv_target.parent.mkdir(parents=True, exist_ok=True)
    if venv_source.exists() and not venv_target.exists():
        os.symlink(venv_source, venv_target)

    return wt, branch


async def _remove_worktree(cfg: dict, worktree_path: Optional[Path], branch: Optional[str]):
    if not worktree_path or not branch:
        return
    live = cfg["live_dir"]
    await _run(["git", "-C", str(live), "worktree", "remove", "--force", str(worktree_path)], timeout=30)
    await _run(["git", "-C", str(live), "branch", "-D", branch], timeout=15)
    # best-effort - branch mungkin belum sempat ke-push sama sekali, boleh gagal diam2
    await _run(["git", "-C", str(live), "push", "origin", "--delete", branch], timeout=30)


# ---------------------------------------------------------------------------
# Claude invocation
# ---------------------------------------------------------------------------

async def _run_claude(cfg: dict, worktree_path: Path, instruction: str, run_id: str) -> dict:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # paksa selalu lewat OAuth session Agus yg sudah dikonfirmasi, bukan API key nyasar
    argv = [
        "claude", "-p", instruction,
        "--output-format", "json",
        "--permission-mode", "dontAsk",
        "--settings", str(cfg["settings_profile"]),
        "--model", "sonnet",
    ]
    rc, out, err = await _run_scoped(
        f"claude-fix-{run_id}", argv, cwd=worktree_path, env=env,
        timeout=cfg["claude_timeout_sec"], memory_max="1200M", cpu_quota="150%",
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{run_id}.json").write_text(out or err)
    if rc != 0:
        return {"ok": False, "raw": (out + "\n" + err).strip() or "(tidak ada output)"}
    try:
        parsed = json.loads(out)
    except (ValueError, json.JSONDecodeError):
        return {"ok": False, "raw": (out + "\n" + err).strip()[-1500:]}
    return {"ok": True, "data": parsed}


async def _run_gate(cfg: dict, worktree_path: Path, run_id: str, attempt_no: int) -> tuple:
    venv_python = worktree_path / cfg["venv_sub"] / "bin" / "python"
    gate_env = os.environ.copy()
    if cfg.get("gate_env_file"):
        gate_env.update(_parse_dotenv(cfg["gate_env_file"]))
    rc, out, err = await _run_scoped(
        f"claude-gate-{run_id}-{attempt_no}",
        [str(venv_python), "-m", cfg["gate_module"]],
        cwd=worktree_path / cfg["gate_cwd_sub"], env=gate_env,
        timeout=cfg["gate_timeout_sec"], memory_max="800M", cpu_quota="150%",
    )
    combined = (out + "\n" + err).strip()
    return rc, combined


# ---------------------------------------------------------------------------
# Orkestrasi utama
# ---------------------------------------------------------------------------

async def handle_fix_command(repo: str, instruction: str, owner_user: dict, chat_id: Any, token: str):
    """Entry point dari /fixpms & /fixbot (telegram_bot.py). Balas cepat lalu jalankan
    seluruh alur di background - webhook TIDAK BOLEH nunggu proses multi-menit."""
    kirim, _, _, _ = _telegram()
    cfg = REPO_CONFIG[repo]
    if _claude_run_lock.locked():
        active = await db.claude_code_runs.find_one({"status": {"$in": ACTIVE_STATUSES}}, sort=[("started_at", -1)])
        if active:
            await kirim(token, chat_id,
                f"⏳ Masih ada proses berjalan ({REPO_CONFIG[active['repo']]['label']}: "
                f"\"{active['instruction'][:80]}\") - tunggu itu selesai dulu.")
        else:
            await kirim(token, chat_id, "⏳ Ada proses lain sedang berjalan, coba lagi sebentar.")
        return
    await kirim(token, chat_id,
        f"🔧 Mulai diagnosa {cfg['label']}...\n\n\"{instruction}\"\n\n"
        f"Bisa makan beberapa menit, saya kabari begitu selesai.")
    asyncio.create_task(_run_claude_fix(repo, instruction, owner_user, chat_id, token))


async def _run_claude_fix(repo: str, instruction: str, owner_user: dict, chat_id: Any, token: str):
    kirim, kirim_tombol, edit, _ = _telegram()
    cfg = REPO_CONFIG[repo]
    run_id = uuid.uuid4().hex[:12]

    async with _claude_run_lock:
        doc = {
            "id": run_id, "repo": repo, "requested_by": owner_user.get("id"),
            "requested_by_nama": owner_user.get("nama"), "instruction": instruction,
            "status": "preparing", "branch": None, "worktree_path": None,
            "git_sha_before": None, "git_sha_after": None, "diff_files": [], "diff_stat_text": "",
            "claude_result_text": "", "claude_cost_usd": None, "claude_num_turns": None,
            "claude_log_path": str(LOG_DIR / f"{run_id}.json"),
            "gate_attempts": [], "telegram_chat_id": chat_id, "telegram_message_id": None,
            "started_at": now_iso(), "gate_finished_at": None, "confirmed_at": None,
            "confirmed_by": None, "deployed_at": None, "error": None,
        }
        await db.claude_code_runs.insert_one(dict(doc))

        worktree_path, branch = None, None
        try:
            rc, sha_out, _ = await _run(["git", "-C", str(cfg["live_dir"]), "rev-parse", "origin/main"], timeout=30)
            git_sha_before = sha_out.strip() if rc == 0 else None
            await db.claude_code_runs.update_one(
                {"id": run_id}, {"$set": {"status": "diagnosing", "git_sha_before": git_sha_before}},
            )
            worktree_path, branch = await _create_worktree(cfg, run_id)
            await db.claude_code_runs.update_one(
                {"id": run_id}, {"$set": {"worktree_path": str(worktree_path), "branch": branch}},
            )
            result = await _run_claude(cfg, worktree_path, instruction, run_id)
        except Exception as e:
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "error", "error": str(e)}})
            await kirim(token, chat_id, f"❌ Gagal memulai diagnosa {cfg['label']}: {e}")
            await _remove_worktree(cfg, worktree_path, branch)
            return

        if not result["ok"]:
            await db.claude_code_runs.update_one(
                {"id": run_id}, {"$set": {"status": "error", "error": result["raw"][-1500:]}},
            )
            await kirim(token, chat_id, f"❌ Diagnosa {cfg['label']} gagal/timeout.\n\n{result['raw'][-1200:]}")
            return  # worktree DIBIARKAN - jangan buang kerja diagnostik walau error

        claude_data = result["data"]
        claude_text = (claude_data.get("result") or "").strip()
        await db.claude_code_runs.update_one({"id": run_id}, {"$set": {
            "claude_result_text": claude_text[:2000],
            "claude_cost_usd": claude_data.get("total_cost_usd"),
            "claude_num_turns": claude_data.get("num_turns"),
        }})

        _, diff_stat, _ = await _run(["git", "-C", str(worktree_path), "diff", "--stat", "HEAD"], timeout=30)
        diff_stat = diff_stat.strip()
        if not diff_stat:
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "no_changes"}})
            await kirim(token, chat_id,
                f"ℹ️ Diagnosa {cfg['label']} selesai - Claude TIDAK membuat perubahan apa pun.\n\n"
                f"Ringkasan: {claude_text[:1500] or '(tidak ada ringkasan)'}")
            await _remove_worktree(cfg, worktree_path, branch)
            return

        _, files_out, _ = await _run(["git", "-C", str(worktree_path), "diff", "--name-only", "HEAD"], timeout=30)
        diff_files = [f for f in files_out.strip().splitlines() if f]

        # Controller sendiri yang commit (pesan sistem, BUKAN ditulis Claude) - prinsip
        # desain #1: jejak commit deterministik, kurangi 1 kelas resiko prompt-injection.
        #
        # PENTING: venv_sub (symlink ke venv live, lihat _create_worktree) HARUS dikecualikan
        # eksplisit dari staging - ditemukan lewat tes sintetis (2026-08-13): pola `venv/` di
        # .gitignore TIDAK menangkap symlink yang diberi nama sama (git cuma ignore
        # direktori ASLI dgn pola trailing-slash itu, bukan symlink yang menunjuk ke
        # direktori). Tanpa pengecualian ini, `git add -A` polos akan men-stage symlink
        # venv itu sendiri ke commit fix - begitu di-deploy & di-merge ke folder live,
        # symlink itu bisa menimpa/bentrok dgn folder venv ASLI (direktori sungguhan,
        # bukan symlink) yang sedang dipakai service produksi.
        await _run(["git", "-C", str(worktree_path), "add", "-A", "--", ".", f":!{cfg['venv_sub']}"], timeout=30)
        commit_msg = (f"[claude-fix {run_id}] {instruction[:200]}\n\n"
                      f"Diminta {owner_user.get('nama') or 'owner'} via Telegram (Fase 4 Claude Code Control).")
        await _run([
            "git", "-C", str(worktree_path),
            "-c", "user.email=claude-fix@pelangihomestay.com", "-c", "user.name=Claude Fix Bot",
            "commit", "-m", commit_msg,
        ], timeout=30)
        _, sha_out, _ = await _run(["git", "-C", str(worktree_path), "rev-parse", "HEAD"], timeout=30)

        await db.claude_code_runs.update_one({"id": run_id}, {"$set": {
            "diff_files": diff_files, "diff_stat_text": diff_stat,
            "git_sha_after": sha_out.strip() or None,
        }})

        await _run_gate_and_report(cfg, run_id, attempt_no=1)


async def _run_gate_and_report(cfg: dict, run_id: str, attempt_no: int):
    kirim, kirim_tombol, edit, BOT_CONFIG = _telegram()
    run = await db.claude_code_runs.find_one({"id": run_id})
    if not run:
        return
    token = BOT_CONFIG["owner"]["token"]
    chat_id = run["telegram_chat_id"]
    worktree_path = Path(run["worktree_path"])

    await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "gate_running"}})
    rc, tail = await _run_gate(cfg, worktree_path, run_id, attempt_no)
    await db.claude_code_runs.update_one({"id": run_id}, {
        "$push": {"gate_attempts": {"attempt": attempt_no, "exit_code": rc, "output_tail": tail[-1500:], "ran_at": now_iso()}},
        "$set": {"gate_finished_at": now_iso()},
    })

    run = await db.claude_code_runs.find_one({"id": run_id})
    diff_stat = run.get("diff_stat_text", "")
    diff_files = run.get("diff_files", [])
    claude_text = run.get("claude_result_text", "")
    frontend_touched = any(f.startswith("frontend/") for f in diff_files)

    if rc == 0:
        await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "gate_passed_awaiting_confirm"}})
        teks = (
            f"✅ Regression gate LOLOS - {cfg['label']}\n\n"
            f"Instruksi: \"{run['instruction']}\"\n\n"
            f"Ringkasan Claude:\n{claude_text[:800] or '(tidak ada ringkasan)'}\n\n"
            f"Perubahan: {diff_stat}\n\n"
        )
        if frontend_touched:
            teks += ("⚠️ Ada file frontend/** ikut berubah - regression gate ini 100% backend, "
                      "TIDAK menguji kode frontend sama sekali. Tinjau lebih teliti.\n\n")
        teks += "Tinjau ringkasan di atas sebelum tap Deploy."
        tombol = [
            [{"text": "🚀 Deploy ke Produksi", "callback_data": f"deploy_fix:{run_id}"}],
            [{"text": "🔁 Ulangi Regression Gate", "callback_data": f"regate_fix:{run_id}"}],
            [{"text": "🗑 Batalkan", "callback_data": f"discard_fix:{run_id}"}],
        ]
    else:
        await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "gate_failed"}})
        teks = (
            f"❌ Regression gate GAGAL (percobaan #{attempt_no}) - {cfg['label']}\n\n"
            f"Instruksi: \"{run['instruction']}\"\n\n"
            f"Perubahan: {diff_stat}\n\n"
            f"Output gate (potongan akhir):\n{tail[-1200:]}"
        )
        if run["repo"] == "aichatbot":
            teks += ("\n\n⚠️ Gate ini punya sedikit flakiness yang sudah diketahui (skenario "
                      "live-LLM kadang gagal acak, tidak selalu terkait perubahan kode) - coba "
                      "tap 🔁 Ulangi dulu sebelum simpulkan ini regresi asli.")
        tombol = [
            [{"text": "🔁 Ulangi Regression Gate", "callback_data": f"regate_fix:{run_id}"}],
            [{"text": "🗑 Buang percobaan ini", "callback_data": f"discard_fix:{run_id}"}],
        ]

    msg_id = run.get("telegram_message_id")
    if msg_id:
        await edit(token, chat_id, msg_id, teks, tombol)
    else:
        sent = await kirim_tombol(token, chat_id, teks, tombol)
        if sent and sent.get("message_id"):
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"telegram_message_id": sent["message_id"]}})


async def retry_gate(run_id: str, owner_user: dict) -> Optional[str]:
    """Dipanggil dari callback `regate_fix:` - re-run gate SAJA (TIDAK panggil claude -p
    baru) thd commit worktree yang sama, murah & tidak melaundering kegagalan asli.
    Return None kalau berhasil di-antre (hasil menyusul via edit pesan), atau teks error
    kalau ditolak."""
    run = await db.claude_code_runs.find_one({"id": run_id})
    if not run:
        return "Run tidak ditemukan."
    if run["status"] not in ("gate_failed", "gate_passed_awaiting_confirm"):
        return "Run ini tidak dalam status yang bisa diulang gate-nya."
    if _claude_run_lock.locked():
        return "Ada proses lain sedang berjalan, coba lagi sebentar."
    _, _, edit, BOT_CONFIG = _telegram()
    cfg = REPO_CONFIG[run["repo"]]
    attempt_no = len(run.get("gate_attempts", [])) + 1

    if run.get("telegram_message_id"):
        await edit(BOT_CONFIG["owner"]["token"], run["telegram_chat_id"], run["telegram_message_id"],
                   f"🔁 Mengulangi regression gate {cfg['label']} (percobaan #{attempt_no})...", [])

    async def _locked():
        async with _claude_run_lock:
            await _run_gate_and_report(cfg, run_id, attempt_no)

    asyncio.create_task(_locked())
    return None


async def discard_run(run_id: str, owner_user: dict) -> str:
    """Dipanggil dari callback `discard_fix:` - buang worktree/branch, tandai discarded.
    Aksi ringan (bukan job berat), tidak butuh _claude_run_lock."""
    run = await db.claude_code_runs.find_one({"id": run_id})
    if not run:
        return "Run tidak ditemukan."
    if run["status"] in ("discarded", "deployed", "deploying"):
        return "Sudah diproses sebelumnya."
    cfg = REPO_CONFIG[run["repo"]]
    await _remove_worktree(cfg, Path(run["worktree_path"]) if run.get("worktree_path") else None, run.get("branch"))
    await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "discarded"}})
    return f"🗑 Dibuang - {cfg['label']}: \"{run['instruction'][:150]}\""


async def confirm_deploy(run_id: str, owner_user: dict) -> Optional[str]:
    """Dipanggil dari callback `deploy_fix:` - INI konfirmasi 2-langkah yang dimaksud
    (owner sudah lihat ringkasan diff di pesan sebelumnya, tap ini = konfirmasi aktif).
    Return None kalau berhasil diantre (pesan diedit "deploy berjalan", hasil menyusul),
    atau teks error kalau ditolak (status basi/tombol dobel-tap/lock)."""
    kirim, _, edit, BOT_CONFIG = _telegram()
    run = await db.claude_code_runs.find_one({"id": run_id})
    if not run:
        return "Run tidak ditemukan."
    if run["status"] != "gate_passed_awaiting_confirm":
        return "Sudah diproses sebelumnya atau belum siap deploy."
    if _claude_run_lock.locked():
        return "Ada proses lain sedang berjalan, coba lagi sebentar."

    await db.claude_code_runs.update_one({"id": run_id}, {"$set": {
        "status": "deploying", "confirmed_at": now_iso(), "confirmed_by": owner_user.get("nama"),
    }})
    await log_activity(owner_user, "claude_fix_deploy_confirm",
                        f"{run['repo']} - {run['instruction'][:150]}", entity=run_id)
    token = BOT_CONFIG["owner"]["token"]
    if run.get("telegram_message_id"):
        await edit(token, run["telegram_chat_id"], run["telegram_message_id"], "⏳ Deploy sedang berjalan...", [])

    async def _locked():
        async with _claude_run_lock:
            await _do_deploy(run_id, owner_user)

    asyncio.create_task(_locked())
    return None


async def _do_deploy(run_id: str, owner_user: dict):
    kirim, _, edit, BOT_CONFIG = _telegram()
    run = await db.claude_code_runs.find_one({"id": run_id})
    cfg = REPO_CONFIG[run["repo"]]
    token = BOT_CONFIG["owner"]["token"]
    chat_id = run["telegram_chat_id"]
    msg_id = run.get("telegram_message_id")
    branch = run["branch"]
    live = cfg["live_dir"]
    worktree_path = Path(run["worktree_path"])

    async def lapor(teks):
        if msg_id:
            await edit(token, chat_id, msg_id, teks, [])
        else:
            await kirim(token, chat_id, teks)

    try:
        rc, _, err = await _run(["git", "-C", str(worktree_path), "push", "origin", f"{branch}:{branch}"], timeout=60)
        if rc != 0:
            raise RuntimeError(f"Gagal push branch {branch}: {err[-800:]}")

        await _run(["git", "-C", str(live), "fetch", "origin"], timeout=60)
        rc, _, err = await _run(["git", "-C", str(live), "checkout", "main"], timeout=30)
        if rc != 0:
            raise RuntimeError(f"Gagal checkout main di folder live: {err[-800:]}")
        rc, _, err = await _run(["git", "-C", str(live), "merge", "--ff-only", f"origin/{branch}"], timeout=30)
        if rc != 0:
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {
                "status": "deploy_failed",
                "error": "merge --ff-only gagal - main sudah maju sejak worktree dibuat",
            }})
            await lapor(
                f"❌ Deploy dibatalkan - branch main {cfg['label']} sudah berubah sejak fix ini "
                f"dibuat (merge --ff-only gagal, TIDAK dipaksa/force). Perlu ditinjau manual - "
                f"branch {branch} masih tersimpan.\n\n{err[-600:]}",
            )
            return

        if cfg["deploy_mode"] == "github_actions":
            ok, detail = await _deploy_pms(cfg)
        else:
            ok, detail = await _deploy_aichatbot(cfg, run.get("diff_files", []))

        if ok:
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "deployed", "deployed_at": now_iso()}})
            _, sha_out, _ = await _run(["git", "-C", str(live), "rev-parse", "HEAD"], timeout=15)
            sha_short = sha_out.strip()[:8] or "?"
            await log_activity(owner_user, "claude_fix_deployed", f"{run['repo']} sha {sha_short}", entity=run_id)
            await lapor(f"✅ Deploy berhasil - {cfg['label']} (sha {sha_short})\n\n{detail}")
            await _remove_worktree(cfg, worktree_path, branch)
        else:
            await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "deploy_failed", "error": detail[:1500]}})
            await lapor(f"⚠️ Deploy {cfg['label']} bermasalah:\n\n{detail}")
            # worktree TETAP disimpan - jangan buang kalau deploy gagal, perlu bisa ditinjau
    except Exception as e:
        await db.claude_code_runs.update_one({"id": run_id}, {"$set": {"status": "deploy_failed", "error": str(e)}})
        await lapor(f"❌ Deploy {cfg['label']} gagal: {e}")


async def _deploy_pms(cfg: dict) -> tuple:
    """Reuse PERSIS jalur deploy yang sudah ada & teruji (push main -> GitHub Actions ->
    deploy.sh) - TIDAK bikin jalur deploy baru. Konfirmasi restart via poll MainPID
    (dependency-free, `gh` tidak terautentikasi di box ini) - timeout = inconclusive,
    BUKAN gagal (build bisa lama)."""
    _, pid_before, _ = await _run(["systemctl", "show", "-p", "MainPID", "--value", cfg["service_name"]], timeout=15)
    pid_before = pid_before.strip()

    rc, _, err = await _run(["git", "-C", str(cfg["live_dir"]), "push", "origin", "main"], timeout=60)
    if rc != 0:
        return False, f"Gagal push origin main: {err[-800:]}"

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        await asyncio.sleep(10)
        _, pid_now, _ = await _run(["systemctl", "show", "-p", "MainPID", "--value", cfg["service_name"]], timeout=15)
        _, active, _ = await _run(["systemctl", "is-active", cfg["service_name"]], timeout=15)
        if pid_now.strip() and pid_now.strip() != pid_before and active.strip() == "active":
            return True, f"Push ke main berhasil, {cfg['service_name']} sudah restart & aktif."
    return True, (
        f"Push ke main berhasil, tapi belum terlihat restart {cfg['service_name']} dalam 3 "
        f"menit (build bisa lama) - cek manual via journalctl/GitHub Actions."
    )


async def _deploy_aichatbot(cfg: dict, diff_files: list) -> tuple:
    """Tidak ada CI utk repo ini - replikasi PERSIS langkah manual yang sudah ada
    (dipakai sepanjang sesi ini): push main -> (kalau ada file frontend/** berubah) build
    + rsync -> restart service -> cek aktif."""
    rc, _, err = await _run(["git", "-C", str(cfg["live_dir"]), "push", "origin", "main"], timeout=60)
    if rc != 0:
        return False, f"Gagal push origin main: {err[-800:]}"

    detail_parts = ["git push origin main berhasil."]
    if any(f.startswith("frontend/") for f in diff_files):
        env = os.environ.copy()
        env["CI"] = "true"
        rc, out, err = await _run_scoped(
            f"claude-deploy-build-{uuid.uuid4().hex[:8]}",
            [_NPM_BIN, "run", "build"], cwd=cfg["frontend_build_dir"], env=env,
            timeout=300, memory_max="1200M", cpu_quota="100%",
        )
        if rc != 0:
            return False, f"Push berhasil tapi build frontend GAGAL - service TIDAK di-restart:\n{(out + err)[-1200:]}"
        rc, _, err = await _run([
            "rsync", "-a", "--delete", f"{cfg['frontend_build_dir']}/build/", f"{cfg['frontend_deploy_dir']}/",
        ], timeout=60)
        if rc != 0:
            return False, f"Push+build berhasil tapi rsync frontend gagal:\n{err[-800:]}"
        detail_parts.append("Build+deploy frontend berhasil.")

    rc, _, err = await _run(["systemctl", "restart", cfg["service_name"]], timeout=30)
    if rc != 0:
        return False, f"Push berhasil tapi restart service gagal:\n{err[-800:]}"
    await asyncio.sleep(3)
    _, active, _ = await _run(["systemctl", "is-active", cfg["service_name"]], timeout=15)
    if active.strip() != "active":
        return False, f"Service {cfg['service_name']} TIDAK aktif setelah restart - cek log manual."
    detail_parts.append(f"{cfg['service_name']} restart & aktif.")
    return True, " ".join(detail_parts)


async def reconcile_stale_claude_runs():
    """Restart-safety (2026-08-13, pola sama db.scheduler_state di telegram_bot.py) -
    restart pms-backend di tengah 1 run bikin asyncio.Lock in-process otomatis balik
    unlocked (benar), tapi dokumen DB bisa nyangkut "in progress" selamanya kalau tidak
    ditandai ulang di startup.

    Bug NYATA ditemukan sendiri lewat tes live end-to-end pertama (2026-08-13, run
    89c584735721, disaksikan Agus): utk repo="pms", `_deploy_pms()` men-push ke `main`
    yang MEMICU GitHub Actions restart `pms-backend` - tapi kode yang nunggu+lapor hasil
    deploy itu jalan DI DALAM `pms-backend` sendiri, jadi restart yang dipicunya sendiri
    membunuh proses yang sedang nyupervisi deploy-nya SEBELUM sempat menulis
    status="deployed". Versi lama fungsi ini menandai run itu "error" begitu saja -
    padahal deploy-nya SUDAH BENAR-BENAR BERHASIL (branch ke-merge+push, service sudah
    restart dgn kode baru) - cuma laporan/cleanup finalnya yang terputus. Ini BUKAN race
    langka, tapi PASTI terjadi tiap kali deploy PMS sukses lewat fitur ini.

    Sekarang, khusus status="deploying", verifikasi ke git SEBELUM menyerah - kalau
    `git_sha_after` run itu ternyata sudah jadi bagian riwayat `main` di folder live,
    deploy-nya nyata sukses - pulihkan status jadi "deployed" (bukan "error"), beres-beres
    worktree/branch yang lama nyangkut, & kabari owner via Telegram (edit pesan yang sama,
    yang lain kalau sempat nyangkut di "⏳ Deploy sedang berjalan..." selamanya). Repo lain
    (aichatbot) TIDAK kena masalah ini (restart service-nya beda dari proses controller),
    tapi cek yang sama tetap aman & benar diterapkan ke keduanya."""
    stale_deploying = await db.claude_code_runs.find({"status": "deploying"}, {"_id": 0}).to_list(20)
    for run in stale_deploying:
        cfg = REPO_CONFIG.get(run.get("repo"))
        sha = run.get("git_sha_after")
        if not cfg or not sha:
            continue
        rc, _, _ = await _run(
            ["git", "-C", str(cfg["live_dir"]), "merge-base", "--is-ancestor", sha, "main"], timeout=15,
        )
        if rc != 0:
            continue  # belum kebukti ke-merge - biarkan jatuh ke penandaan "error" umum di bawah
        await db.claude_code_runs.update_one(
            {"id": run["id"]},
            {"$set": {"status": "deployed", "deployed_at": now_iso(), "error": None,
                      "recovered_note": "Deploy sebenarnya sukses - status dipulihkan otomatis saat "
                                         "startup (proses lama terputus restart yang dipicunya sendiri)."}},
        )
        try:
            kirim, _, edit, BOT_CONFIG = _telegram()
            token = BOT_CONFIG["owner"]["token"]
            if run.get("telegram_message_id"):
                await edit(token, run["telegram_chat_id"], run["telegram_message_id"],
                           f"✅ Deploy berhasil - {cfg['label']} (sha {sha[:8]})\n\n"
                           f"(Status dipulihkan otomatis - proses sempat terputus oleh restart "
                           f"yang dipicunya sendiri, tapi deploy-nya nyata sukses.)", [])
        except Exception as e:
            logging.getLogger("claude_fix").warning(f"Gagal lapor recovery deploy run {run['id']}: {e}")
        try:
            await _remove_worktree(cfg, Path(run["worktree_path"]), run.get("branch"))
        except Exception as e:
            logging.getLogger("claude_fix").warning(f"Gagal cleanup worktree run {run['id']} stlh recovery: {e}")

    await db.claude_code_runs.update_many(
        {"status": {"$in": ACTIVE_STATUSES}},
        {"$set": {"status": "error", "error": "Interrupted by backend restart"}},
    )
