# -*- coding: utf-8 -*-
"""Program startup and shutdown orchestration for the NAI workspace.

Filesystem layout, legacy migration, HTTP construction, and generation stay
behind injected operations.  This module owns only their externally observable
order and the long-running batch event loop.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class ProgramArguments:
    """CLI values that affect profile isolation and browser launch."""

    argv: tuple[str, ...]
    profile: str
    open_browser: bool


@dataclass(frozen=True)
class ProgramEntryOperations:
    """Dependencies required to enter, run, and cleanly leave the program."""

    prepare_profile: Callable[[str], Any]
    initialize_logging: Callable[[Any], Any]
    acquire_single_instance: Callable[[Any], Any]
    release_single_instance: Callable[[Any], Any]
    migrate_program_data: Callable[[Any], Any]
    load_config: Callable[[Any], dict]
    load_options: Callable[[Any], Any]
    load_spec: Callable[[Any], Any]
    recover_jobs: Callable[[Any], Any]
    create_server: Callable[[dict, Any, Any, Any], Any]
    start_server: Callable[[Any, bool], str | None]
    cleanup_server: Callable[[Any], Any]
    close_logging: Callable[[Any], Any]
    warm_index: Callable[[Any], Any]
    start_daemon: Callable[[Callable[[], None]], Any]
    run_generation: Callable[[Any, dict], Any]
    inherited_blueprint: Callable[..., dict[str, Any]]
    fatal_stop_errors: tuple[type[BaseException], ...]
    log_info: Callable[..., Any]
    log_critical: Callable[..., Any]
    format_traceback: Callable[[], str]
    read_input: Callable[[str], str]
    write_line: Callable[[str], Any]


def parse_program_arguments(argv: Sequence[str]) -> ProgramArguments:
    """Read only the two legacy entry flags and leave all others untouched."""
    values = tuple(str(value) for value in argv)
    profile = ""
    for index, value in enumerate(values):
        if value.startswith("--profile="):
            profile = value.split("=", 1)[1].strip()
            break
        if value == "--profile" and index + 1 < len(values):
            profile = values[index + 1].strip()
            break
    return ProgramArguments(
        argv=values,
        profile=profile,
        open_browser="--no-browser" not in values,
    )


def _warm_server(
    server: Any, operations: ProgramEntryOperations
) -> None:
    try:
        operations.warm_index(server)
    except Exception as error:
        operations.log_info("자동완성 예열 건너뜀: %s", error)


def _print_started(
    url: str, operations: ProgramEntryOperations
) -> None:
    for line in (
        "",
        "브라우저에서 설정을 마치고 '생성 시작'을 눌러주세요.",
        f"창이 자동으로 열리지 않으면 이 주소를 직접 열어주세요: {url}",
        "생성이 끝난 뒤에도 설정을 바꿔서 '생성 시작'을 다시 누르면 "
        "이어서 새로 만듭니다.",
        "",
    ):
        operations.write_line(line)


def _pending_batch_config(server: Any) -> dict:
    with server.config_lock:
        config = copy.deepcopy(
            server.pending_batch_config
            if isinstance(server.pending_batch_config, dict)
            else server.cfg
        )
        server.pending_batch_config = None
    return config


def _claim_batch(
    server: Any,
    config: dict,
    operations: ProgramEntryOperations,
) -> Any:
    return server.live.try_claim(
        "세팅 배치 생성",
        "settings",
        blueprint=operations.inherited_blueprint(
            config,
            source={"kind": "settings-batch"},
        ),
        payload_identity={
            "kind": "setting",
            "seed_round": config.get("seed"),
        },
    )


def _update_batch_result(server: Any) -> None:
    if server.live.stop_req:
        server.live.update(
            status_text="중지됨 — '생성 시작'을 누르면 이어서 합니다.",
            phase="stopped",
            can_retry=True,
        )
    elif server.live.failed:
        server.live.update(
            status_text=(
                f"일부 완료 — 성공 {server.live.completed} · "
                f"실패 {server.live.failed} "
                "(다시 실행하면 실패분 재시도)"
            ),
            phase="partial",
            can_retry=True,
        )
    else:
        operations.log_info(
            "═══ 이번 실행 완료 — 설정을 바꾸고 '생성 시작'을 "
            "다시 누르면 계속할 수 있습니다 ═══"
        )
        server.live.update(
            status_text=(
                "완료! 다시 '생성 시작'을 누르면 계속할 수 있습니다."
            ),
            phase="completed",
        )


def _run_batch(
    server: Any,
    config: dict,
    token: Any,
    operations: ProgramEntryOperations,
) -> bool:
    """Run one claimed batch; return False only for terminal failures."""
    keep_running = True
    try:
        operations.run_generation(server, config)
        _update_batch_result(server)
    except operations.fatal_stop_errors as error:
        server.live.update(
            status_text=f"즉시 중단: {error}",
            failed=max(1, server.live.failed),
            last_error=str(error),
            phase="failed",
            can_retry=True,
        )
        keep_running = False
    except Exception as error:
        operations.log_critical(
            "예기치 못한 오류로 중단되었습니다: %s", error
        )
        operations.log_critical(operations.format_traceback())
        server.live.update(
            status_text=f"오류로 중단됨: {error}",
            failed=max(1, server.live.failed),
            last_error=str(error),
            phase="failed",
            can_retry=True,
        )
        keep_running = False
    finally:
        server.live.release(token)
        server.start_event.clear()
    return keep_running


def run_event_loop(
    server: Any, operations: ProgramEntryOperations
) -> None:
    """Wait for UI start requests and serialize them through the live lease."""
    while True:
        server.start_event.wait()
        config = _pending_batch_config(server)
        token = _claim_batch(server, config, operations)
        if token is None:
            server.start_event.clear()
            server.live.update(
                status_text=(
                    "다른 생성이 도는 중입니다 — 끝난 뒤 "
                    "'생성 시작'을 다시 눌러주세요."
                )
            )
            continue
        if not _run_batch(server, config, token, operations):
            break


def _load_runtime(
    profile_context: Any,
    operations: ProgramEntryOperations,
) -> tuple[dict, Any, Any]:
    """Apply migration before reading all profile-dependent runtime data."""
    operations.migrate_program_data(profile_context)
    config = operations.load_config(profile_context)
    operations.recover_jobs(profile_context)
    options = operations.load_options(profile_context)
    spec = operations.load_spec(profile_context)
    return config, options, spec


def run_program(
    argv: Sequence[str],
    operations: ProgramEntryOperations,
) -> int:
    """Execute the stable CLI→profile→server→cleanup lifecycle."""
    arguments = parse_program_arguments(argv)
    profile_context = operations.prepare_profile(arguments.profile)
    logger = operations.initialize_logging(profile_context)
    instance = None
    server = None
    try:
        instance = operations.acquire_single_instance(profile_context)
        if instance is False:
            return 0
        config, options, spec = _load_runtime(
            profile_context, operations
        )
        server = operations.create_server(
            config, options, spec, profile_context
        )
        url = operations.start_server(
            server, arguments.open_browser
        )
        if not url:
            operations.read_input("엔터를 누르면 종료...")
            return 0
        operations.start_daemon(
            lambda: _warm_server(server, operations)
        )
        _print_started(url, operations)
        run_event_loop(server, operations)
        operations.write_line("프로그램을 종료합니다.")
        return 0
    finally:
        if server is not None:
            operations.cleanup_server(server)
        if instance is not None and instance is not False:
            operations.release_single_instance(instance)
        operations.close_logging(logger)


__all__ = [
    "ProgramArguments",
    "ProgramEntryOperations",
    "parse_program_arguments",
    "run_event_loop",
    "run_program",
]
