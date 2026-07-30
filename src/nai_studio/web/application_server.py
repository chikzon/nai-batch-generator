# -*- coding: utf-8 -*-
"""애플리케이션 서버 — 설정 편집(실시간 자동저장) + 생성 시작 신호 + 미리보기.

레거시 축소 단계 4로 compat/legacy_surface에서 옮겨 왔다. 서비스 모듈은
직접 import하고, 레거시 전역(경로·조립 함수·상태)은 생성 시 주입되는
`namespace`(레거시 globals())를 **호출 시점에** 조회한다 — 기존
`patch.object(APP, …)` monkeypatch와 STARTUP_RECOVERY_NOTICE 같은 rebind
전역이 그대로 반영된다. endpoint 문자열은 여기 없다.
"""
from __future__ import annotations

from typing import Any, Mapping

from src.nai_studio.services import builder_handlers as _builder_handlers
from src.nai_studio.services import collection_handlers as _collection_handlers
from src.nai_studio.services import comparison_handlers as _comparison_handlers
from src.nai_studio.services import generation_handlers as _generation_handlers
from src.nai_studio.services import management_state as _management_state
from src.nai_studio.services import resource_bridge as _resource_bridge
from src.nai_studio.services import setting_store as _setting_store
from src.nai_studio.services import settings_handlers as _settings_handlers
from src.nai_studio.services import image_tool_handlers as _image_tool_handlers
from src.nai_studio.web import app_wiring as _app_wiring
from src.nai_studio.web import server_runtime as _server_runtime


class ConfigServer:
    """설정 편집(실시간 자동저장) + 생성 시작 신호 + 실시간 미리보기를 모두 담당."""

    def __init__(
        self,
        cfg,
        persist_jobs=False,
        spec=None,
        *,
        namespace: Mapping[str, Any],
    ):
        self._app = namespace
        self.cfg = cfg
        self.spec = namespace["load_spec"]() if spec is None else spec
        self.live = namespace["LiveState"](persist_jobs=persist_jobs)
        self.start_event = namespace["threading"].Event()
        self.httpd = None
        self.url = None
        self.config_lock = namespace["threading"].RLock()
        self.config_revision = 0
        self.anlas_balance_cache = None
        self.anlas_balance_token_key = None
        self.pending_batch_config = None
        # 백업 원문은 디스크에 임시 저장하지 않고 마지막 검사본 한 개만 메모리에 둔다.
        # 선택 복원 요청은 SHA와 diff 지문이 모두 맞을 때만 이 바이트를 사용한다.
        self.backup_preview_blob = None
        self.backup_preview_sha256 = ""
        self.pack_preview_blob = None
        self.pack_preview_sha256 = ""
        self.pack_preview_filename = ""
        self.pending_variation = None

    def latest_config_from_disk(self):
        return _management_state.latest_config_from_disk(
            self.cfg,
            self._app["SETTINGS_FILE"],
            self._app["DEFAULT_CONFIG"],
            self._app["_config_projection_operations"](),
        )

    def use_latest_config(self):
        merged = self.latest_config_from_disk()
        self.cfg.clear()
        self.cfg.update(merged)
        return merged

    def snapshot_config(self):
        app = self._app
        try:
            settings_out = _setting_store.setting_catalog(
                app["_setting_store_paths"](),
                app["_setting_store_operations"](),
                app["CATEGORY_META"],
            )
        except Exception as e:
            app["log"].warning(f"세팅 로드 실패: {e}")
            settings_out = []
        return {
            "config": {**{k: v for k, v in self.cfg.items()
                          if not k.startswith("_")},
                       "_revision": self.config_revision},
            "settings": settings_out,
            "scene_clashes": app["scene_num_clashes"](),
            "fragments": app["list_fragments"](),
            "scenes": app["load_scenes"](),
            "spec": self.spec,
            "styles": app["list_styles"](self.spec),
            "builder": app["load_builder"](),
            "scene_presets": app["list_scene_presets"](),
            "startup_recovery": app["STARTUP_RECOVERY_NOTICE"],
        }

    def snapshot_blueprint(self):
        """현재 화면값의 파생 설계도. 토큰과 전체 사용자 자료는 포함하지 않는다."""
        app = self._app
        deepcopy = app["copy"].deepcopy
        with self.config_lock:
            resolution = app["inherited_blueprint_resolution"](self.cfg)
            return {
                "ok": True,
                # 기존 소비자는 계속 blueprint 하나만 읽어도 된다.
                "blueprint": resolution["blueprint"],
                "inheritance": {
                    **deepcopy(resolution.get("project") or {}),
                    "projects": [
                        {
                            "id": item.get("id"),
                            "name": item.get("name"),
                            "fingerprint": item.get("fingerprint"),
                            "updated_at": item.get("updated_at"),
                        }
                        for item in (self.cfg.get("blueprint_projects") or [])
                        if isinstance(item, dict)
                    ],
                    "provenance": deepcopy(resolution.get("provenance") or {}),
                    "conflicts": deepcopy(resolution.get("conflicts") or []),
                },
                "knowledge_assets": app["knowledge_assets_from_config"](
                    self.cfg),
            }

    def handle_blueprint_project(self, body):
        return _settings_handlers.handle_blueprint_project(
            self,
            {"body": body},
            self._app["_settings_handler_operations"](),
        )

    def snapshot_sequence(self, name=""):
        """기존 세팅 파일을 바꾸지 않고 공통 순서 계획으로 보여 준다."""
        app = self._app
        selected = next(
            (item for item in app["list_settings"]()
             if str(item.get("name") or "") == str(name or "")),
            None,
        )
        if selected is None:
            return {"ok": False, "error": "세팅을 찾을 수 없습니다."}
        plan = app["sequence_plan_from_setting"](selected)
        return {
            "ok": True,
            "sequence": plan,
            "steps": len(plan["steps"]),
        }

    def snapshot_jobs(self):
        return _management_state.snapshot_jobs(
            self,
            self._app["_config_projection_operations"](),
        )

    def handle_job_command(self, body):
        data = self._app["json"].loads(body or b"{}")
        return _generation_handlers.handle_job_command(
            self, data, self._app["_generation_handler_operations"]())

    def handle_generate_one(self):
        return _generation_handlers.handle_generate_one(
            self, None, self._app["_generation_handler_operations"]())

    def handle_i2i(self, body):
        try:
            data = self._app["json"].loads(body or b"{}")
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return _generation_handlers.handle_i2i(
            self, data, self._app["_generation_handler_operations"]())

    def handle_character_variation_save(self, body):
        return _collection_handlers.handle_character_variation_save(
            self,
            {"body": body},
            self._app["_collection_handler_operations"](),
        )

    def handle_regen(self, body):
        try:
            data = self._app["json"].loads(body or b"{}")
        except Exception as error:
            return {"ok": False, "error": str(error)}
        return _generation_handlers.handle_regen(
            self, data, self._app["_generation_handler_operations"]())

    def handle_scene_run(self):
        return _generation_handlers.handle_scene_run(
            self, None, self._app["_generation_handler_operations"]())

    def handle_role_save(self, body):
        return _setting_store.save_role(
            self._app["_setting_store_paths"](),
            self._app["_setting_store_operations"](),
            body,
        )

    def handle_sceneset_save(self, body):
        return _setting_store.save_preset(
            self._app["_setting_store_paths"](),
            self._app["_setting_store_operations"](),
            body,
            self.cfg,
        )

    def handle_option_item(self, body):
        return _setting_store.update_option(
            self._app["_setting_store_paths"](),
            self._app["_setting_store_operations"](),
            body,
            self.snapshot_config,
        )

    def handle_style_save(self, body):
        return _builder_handlers.handle_style_save(
            self,
            {"body": body},
            self._app["_builder_handler_operations"](),
        )

    def handle_compare_promote(self, body):
        # 기존 @serialized_data_write(BASE_DIR)와 같은 잠금 의미다.
        with self._app["shared_data_transaction"](self._app["BASE_DIR"]):
            return _comparison_handlers.handle_compare_promote(
                self,
                {"body": body},
                self._app["_comparison_handler_operations"](),
            )

    def handle_compare_preview(self, body):
        """자료 비교 생성의 실제 장수·비용 범위를 계산한다. 생성이나 저장은 하지 않는다."""
        try:
            data = self._app["json"].loads(body or b"{}")
            opus = None
            if self.anlas_balance_cache is not None:
                opus = bool(self.anlas_balance_cache.get("opus"))
            return self._app["comparison_plan"](
                self.cfg, data, self.spec, opus=opus)
        except Exception as e:
            return {"ok": False, "errors": [str(e)], "error": str(e)}

    def handle_compare_run(self, body):
        return _comparison_handlers.handle_compare_run(
            self,
            {"body": body},
            self._app["_comparison_handler_operations"](),
        )

    def handle_compare_rerun(self, body):
        return _comparison_handlers.handle_compare_rerun(
            self,
            {"body": body},
            self._app["_comparison_handler_operations"](),
        )

    def handle_inspect(self, body, filename="", save_flag=""):
        return _collection_handlers.handle_inspect(
            self,
            {
                "body": body,
                "filename": filename,
                "save_flag": save_flag,
            },
            self._app["_collection_handler_operations"](),
        )

    def handle_resource_import(self, body, filename=""):
        """Vibe 교환 문서를 기존 저장소에 비활성 자원으로 안전하게 추가."""
        try:
            return _resource_bridge.import_legacy_resources(
                self,
                self._app["_resource_import_paths"](),
                self._app["_resource_import_operations"](),
                body,
                filename,
            )
        except Exception as e:
            self._app["log"].warning(f"Vibe·Reference 묶음 가져오기 실패: {e}")
            return {"ok": False, "error": str(e)}

    def handle_ref_add(self, body, kind, filename=""):
        return _image_tool_handlers.handle_ref_add(
            self,
            {"body": body, "kind": kind, "filename": filename},
            self._app["_image_tool_operations"](),
        )

    def handle_ref_save(self, body):
        return _image_tool_handlers.handle_ref_save(
            self,
            {"body": body},
            self._app["_image_tool_operations"](),
        )

    def handle_director(
        self,
        body,
        tool,
        prompt="",
        defry="0",
        scale="4",
        filename="",
    ):
        return _image_tool_handlers.handle_director(
            self,
            {
                "body": body,
                "tool": tool,
                "prompt": prompt,
                "defry": defry,
                "scale": scale,
                "filename": filename,
            },
            self._app["_image_tool_operations"](),
        )

    def handle_norm_save(self, body):
        return _builder_handlers.handle_norm_save(
            self,
            {"body": body},
            self._app["_builder_handler_paths"](),
            self._app["_builder_handler_operations"](),
        )

    def handle_save(self, body):
        return _settings_handlers.handle_save(
            self,
            {"body": body},
            self._app["_settings_handler_operations"](),
        )

    def handle_scene_save(self, body):
        return _settings_handlers.handle_scene_save(
            self,
            {"body": body},
            self._app["_settings_handler_operations"](),
        )

    def handle_start(self):
        return _generation_handlers.handle_start(
            self,
            None,
            self._app["_generation_handler_operations"](),
        )

    def start(self, open_browser=True):
        app = self._app
        paths = _server_runtime.ServerRuntimePaths(
            static_dir=app["UI_DIR"],
            port_range=app["PREVIEW_PORT_RANGE"],
        )
        operations = _server_runtime.ServerRuntimeOperations(
            build_operation_sets=_app_wiring.build_route_operation_sets,
            request_handler=app["ConfigRequestHandler"],
            start_http=app["start_http_server"],
            browser_open=app["webbrowser"].open,
            logger=app["log"],
        )
        return _server_runtime.start_server_runtime(
            self,
            app["_route_bindings"](),
            paths,
            operations,
            open_browser=open_browser,
        )


__all__ = ["ConfigServer"]
