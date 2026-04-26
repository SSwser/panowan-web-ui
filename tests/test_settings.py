import os
import unittest
from unittest.mock import patch

from app.paths import (
    CONTAINER_MODEL_ROOT,
    CONTAINER_PANOWAN_ENGINE_ROOT,
    CONTAINER_RUNTIME_ROOT,
    CONTAINER_UPSCALE_ENGINE_ROOT,
    default_runtime_roots,
    job_store_path,
    lora_checkpoint_path,
    model_root_path,
    output_dir_path,
    worker_store_path,
)
from app.settings import load_settings


class RuntimePathRootsTests(unittest.TestCase):
    def test_default_runtime_roots_use_host_layout_outside_container(self) -> None:
        roots = default_runtime_roots(repo_root="/repo", in_container=False)

        self.assertEqual(roots.model_root, os.path.join("/repo", "data", "models"))
        self.assertEqual(
            roots.runtime_root,
            os.path.join("/repo", "data", "runtime"),
        )
        self.assertEqual(
            roots.panowan_engine_root,
            os.path.join("/repo", "third_party", "PanoWan"),
        )
        self.assertEqual(
            roots.upscale_engine_root,
            os.path.join("/repo", "third_party", "Upscale"),
        )

    def test_default_runtime_roots_use_container_layout_in_container(self) -> None:
        roots = default_runtime_roots(repo_root="/repo", in_container=True)

        self.assertEqual(roots.model_root, CONTAINER_MODEL_ROOT)
        self.assertEqual(roots.runtime_root, CONTAINER_RUNTIME_ROOT)
        self.assertEqual(roots.panowan_engine_root, CONTAINER_PANOWAN_ENGINE_ROOT)
        self.assertEqual(roots.upscale_engine_root, CONTAINER_UPSCALE_ENGINE_ROOT)


class SettingsTests(unittest.TestCase):
    def test_load_settings_from_environment(self) -> None:
        env = {
            "MODEL_ROOT": "/workspace/models",
            "DEFAULT_PROMPT": "custom prompt",
            "GENERATION_TIMEOUT_SECONDS": "42",
            "HOST": "127.0.0.1",
            "PORT": "9000",
        }

        with patch.dict(os.environ, env, clear=False):
            loaded = load_settings()

        self.assertEqual(loaded.model_root, "/workspace/models")
        self.assertEqual(loaded.wan_model_path, model_root_path("/workspace/models"))
        self.assertEqual(
            loaded.lora_checkpoint_path,
            lora_checkpoint_path("/workspace/models"),
        )
        self.assertEqual(loaded.default_prompt, "custom prompt")
        self.assertEqual(loaded.generation_timeout_seconds, 42)
        self.assertEqual(loaded.host, "127.0.0.1")
        self.assertEqual(loaded.port, 9000)
        self.assertEqual(
            loaded.lora_absolute_path,
            lora_checkpoint_path("/workspace/models"),
        )

    def test_load_settings_ignores_leaf_path_environment_overrides(self) -> None:
        env = {
            "SERVICE_ROLE": "worker",
            "MODEL_ROOT": "/models-x",
            "RUNTIME_DIR": "/runtime-ignored",
            "PANOWAN_ENGINE_DIR": "/engine-ignored",
            "UPSCALE_ENGINE_DIR": "/upscale-ignored",
            "WAN_MODEL_PATH": "/custom-wan",
            "LORA_CHECKPOINT_PATH": "/custom-lora.ckpt",
            "OUTPUT_DIR": "/custom-output",
            "JOB_STORE_PATH": "/custom-jobs.json",
            "WORKER_STORE_PATH": "/custom-workers.json",
            "UPSCALE_WEIGHTS_DIR": "/custom-upscale-weights",
            "UPSCALE_OUTPUT_DIR": "/custom-upscale-output",
        }
        with patch.dict(os.environ, env, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.model_root, "/models-x")
        self.assertEqual(loaded.runtime_dir, CONTAINER_RUNTIME_ROOT)
        self.assertEqual(loaded.panowan_engine_dir, CONTAINER_PANOWAN_ENGINE_ROOT)
        self.assertEqual(loaded.upscale_engine_dir, CONTAINER_UPSCALE_ENGINE_ROOT)
        self.assertEqual(loaded.wan_model_path, model_root_path("/models-x"))
        self.assertEqual(
            loaded.lora_checkpoint_path,
            lora_checkpoint_path("/models-x"),
        )
        self.assertEqual(loaded.output_dir, output_dir_path(CONTAINER_RUNTIME_ROOT))
        self.assertEqual(loaded.job_store_path, job_store_path(CONTAINER_RUNTIME_ROOT))
        self.assertEqual(
            loaded.worker_store_path,
            worker_store_path(CONTAINER_RUNTIME_ROOT),
        )
        self.assertEqual(loaded.upscale_weights_dir, "/models-x")
        self.assertEqual(loaded.upscale_output_dir, loaded.output_dir)

    def test_load_settings_container_defaults_include_runtime_layout(self) -> None:
        with patch.dict(os.environ, {"SERVICE_ROLE": "worker"}, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.runtime_dir, CONTAINER_RUNTIME_ROOT)
        self.assertEqual(loaded.panowan_engine_dir, CONTAINER_PANOWAN_ENGINE_ROOT)
        self.assertEqual(loaded.upscale_engine_dir, CONTAINER_UPSCALE_ENGINE_ROOT)
        self.assertEqual(loaded.output_dir, output_dir_path(CONTAINER_RUNTIME_ROOT))
        self.assertEqual(loaded.job_store_path, job_store_path(CONTAINER_RUNTIME_ROOT))
        self.assertEqual(
            loaded.worker_store_path,
            worker_store_path(CONTAINER_RUNTIME_ROOT),
        )
        self.assertEqual(loaded.upscale_weights_dir, CONTAINER_MODEL_ROOT)
        self.assertEqual(
            loaded.upscale_output_dir,
            output_dir_path(CONTAINER_RUNTIME_ROOT),
        )
        self.assertEqual(loaded.upscale_timeout_seconds, 1800)

    def test_load_settings_uses_model_root_for_derived_paths(self) -> None:
        with patch.dict(
            os.environ,
            {"SERVICE_ROLE": "worker", "MODEL_ROOT": "/models"},
            clear=True,
        ):
            loaded = load_settings()

        self.assertEqual(loaded.model_root, "/models")
        self.assertEqual(loaded.wan_model_path, model_root_path("/models"))
        self.assertEqual(loaded.lora_checkpoint_path, lora_checkpoint_path("/models"))
        self.assertEqual(
            loaded.wan_diffusion_absolute_path,
            "/models/Wan-AI/Wan2.1-T2V-1.3B/diffusion_pytorch_model.safetensors",
        )
        self.assertEqual(
            loaded.lora_absolute_path,
            "/models/PanoWan/latest-lora.ckpt",
        )
        self.assertEqual(loaded.upscale_weights_dir, "/models")

    def test_load_settings_ignores_removed_legacy_panowan_app_dir(self) -> None:
        env = {"PANOWAN_APP_DIR": "/legacy/PanoWan", "SERVICE_ROLE": "worker"}
        with patch.dict(os.environ, env, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.panowan_engine_dir, CONTAINER_PANOWAN_ENGINE_ROOT)

    def test_load_settings_keeps_behavior_overrides(self) -> None:
        env = {
            "SERVICE_ROLE": "worker",
            "UPSCALE_TIMEOUT_SECONDS": "900",
            "MAX_CONCURRENT_JOBS": "3",
            "WORKER_POLL_INTERVAL_SECONDS": "1.5",
            "WORKER_STALE_SECONDS": "45",
        }
        with patch.dict(os.environ, env, clear=True):
            loaded = load_settings()

        self.assertEqual(loaded.upscale_timeout_seconds, 900)
        self.assertEqual(loaded.max_concurrent_jobs, 3)
        self.assertEqual(loaded.worker_poll_interval_seconds, 1.5)
        self.assertEqual(loaded.worker_stale_seconds, 45.0)

    def test_container_path_join_uses_posix_separators(self):
        from app.paths import container_join

        self.assertEqual(
            container_join("/engines/panowan", "models/PanoWan/latest-lora.ckpt"),
            "/engines/panowan/models/PanoWan/latest-lora.ckpt",
        )

    def test_container_path_join_handles_root_base(self):
        from app.paths import container_join

        self.assertEqual(container_join("/", "models/foo"), "/models/foo")
