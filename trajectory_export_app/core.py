from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ExportConfig
from .events import CancellationToken, ExportCancelled, ProgressCallback, ProgressEvent
from .vendor.sw_connect import get_com_member


DEFAULT_OUTPUT = Path.home() / "Documents" / "SolidWorksTrajectory" / "current_solidworks_trajectory.csv"
DEFAULT_METADATA = DEFAULT_OUTPUT.with_name(f"{DEFAULT_OUTPUT.stem}_metadata.json")
# 轨迹相对模型表面的默认偏置，单位为 mm。
# 设为 None 时输出草图原始平面；设为 0.05 时保留 0.05 mm 的显示间隙。
DEFAULT_SURFACE_OFFSET_MM = 0.05


@dataclass
class ExportResult:
    csv_path: Path
    metadata_path: Path
    model_title: str
    model_path: str
    sketch_name: str
    point_count: int
    trajectory_length_mm: float
    path_closed: bool
    warnings: list[str]
    bbox_mm: dict[str, list[float]]
    preview_points_mm: list[tuple[float, float, float]]


def _emit(
    progress: ProgressCallback | None,
    stage: str,
    current: int | None,
    total: int | None,
    percent: float | None,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if progress is not None:
        progress(
            ProgressEvent(
                stage=stage,
                current=current,
                total=total,
                percent=percent,
                message=message,
                payload=payload or {},
            )
        )


def _check_cancel(cancel: CancellationToken | None) -> None:
    if cancel is not None:
        cancel.throw_if_cancelled()


@dataclass
class SegmentRecord:
    index: int
    kind: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    length_m: float
    segment: Any
    curve: Any
    circle_params: tuple[float, ...] | None = None


def vec_sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def vec_add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def vec_scale(a, scale):
    return tuple(x * scale for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a):
    return math.sqrt(dot(a, a))


def normalize(a):
    length = norm(a)
    if length < 1e-14:
        raise ValueError("zero-length vector")
    return vec_scale(a, 1.0 / length)


def safe_member(obj, name, *args, default=None):
    try:
        return get_com_member(obj, name, *args)
    except Exception:
        return default


def find_sketch_features(model):
    features = []
    feature = safe_member(model, "FirstFeature")
    while feature:
        type_name = str(safe_member(feature, "GetTypeName2", default="") or "")
        if type_name == "ProfileFeature":
            sketch = safe_member(feature, "GetSpecificFeature2")
            if sketch is not None:
                segments = safe_member(sketch, "GetSketchSegments", default=()) or ()
                features.append(
                    {
                        "feature": feature,
                        "sketch": sketch,
                        "name": str(safe_member(feature, "Name", default="") or ""),
                        "is_3d": bool(safe_member(sketch, "Is3D", default=False)),
                        "segment_count": len(segments),
                    }
                )
        feature = safe_member(feature, "GetNextFeature")
    return features


def choose_sketch(model, requested_name: str | None):
    sketches = find_sketch_features(model)
    if requested_name:
        for item in sketches:
            if item["name"].casefold() == requested_name.casefold():
                return item, sketches
        available = ", ".join(item["name"] for item in sketches)
        raise RuntimeError(f"找不到草图 {requested_name}。可用草图: {available}")

    candidates = [item for item in sketches if item["segment_count"] > 0]
    if not candidates:
        raise RuntimeError("当前零件没有包含几何段的草图")
    return candidates[-1], sketches


def transform_from_array(array_data):
    if not array_data or len(array_data) < 13:
        raise RuntimeError("无法读取 SolidWorks 草图坐标变换")
    rotation = (
        tuple(float(x) for x in array_data[0:3]),
        tuple(float(x) for x in array_data[3:6]),
        tuple(float(x) for x in array_data[6:9]),
    )
    translation = tuple(float(x) for x in array_data[9:12])
    scale = float(array_data[12] or 1.0)
    if abs(scale) < 1e-14:
        raise RuntimeError("SolidWorks 草图坐标变换的缩放因子为零")
    return rotation, translation, scale


def sketch_to_model(point, transform):
    rotation, translation, scale = transform
    q = tuple((float(point[i]) - translation[i]) / scale for i in range(3))
    # SolidWorks MathTransform stores a row-major 3 x 3 rotation followed by translation.
    return tuple(sum(rotation[j][i] * q[j] for j in range(3)) for i in range(3))


def model_vector_from_sketch(vector, transform):
    rotation, _, _ = transform
    return tuple(sum(rotation[j][i] * vector[j] for j in range(3)) for i in range(3))


def model_bbox(model):
    values = safe_member(model, "GetPartBox", True)
    if values is None or len(values) < 6:
        raise RuntimeError("无法读取 SolidWorks 模型包围盒，不能自动推断表面偏置")
    return tuple(float(value) for value in values[:6])


def bbox_corners(bbox):
    x_min, y_min, z_min, x_max, y_max, z_max = bbox
    return [
        (x, y, z)
        for x in (x_min, x_max)
        for y in (y_min, y_max)
        for z in (z_min, z_max)
    ]


def apply_surface_offset(model, points_m, transform, requested_offset_mm, warnings):
    """Move a planar sketch to a requested offset from the nearest model envelope face."""
    if requested_offset_mm is None:
        return points_m, {
            "requested_surface_offset_mm": None,
            "applied": False,
            "method": "raw_sketch_plane",
        }

    requested_offset_m = float(requested_offset_mm) / 1000.0
    if requested_offset_m < 0.0:
        raise ValueError("surface offset must be non-negative")

    sketch_origin = sketch_to_model((0.0, 0.0, 0.0), transform)
    sketch_normal = normalize(model_vector_from_sketch((0.0, 0.0, 1.0), transform))
    bbox = model_bbox(model)
    projections = [dot(vec_sub(corner, sketch_origin), sketch_normal) for corner in bbox_corners(bbox)]
    anchor_projection = min(projections, key=abs)
    surface_anchor = vec_add(sketch_origin, vec_scale(sketch_normal, anchor_projection))
    outward_vector = vec_sub(sketch_origin, surface_anchor)
    if norm(outward_vector) < 1e-12:
        warnings.append("sketch plane appears coincident with the inferred model surface; no normal direction was applied")
        return points_m, {
            "requested_surface_offset_mm": float(requested_offset_mm),
            "applied": False,
            "method": "bbox_surface_inference_failed",
        }

    outward = normalize(outward_vector)
    current_offset_m = dot(vec_sub(sketch_origin, surface_anchor), outward)
    delta_m = requested_offset_m - current_offset_m
    shifted = [vec_add(point, vec_scale(outward, delta_m)) for point in points_m]
    if abs(current_offset_m - requested_offset_m) > 1e-9:
        warnings.append(
            f"surface offset adjusted from {current_offset_m * 1000.0:.6f} mm "
            f"to {requested_offset_mm:.6f} mm using the nearest model envelope face"
        )
    return shifted, {
        "requested_surface_offset_mm": float(requested_offset_mm),
        "original_sketch_plane_offset_mm": round(current_offset_m * 1000.0, 9),
        "applied": True,
        "method": "nearest_model_envelope_face_plus_outward_normal",
        "surface_anchor_model_m": [round(value, 12) for value in surface_anchor],
        "outward_normal_model": [round(value, 12) for value in outward],
        "model_bbox_m": [round(value, 12) for value in bbox],
    }


def sketch_point_tuple(point):
    return tuple(float(safe_member(point, axis)) for axis in ("X", "Y", "Z"))


def segment_kind(segment_type: int) -> str:
    return {
        0: "line",
        1: "arc",
        2: "circle",
        3: "ellipse",
        4: "parabola",
        5: "spline",
        6: "helix",
    }.get(int(segment_type), f"type_{segment_type}")


def collect_segments(
    sketch,
    transform,
    warnings,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
):
    records = []
    all_segments = safe_member(sketch, "GetSketchSegments", default=()) or ()
    total = len(all_segments)
    for index, segment in enumerate(all_segments):
        _check_cancel(cancel)
        if bool(safe_member(segment, "ConstructionGeometry", default=False)):
            warnings.append(f"ignored construction geometry segment {index}")
            _emit(progress, "collect", index + 1, total, 15.0 + 20.0 * (index + 1) / max(total, 1), f"跳过构造几何段 {index + 1}/{total}")
            continue
        start_point = safe_member(segment, "GetStartPoint2")
        end_point = safe_member(segment, "GetEndPoint2")
        if start_point is None or end_point is None:
            warnings.append(f"segment {index} has no usable endpoints")
            continue
        start = sketch_to_model(sketch_point_tuple(start_point), transform)
        end = sketch_to_model(sketch_point_tuple(end_point), transform)
        length_m = float(safe_member(segment, "GetLength", default=0.0) or 0.0)
        curve = safe_member(segment, "GetCurve")
        kind = segment_kind(int(safe_member(segment, "GetType", default=-1)))
        circle_params = None
        if kind in {"arc", "circle"} and curve is not None:
            raw = safe_member(curve, "CircleParams")
            if raw is not None:
                circle_params = tuple(float(value) for value in raw)
        records.append(
            SegmentRecord(
                index=index,
                kind=kind,
                start=start,
                end=end,
                length_m=length_m,
                segment=segment,
                curve=curve,
                circle_params=circle_params,
            )
        )
        _emit(progress, "collect", index + 1, total, 15.0 + 20.0 * (index + 1) / max(total, 1), f"读取草图几何段 {index + 1}/{total}")
    return records


def point_key(point, tolerance_m=1e-8):
    return tuple(round(float(value) / tolerance_m) for value in point)


def order_segments(records, warnings):
    if not records:
        raise RuntimeError("草图没有可导出的几何段")

    node_to_edges = defaultdict(list)
    for position, record in enumerate(records):
        node_to_edges[point_key(record.start)].append(position)
        node_to_edges[point_key(record.end)].append(position)

    components = []
    adjacency = defaultdict(set)
    for edges in node_to_edges.values():
        for first in edges:
            for second in edges:
                if first != second:
                    adjacency[first].add(second)
    unseen = set(range(len(records)))
    while unseen:
        first = min(unseen)
        stack = [first]
        unseen.remove(first)
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in adjacency[current]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    stack.append(neighbor)
        components.append(sorted(component))

    if len(components) != 1:
        warnings.append(f"detected {len(components)} disconnected trajectory components")

    component = components[0]
    component_nodes = defaultdict(list)
    for position in component:
        record = records[position]
        component_nodes[point_key(record.start)].append(position)
        component_nodes[point_key(record.end)].append(position)
    endpoints = [node for node, edges in component_nodes.items() if len(edges) == 1]
    closed = not endpoints
    start_position = component[0]
    start_node = point_key(records[start_position].start)
    if endpoints:
        start_node = endpoints[0]
        start_position = component_nodes[start_node][0]

    ordered = []
    used = set()
    current_position = start_position
    current_node = start_node
    while len(used) < len(component):
        record = records[current_position]
        start_key = point_key(record.start)
        end_key = point_key(record.end)
        if start_key == current_node:
            reversed_record = False
            next_node = end_key
        elif end_key == current_node:
            reversed_record = True
            next_node = start_key
        else:
            warnings.append(f"segment {record.index} could not be connected at the current node")
            reversed_record = False
            next_node = end_key
        ordered.append((record, reversed_record))
        used.add(current_position)
        if len(used) == len(component):
            break
        next_candidates = [candidate for candidate in component_nodes[next_node] if candidate not in used]
        if not next_candidates:
            warnings.append("trajectory ordering stopped before all segments were consumed")
            break
        current_node = next_node
        current_position = next_candidates[0]

    return ordered, closed, len(components)


def arc_samples(record: SegmentRecord, transform, sample_step_m: float):
    if not record.circle_params or record.curve is None:
        return [record.start, record.end]
    params = record.circle_params
    center_local = params[0:3]
    axis_local = params[3:6]
    radius = abs(params[6])
    if radius < 1e-14:
        return [record.start, record.end]
    center = sketch_to_model(center_local, transform)
    axis = normalize(model_vector_from_sketch(axis_local, transform))
    start_radius = normalize(vec_sub(record.start, center))
    end_radius = normalize(vec_sub(record.end, center))
    sin_value = dot(axis, cross(start_radius, end_radius))
    cos_value = max(-1.0, min(1.0, dot(start_radius, end_radius)))
    raw_angle = math.atan2(sin_value, cos_value)
    direction = 1.0 if raw_angle >= 0.0 else -1.0
    target_sweep = abs(record.length_m / radius)
    if target_sweep < 1e-12:
        return [record.start, record.end]
    if abs(raw_angle) < 1e-10:
        direction = 1.0

    tangent = normalize(cross(axis, start_radius))

    def candidate(sweep):
        end_candidate = vec_add(
            center,
            vec_scale(
                vec_add(
                    vec_scale(start_radius, math.cos(sweep)),
                    vec_scale(tangent, math.sin(sweep)),
                ),
                radius,
            ),
        )
        return end_candidate

    sweep = direction * target_sweep
    if math.dist(candidate(sweep), record.end) > math.dist(candidate(-sweep), record.end):
        sweep = -sweep

    count = max(2, int(math.ceil(abs(sweep) * radius / max(sample_step_m, 1e-7))))
    points = []
    for index in range(count + 1):
        fraction = index / count
        angle = sweep * fraction
        points.append(
            vec_add(
                center,
                vec_scale(
                    vec_add(
                        vec_scale(start_radius, math.cos(angle)),
                        vec_scale(tangent, math.sin(angle)),
                    ),
                    radius,
                ),
            )
        )
    points[0] = record.start
    points[-1] = record.end
    return points


def segment_samples(record: SegmentRecord, reversed_record: bool, transform, sample_step_m: float, warnings):
    if record.kind == "arc":
        points = arc_samples(record, transform, sample_step_m)
    else:
        points = [record.start, record.end]
        if record.kind not in {"line"}:
            warnings.append(f"segment {record.index} type {record.kind} exported by endpoints")
    if reversed_record:
        points.reverse()
    return points


def deduplicate_join(points, tolerance_m=1e-9):
    result = []
    for point in points:
        if not result or math.dist(result[-1], point) > tolerance_m:
            result.append(point)
    return result


def build_path(
    ordered,
    transform,
    sample_step_m,
    warnings,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
):
    points = []
    segment_ids = []
    total = len(ordered)
    for index, (record, reversed_record) in enumerate(ordered):
        _check_cancel(cancel)
        samples = segment_samples(record, reversed_record, transform, sample_step_m, warnings)
        if points and math.dist(points[-1], samples[0]) > 1e-7:
            warnings.append(
                f"gap between ordered segments near segment {record.index}: "
                f"{math.dist(points[-1], samples[0]) * 1000.0:.6f} mm"
            )
        for sample_index, point in enumerate(samples):
            if points and sample_index == 0 and math.dist(points[-1], point) <= 1e-9:
                continue
            points.append(point)
            segment_ids.append(record.index)
        _emit(progress, "sample", index + 1, total, 40.0 + 35.0 * (index + 1) / max(total, 1), f"生成轨迹 {index + 1}/{total}")
    return deduplicate_join(points), segment_ids


def write_csv(
    path: Path,
    points_m,
    segment_ids,
    metadata,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    cumulative = 0.0
    total = len(points_m)
    update_step = max(1, total // 100)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "point_id",
                "segment_id",
                "arc_length_mm",
                # MATLAB 客户端通过 data(:, end-2:end) 读取 XYZ，
                # 因此坐标必须始终位于最后三列，并且全部为数值列。
                "x_mm",
                "y_mm",
                "z_mm",
            ]
        )
        for point_id, point in enumerate(points_m):
            _check_cancel(cancel)
            if point_id:
                cumulative += math.dist(points_m[point_id - 1], point) * 1000.0
            writer.writerow(
                [
                    point_id,
                    segment_ids[point_id] if point_id < len(segment_ids) else "",
                    f"{cumulative:.6f}",
                    f"{point[0] * 1000.0:.6f}",
                    f"{point[1] * 1000.0:.6f}",
                    f"{point[2] * 1000.0:.6f}",
                ]
            )
            if point_id == total - 1 or point_id % update_step == 0:
                _emit(progress, "write_csv", point_id + 1, total, 80.0 + 18.0 * (point_id + 1) / max(total, 1), f"写入 CSV {point_id + 1}/{total}")
    return cumulative


def export_model(
    model,
    config: ExportConfig,
    progress: ProgressCallback | None = None,
    cancel: CancellationToken | None = None,
) -> ExportResult:
    """Export the active SolidWorks model without owning the COM connection."""
    config = config.normalized()
    _check_cancel(cancel)
    _emit(progress, "prepare", 0, 1, 0.0, "准备导出配置")

    if not config.overwrite and (config.output_csv.exists() or config.metadata_path.exists()):
        raise FileExistsError("输出文件已存在，且当前未允许覆盖")

    _emit(progress, "discover", 0, 1, 5.0, "正在读取当前模型和草图")
    sketches = find_sketch_features(model)
    if not sketches:
        raise RuntimeError("当前零件没有可用草图")
    selected, _ = choose_sketch(model, config.sketch_name)
    _emit(
        progress,
        "discover",
        1,
        1,
        15.0,
        f"已选择草图: {selected['name']}",
        {"sketches": [{k: item[k] for k in ("name", "is_3d", "segment_count")} for item in sketches]},
    )

    sketch = selected["sketch"]
    model_path = str(safe_member(model, "GetPathName", default="") or "")
    model_title = str(safe_member(model, "GetTitle", default="") or "")
    transform_value = safe_member(safe_member(sketch, "ModelToSketchTransform"), "ArrayData")
    if transform_value is None:
        raise RuntimeError("无法读取 SolidWorks 草图坐标变换")
    transform_array = tuple(float(x) for x in transform_value)
    transform = transform_from_array(transform_array)
    warnings: list[str] = []

    records = collect_segments(sketch, transform, warnings, progress, cancel)
    ordered, closed, component_count = order_segments(records, warnings)
    _check_cancel(cancel)
    _emit(progress, "order", 1, 1, 40.0, f"已完成轨迹排序，共 {len(ordered)} 段")
    points_m, segment_ids = build_path(
        ordered,
        transform,
        config.sample_step_mm / 1000.0,
        warnings,
        progress,
        cancel,
    )
    if len(points_m) < 2:
        raise RuntimeError("导出的轨迹点少于 2 个，无法形成路径")

    _check_cancel(cancel)
    points_m, surface_offset_info = apply_surface_offset(
        model,
        points_m,
        transform,
        config.surface_offset_mm,
        warnings,
    )
    _emit(progress, "offset", 1, 1, 80.0, "已应用表面偏置")

    base_metadata = {
        "model_title": model_title,
        "model_path": model_path,
        "sketch_name": selected["name"],
        "sketch_is_3d": selected["is_3d"],
        "source_segment_count": len(records),
        "ordered_segment_count": len(ordered),
        "component_count": component_count,
        "path_closed": closed,
        "sample_step_mm": config.sample_step_mm,
        "surface_offset": surface_offset_info,
        "coordinate_system": "Global SolidWorks model coordinates",
        "units": "mm",
        "transform_array": list(transform_array),
        "warnings": warnings,
    }
    length_mm = write_csv(config.output_csv, points_m, segment_ids, base_metadata, progress, cancel)
    xs = [point[0] * 1000.0 for point in points_m]
    ys = [point[1] * 1000.0 for point in points_m]
    zs = [point[2] * 1000.0 for point in points_m]
    bbox_mm = {
        "x": [round(min(xs), 6), round(max(xs), 6)],
        "y": [round(min(ys), 6), round(max(ys), 6)],
        "z": [round(min(zs), 6), round(max(zs), 6)],
    }
    base_metadata.update(
        {
            "point_count": len(points_m),
            "trajectory_length_mm": round(length_mm, 6),
            "bbox_mm": bbox_mm,
            "csv_path": str(config.output_csv),
            "metadata_path": str(config.metadata_path),
        }
    )
    _check_cancel(cancel)
    config.metadata_path.parent.mkdir(parents=True, exist_ok=True)
    config.metadata_path.write_text(json.dumps(base_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _emit(progress, "complete", 1, 1, 100.0, "导出完成")

    preview_limit = 500
    if len(points_m) <= preview_limit:
        preview = points_m
    else:
        stride = (len(points_m) - 1) / (preview_limit - 1)
        preview = [points_m[round(index * stride)] for index in range(preview_limit)]
    return ExportResult(
        csv_path=config.output_csv,
        metadata_path=config.metadata_path,
        model_title=model_title,
        model_path=model_path,
        sketch_name=selected["name"],
        point_count=len(points_m),
        trajectory_length_mm=round(length_mm, 6),
        path_closed=closed,
        warnings=warnings,
        bbox_mm=bbox_mm,
        preview_points_mm=[tuple(value * 1000.0 for value in point) for point in preview],
    )


def main():
    parser = argparse.ArgumentParser(description="Export a SolidWorks sketch trajectory to CSV")
    parser.add_argument("--sketch", help="sketch feature name, for example 草图3 or Sketch3")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="CSV output path")
    parser.add_argument("--metadata", help="metadata JSON output path")
    parser.add_argument("--sample-step-mm", type=float, default=1.0, help="arc sampling step in mm")
    parser.add_argument("--surface-offset-mm", type=float, default=DEFAULT_SURFACE_OFFSET_MM)
    parser.add_argument("--list-sketches", action="store_true", help="list sketches and exit")
    args = parser.parse_args()

    from .solidworks_adapter import SolidWorksAdapter

    adapter = SolidWorksAdapter(version=2023, wait_seconds=5, visible=True)
    _, model = adapter.connect()
    if model is None:
        raise RuntimeError("当前没有活动 SolidWorks 文档")
    if args.list_sketches:
        print(json.dumps(adapter.list_sketches(model), ensure_ascii=False, indent=2))
        return 0
    result = export_model(
        model,
        ExportConfig(
            sketch_name=args.sketch,
            output_csv=Path(args.output),
            metadata_path=Path(args.metadata) if args.metadata else None,
            sample_step_mm=args.sample_step_mm,
            surface_offset_mm=args.surface_offset_mm,
        ),
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
