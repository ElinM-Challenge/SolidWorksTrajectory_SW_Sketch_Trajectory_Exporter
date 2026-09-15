from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path

from .config import ExportConfig
from .core import export_model
from .events import CancellationToken, ExportCancelled, ProgressEvent
from .solidworks_adapter import SolidWorksAdapter


class FileCancellationToken(CancellationToken):
    def __init__(self, cancel_file: Path | None):
        super().__init__()
        self.cancel_file = cancel_file

    def is_cancelled(self) -> bool:
        return super().is_cancelled() or bool(self.cancel_file and self.cancel_file.exists())


def emit(event: str, **payload) -> None:
    record = {"event": event, **payload}
    print(json.dumps(record, ensure_ascii=False, default=str), flush=True)


def emit_progress(event: ProgressEvent) -> None:
    emit(
        "progress",
        stage=event.stage,
        current=event.current,
        total=event.total,
        percent=event.percent,
        message=event.message,
        payload=event.payload,
    )


def run(operation: str, config_path: Path, cancel_file: Path | None) -> int:
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config = ExportConfig(
        sketch_name=config_data.get("sketch_name"),
        output_csv=Path(config_data["output_csv"]),
        metadata_path=Path(config_data["metadata_path"]) if config_data.get("metadata_path") else None,
        sample_step_mm=float(config_data.get("sample_step_mm", 1.0)),
        surface_offset_mm=(
            None
            if config_data.get("surface_offset_mm") is None
            else float(config_data.get("surface_offset_mm"))
        ),
        solidworks_version=config_data.get("solidworks_version", 2023),
        wait_seconds=float(config_data.get("wait_seconds", 5.0)),
        overwrite=bool(config_data.get("overwrite", True)),
    )
    token = FileCancellationToken(cancel_file)
    adapter = SolidWorksAdapter(
        version=config.solidworks_version,
        wait_seconds=config.wait_seconds,
        visible=True,
    )

    emit("status", message="正在连接 SolidWorks")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        _, model = adapter.connect()
    for line in captured.getvalue().splitlines():
        if line.strip():
            emit("log", message=line.strip())
    if model is None:
        raise RuntimeError("当前没有活动 SolidWorks 文档")

    if operation == "inspect":
        info = adapter.active_model_info(model)
        emit(
            "inspect",
            model_title=info.title,
            model_path=info.path,
            document_type=info.document_type,
            sketches=info.sketches,
        )
        emit("complete", message="模型信息读取完成")
        return 0

    if operation != "export":
        raise ValueError(f"未知操作: {operation}")

    result = export_model(model, config, progress=emit_progress, cancel=token)
    emit(
        "result",
        csv_path=str(result.csv_path),
        metadata_path=str(result.metadata_path),
        model_title=result.model_title,
        model_path=result.model_path,
        sketch_name=result.sketch_name,
        point_count=result.point_count,
        trajectory_length_mm=result.trajectory_length_mm,
        path_closed=result.path_closed,
        warnings=result.warnings,
        bbox_mm=result.bbox_mm,
        preview_points_mm=result.preview_points_mm,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SolidWorks trajectory exporter worker")
    parser.add_argument("--operation", choices=("inspect", "export"), default="export")
    parser.add_argument("--config", required=True)
    parser.add_argument("--cancel-file")
    args = parser.parse_args(argv)
    try:
        return run(
            args.operation,
            Path(args.config),
            Path(args.cancel_file) if args.cancel_file else None,
        )
    except ExportCancelled as exc:
        emit("cancelled", message=str(exc))
        return 2
    except Exception as exc:
        emit("error", message=str(exc), error_type=type(exc).__name__)
        emit("log", message=traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
