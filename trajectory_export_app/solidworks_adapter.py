from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import find_sketch_features, safe_member
from .vendor.sw_connect import connect_solidworks


@dataclass
class ActiveModelInfo:
    title: str
    path: str
    document_type: str
    sketches: list[dict[str, Any]]


class SolidWorksAdapter:
    """Owns the SolidWorks COM connection inside the worker process."""

    def __init__(self, version: int | None = 2023, wait_seconds: float = 5.0, visible: bool = True):
        self.version = version
        self.wait_seconds = wait_seconds
        self.visible = visible
        self.sw = None
        self.model = None

    def connect(self):
        self.sw, self.model = connect_solidworks(
            version=self.version,
            wait_seconds=self.wait_seconds,
            visible=self.visible,
            return_metadata=False,
        )
        return self.sw, self.model

    def list_sketches(self, model=None) -> list[dict[str, Any]]:
        model = model or self.model
        if model is None:
            return []
        return [
            {key: item[key] for key in ("name", "is_3d", "segment_count")}
            for item in find_sketch_features(model)
        ]

    def active_model_info(self, model=None) -> ActiveModelInfo:
        model = model or self.model
        if model is None:
            raise RuntimeError("当前没有活动 SolidWorks 文档")
        document_type_map = {1: "part", 2: "assembly", 3: "drawing"}
        document_type = int(safe_member(model, "GetType", default=0) or 0)
        return ActiveModelInfo(
            title=str(safe_member(model, "GetTitle", default="") or ""),
            path=str(safe_member(model, "GetPathName", default="") or ""),
            document_type=document_type_map.get(document_type, "unknown"),
            sketches=self.list_sketches(model),
        )
