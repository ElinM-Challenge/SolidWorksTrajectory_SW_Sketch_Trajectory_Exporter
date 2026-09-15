from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "SolidWorksTrajectory"


@dataclass
class ExportConfig:
    """User-facing export settings kept independent from Qt and argparse."""

    sketch_name: str | None
    output_csv: Path
    metadata_path: Path | None = None
    sample_step_mm: float = 1.0
    surface_offset_mm: float | None = 0.05
    solidworks_version: int | None = 2023
    wait_seconds: float = 5.0
    overwrite: bool = True

    def normalized(self) -> "ExportConfig":
        output_csv = Path(self.output_csv).expanduser().resolve()
        metadata_path = (
            Path(self.metadata_path).expanduser().resolve()
            if self.metadata_path
            else output_csv.with_name(f"{output_csv.stem}_metadata.json")
        )
        if self.sample_step_mm <= 0:
            raise ValueError("sample_step_mm must be positive")
        if self.surface_offset_mm is not None and self.surface_offset_mm < 0:
            raise ValueError("surface_offset_mm must be non-negative or None")
        return ExportConfig(
            sketch_name=self.sketch_name.strip() if self.sketch_name else None,
            output_csv=output_csv,
            metadata_path=metadata_path,
            sample_step_mm=float(self.sample_step_mm),
            surface_offset_mm=(
                None if self.surface_offset_mm is None else float(self.surface_offset_mm)
            ),
            solidworks_version=self.solidworks_version,
            wait_seconds=float(self.wait_seconds),
            overwrite=bool(self.overwrite),
        )
