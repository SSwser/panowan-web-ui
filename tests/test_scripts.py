from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptBoundaryTests(unittest.TestCase):
    def read_script(self, name):
        return (ROOT / "scripts" / name).read_text(encoding="utf-8")

    def test_dockerfile_builds_realesrgan_backend_venv(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("AS upscale-realesrgan-deps", dockerfile)
        self.assertIn("/opt/venvs/upscale-realesrgan", dockerfile)
        self.assertIn(
            "third_party/Upscale/realesrgan/requirements.txt",
            dockerfile,
        )
        self.assertIn(
            "COPY --from=upscale-realesrgan-deps /opt/venvs/upscale-realesrgan /opt/venvs/upscale-realesrgan",
            dockerfile,
        )

    def test_dockerfile_installs_ffmpeg_system_command(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ffmpeg", dockerfile)

    def test_realesrgan_sources_own_generated_vendor_boundary(self):
        backend_root = ROOT / "third_party" / "Upscale" / "realesrgan"
        self.assertFalse((ROOT / "third_party" / "Upscale" / ".gitignore").exists())
        backend_gitignore = (backend_root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("vendor/", backend_gitignore)
        self.assertIn(".tmp/", backend_gitignore)
        self.assertIn("build/", backend_gitignore)
        self.assertIn("__pycache__/", backend_gitignore)

        sources_root = backend_root / "sources"
        self.assertTrue((sources_root / "__main__.py").exists())
        self.assertTrue((sources_root / "inference_realesrgan_video.py").exists())
        self.assertTrue((sources_root / "realesrgan" / "utils.py").exists())
        self.assertFalse((backend_root / "overlay").exists())

    def test_realesrgan_runner_delegates_to_materialized_vendor_entrypoint(self):
        runner = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "runner.py"
        ).read_text(encoding="utf-8")
        self.assertIn('vendor_main = backend_root / "vendor" / "__main__.py"', runner)
        self.assertIn("runpy.run_path", runner)
        self.assertIn("sys.argv", runner)

    def test_realesrgan_vendor_entrypoint_uses_flat_layout_without_runtime_pip(self):
        # The vendored runtime is the contract: a flat ``vendor/`` directory
        # whose ``__main__.py`` prepends itself to ``sys.path`` and delegates
        # to the trimmed ``inference_realesrgan_video.main`` — no runtime pip,
        # no environment variable discovery, no fallback paths.
        entry = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "sources" / "__main__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Path(__file__).resolve().parent", entry)
        self.assertIn("sys.path.insert", entry)
        self.assertIn("import inference_realesrgan_video", entry)
        self.assertNotIn("pip.main", entry)
        self.assertNotIn("pip install", entry)
        # The legacy adapter and nested ``vendor/Real-ESRGAN`` tree must be
        # gone so they cannot drift back in.
        self.assertFalse(
            (ROOT / "third_party" / "Upscale" / "realesrgan" / "adapter.py").exists()
        )
        self.assertFalse(
            (
                ROOT
                / "third_party"
                / "Upscale"
                / "realesrgan"
                / "vendor"
                / "Real-ESRGAN"
            ).exists()
        )

    def test_realesrgan_runtime_bundle_does_not_require_basicsr_package(self):
        requirements = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "requirements.txt"
        ).read_text(encoding="utf-8")
        vendor = ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor"
        runner = (vendor / "inference_realesrgan_video.py").read_text(encoding="utf-8")
        utils = (vendor / "realesrgan" / "utils.py").read_text(encoding="utf-8")
        arch = (vendor / "realesrgan" / "archs" / "srvgg_arch.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("basicsr", requirements)
        self.assertNotIn("from basicsr", runner)
        self.assertIn("GFPGANer = None", runner)
        self.assertNotIn("load_file_from_url", utils)
        self.assertNotIn("ARCH_REGISTRY", arch)

    def test_realesrgan_runtime_package_inits_are_trimmed(self):
        vendor_pkg = (
            ROOT / "third_party" / "Upscale" / "realesrgan" / "vendor" / "realesrgan"
        )
        package_init = (vendor_pkg / "__init__.py").read_text(encoding="utf-8")
        arch_init = (vendor_pkg / "archs" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("from .utils import RealESRGANer", package_init)
        self.assertNotIn("from .data", package_init)
        self.assertNotIn("from .models", package_init)
        self.assertNotIn("from .version", package_init)
        self.assertEqual(
            arch_init.strip(),
            'from .srvgg_arch import SRVGGNetCompact\n\n__all__ = ["SRVGGNetCompact"]',
        )

    def test_realesrgan_runner_only_exposes_supported_cli_surface(self):
        runner = (
            ROOT
            / "third_party"
            / "Upscale"
            / "realesrgan"
            / "vendor"
            / "inference_realesrgan_video.py"
        ).read_text(encoding="utf-8")
        self.assertIn('default="realesr-animevideov3"', runner)
        self.assertNotIn("RealESRGAN_x4plus", runner)
        self.assertNotIn("--denoise_strength", runner)
        self.assertNotIn("--alpha_upsampler", runner)
        self.assertNotIn('"--ext",', runner)

    def test_start_api_does_not_download_or_check_gpu(self):
        script = self.read_script("start-api.sh")
        self.assertIn("python -m app.api_service", script)
        self.assertNotIn("hf download", script)
        self.assertNotIn("nvidia-smi", script)
        self.assertNotIn("check-runtime.sh", script)

    def test_start_worker_checks_runtime_and_starts_worker(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("check-runtime.sh", script)
        self.assertIn("python -m app.worker_service", script)
        self.assertNotIn("hf download", script)

    def test_check_runtime_invokes_backends_verify(self):
        script = self.read_script("check-runtime.sh")
        self.assertIn("python -m app.backends verify", script)

    def test_env_sh_does_not_define_duplicated_runtime_path_defaults(self):
        script = self.read_script("lib/env.sh")
        self.assertNotIn('export PANOWAN_ENGINE_DIR="${PANOWAN_ENGINE_DIR:-', script)
        self.assertNotIn('export WAN_MODEL_PATH="${WAN_MODEL_PATH:-', script)
        self.assertNotIn('export LORA_CHECKPOINT_PATH="${LORA_CHECKPOINT_PATH:-', script)
        self.assertNotIn('export OUTPUT_DIR="${OUTPUT_DIR:-', script)
        self.assertNotIn('export JOB_STORE_PATH="${JOB_STORE_PATH:-', script)
        self.assertNotIn('export WORKER_STORE_PATH="${WORKER_STORE_PATH:-', script)
        self.assertNotIn('export UPSCALE_ENGINE_DIR="${UPSCALE_ENGINE_DIR:-', script)
        self.assertNotIn('export UPSCALE_OUTPUT_DIR="${UPSCALE_OUTPUT_DIR:-', script)

    def test_env_sh_exports_python_derived_settings(self):
        script = self.read_script("lib/env.sh")
        self.assertIn("from app.settings import load_settings", script)
        self.assertIn("panowan_export_python_settings", script)
        self.assertIn('"WAN_MODEL_PATH": settings.wan_model_path', script)
        self.assertIn('"OUTPUT_DIR": settings.output_dir', script)
        self.assertIn('"UPSCALE_OUTPUT_DIR": settings.upscale_output_dir', script)

    def test_start_worker_supports_vmtouch(self):
        script = self.read_script("start-worker.sh")
        self.assertIn("VMTOUCH_MODELS", script)

    def test_docker_proxy_forwards_compose_interpolation_vars_to_wsl(self):
        script = self.read_script("docker-proxy.sh")
        self.assertIn("docker_proxy_export_wslenv_var", script)
        self.assertIn("for name in TAG MODEL_ROOT PORT APT_MIRROR PYPI_INDEX", script)
        self.assertIn("WSLENV", script)

    def test_claude_mem_migrate_sh_exists_with_required_flags(self):
        script = self.read_script("claude-mem-migrate.sh")
        self.assertIn('replace_sqlite=0', script)
        self.assertIn('reset_chroma=0', script)
        self.assertIn('skip_process_check=0', script)
        self.assertIn('force=0', script)
        self.assertIn('--replace-sqlite', script)
        self.assertIn('--reset-chroma', script)
        self.assertIn('--skip-process-check', script)
        self.assertIn('--force', script)

    def test_claude_mem_migrate_sh_keeps_protected_count_checks(self):
        script = self.read_script("claude-mem-migrate.sh")
        self.assertIn('protected_tables=(sdk_sessions user_prompts observations session_summaries)', script)
        self.assertIn('Compacted DB does not match protected live counts', script)
        self.assertIn('Post-replacement protected table mismatch', script)
        self.assertIn('rm -f "$wal_path" "$shm_path"', script)
        self.assertIn('rm -rf "$chroma_dir"', script)
        self.assertIn('rm -f "$chroma_state_path"', script)

    def test_claude_mem_diagnose_sh_reports_bloat_and_recommendation_inputs(self):
        script = self.read_script("claude-mem-diagnose.sh")
        self.assertIn('page_count', script)
        self.assertIn('freelist_count', script)
        self.assertIn('page_size', script)
        self.assertIn('journal_mode', script)
        self.assertIn('pending_messages', script)
        self.assertIn('sdk_sessions', script)
        self.assertIn('user_prompts', script)
        self.assertIn('observations', script)
        self.assertIn('session_summaries', script)
        self.assertIn('freelist_pct=', script)
        self.assertIn('recommended_action=', script)

    def test_claude_mem_compact_sh_requires_output_and_uses_vacuum_into(self):
        script = self.read_script("claude-mem-compact.sh")
        self.assertIn('output_db_path=""', script)
        self.assertIn('--output-db', script)
        self.assertIn('VACUUM INTO', script)
        self.assertIn('sqlite3', script)
        self.assertIn('copy_if_exists "$db_path" "$backup_db_path"', script)
        self.assertIn('copy_if_exists "$wal_path" "$backup_wal_path"', script)
        self.assertIn('copy_if_exists "$shm_path" "$backup_shm_path"', script)

    def test_claude_mem_maint_sh_dispatches_supported_subcommands(self):
        script = self.read_script("claude-mem-maint.sh")
        self.assertIn('command_name="${1:-}"', script)
        self.assertIn('diagnose)', script)
        self.assertIn('compact)', script)
        self.assertIn('migrate)', script)
        self.assertIn('exec bash "$script_dir/claude-mem-diagnose.sh"', script)
        self.assertIn('exec bash "$script_dir/claude-mem-compact.sh"', script)
        self.assertIn('exec bash "$script_dir/claude-mem-migrate.sh"', script)

    def test_claude_mem_shell_scripts_source_shared_helper_library(self):
        for name in (
            "claude-mem-diagnose.sh",
            "claude-mem-compact.sh",
            "claude-mem-migrate.sh",
        ):
            script = self.read_script(name)
            self.assertIn('source "$script_dir/lib/claude-mem.sh"', script)
        shared = self.read_script("lib/claude-mem.sh")
        self.assertIn('step()', shared)
        self.assertIn('info()', shared)
        self.assertIn('fail()', shared)
        self.assertIn('resolve_path()', shared)
        self.assertIn('sqlite_scalar()', shared)
        self.assertIn('join_kv_lines()', shared)
        self.assertIn('get_db_counts()', shared)
        self.assertIn('get_db_pragmas()', shared)
        self.assertIn('copy_if_exists()', shared)
        self.assertIn('remove_if_exists()', shared)
        self.assertIn('require_sqlite3()', shared)
        self.assertIn('get_file_size()', shared)
        self.assertIn('compute_freelist_pct()', shared)
        self.assertIn('recommend_compaction()', shared)
        self.assertIn('require_data_dir()', shared)
        self.assertIn('db_path="$resolved_data_dir/claude-mem.db"', shared)
        self.assertIn('wal_path="$resolved_data_dir/claude-mem.db-wal"', shared)
        self.assertIn('shm_path="$resolved_data_dir/claude-mem.db-shm"', shared)
        self.assertIn('chroma_dir="$resolved_data_dir/chroma"', shared)
        self.assertIn('chroma_state_path="$resolved_data_dir/chroma-sync-state.json"', shared)
        self.assertIn('backups_dir="$resolved_data_dir/backups"', shared)
        self.assertIn('resolved_data_dir=$(resolve_path "$1")', shared)
        self.assertIn('python - <<\'PY\'', shared)
        self.assertIn("compact_then_migrate", shared)
        self.assertIn("recommended_action='none'", shared)
        self.assertIn('command -v sqlite3 >/dev/null 2>&1 || fail', shared)
        self.assertIn('cygpath -am "$path"', shared)
        self.assertIn('cp -R "$source" "$destination"', shared)
        self.assertIn('rm -rf "$path"', shared)
        self.assertIn("wc -c < \"$path\" | tr -d '[:space:]'", shared)
        self.assertIn('declare -A values=()', shared)
        self.assertIn('while IFS=\'='\' read -r key value; do', shared)
        self.assertIn('values["$key"]="$value"', shared)
        self.assertIn('done <<< "$1"', shared)
        self.assertIn('kv_to_map()', shared)
        self.assertIn('mkdir -p "$backups_dir"', shared)
        self.assertIn('timestamp=$(date +%Y-%m-%dT%H-%M-%S)', shared)
        self.assertIn('migration_backup_dir="$backups_dir/migration-$timestamp"', shared)
        self.assertIn('mkdir -p "$migration_backup_dir"', shared)
        self.assertIn('ensure_backup_dir()', shared)
        self.assertIn('prepare_migration_backup_dir()', shared)
        self.assertIn('powershell.exe', shared)
        self.assertIn('Get-CimInstance Win32_Process', shared)
        self.assertIn('ensure_stopped_processes()', shared)
        self.assertIn("claude-mem related processes still running:", shared)
        self.assertIn("Unable to inspect processes with PowerShell Get-CimInstance.", shared)
        self.assertIn('patterns=(\'claude-mem\' \'worker-service\' \'chroma-mcp\' \'mcp-server\' \'bun-runner\')', shared)
        self.assertIn('command -v powershell.exe >/dev/null 2>&1 || fail', shared)
        self.assertIn('tr -d \'\\r\'', shared)
        self.assertIn('matches=()', shared)
        self.assertIn('printf \'%s\\n\' "$table" "$(sqlite_scalar "$db_path" "SELECT COUNT(*) FROM $table")"', shared)
        self.assertIn("printf 'page_count=%s\\n' \"$(sqlite_scalar \"$db_path\" 'PRAGMA page_count')\"", shared)
        self.assertIn("printf 'freelist_count=%s\\n' \"$(sqlite_scalar \"$db_path\" 'PRAGMA freelist_count')\"", shared)
        self.assertIn("printf 'page_size=%s\\n' \"$(sqlite_scalar \"$db_path\" 'PRAGMA page_size')\"", shared)
        self.assertIn("printf 'journal_mode=%s\\n' \"$(sqlite_scalar \"$db_path\" 'PRAGMA journal_mode')\"", shared)
        self.assertIn('BEGIN { first = 1 } NF { if (!first) printf ", "; printf "%s", $0; first = 0 }', shared)
        self.assertIn('Path not found: $path', shared)
        self.assertIn('sqlite3 not found in PATH.', shared)
        self.assertIn('Live SQLite DB not found: $db_path', shared)
        self.assertIn('Nothing to do. Pass --replace-sqlite and/or --reset-chroma.', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('recommended_action=$recommended_action', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('output_db=$resolved_output_db_path', self.read_script("claude-mem-compact.sh"))
        self.assertIn('source "$script_dir/lib/claude-mem.sh"', self.read_script("claude-mem-maint.sh"))
        self.assertIn('Unknown subcommand', self.read_script("claude-mem-maint.sh"))
        self.assertIn('Usage: claude-mem-maint.sh <diagnose|compact|migrate> [options]', self.read_script("claude-mem-maint.sh"))
        self.assertIn('command -v bash >/dev/null 2>&1', self.read_script("claude-mem-maint.sh"))
        self.assertIn('shift || true', self.read_script("claude-mem-maint.sh"))
        self.assertIn('case "$command_name" in', self.read_script("claude-mem-maint.sh"))
        self.assertIn('help|-h|--help)', self.read_script("claude-mem-maint.sh"))
        self.assertIn('exit 0', self.read_script("claude-mem-maint.sh"))
        self.assertIn('exit 1', self.read_script("claude-mem-maint.sh"))
        self.assertIn('exec bash', self.read_script("claude-mem-maint.sh"))
        self.assertIn('script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)', self.read_script("claude-mem-maint.sh"))
        self.assertIn('lib/claude-mem.sh', self.read_script("claude-mem-maint.sh"))
        self.assertIn('Usage: claude-mem-diagnose.sh [options]', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('Usage: claude-mem-compact.sh [options]', self.read_script("claude-mem-compact.sh"))
        self.assertIn('Usage: claude-mem-migrate.sh [options]', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('require_data_dir "$data_dir"', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('require_data_dir "$data_dir"', self.read_script("claude-mem-compact.sh"))
        self.assertIn('require_data_dir "$data_dir"', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('require_sqlite3', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('require_sqlite3', self.read_script("claude-mem-compact.sh"))
        self.assertIn('require_sqlite3', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('ensure_backup_dir', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('prepare_migration_backup_dir', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('kv_to_map', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('kv_to_map', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('compute_freelist_pct', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('recommend_compaction', self.read_script("claude-mem-diagnose.sh"))
        self.assertIn('ensure_stopped_processes', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('remove_if_exists "$wal_path"', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('remove_if_exists "$shm_path"', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('remove_if_exists "$chroma_dir"', self.read_script("claude-mem-migrate.sh"))
        self.assertIn('remove_if_exists "$chroma_state_path"', self.read_script("claude-mem-migrate.sh"))

