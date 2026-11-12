"""GeoTIFF elevation raster loader using Rasterio and PyProj."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from core.models import ElevationSourceRecord, GridCell

logger = logging.getLogger(__name__)

try:
    import rasterio
    from rasterio.windows import from_bounds
    from pyproj import Transformer

    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False


class ElevationImportError(RuntimeError):
    """Raised when elevation raster loading or transformation fails."""


@dataclass(slots=True)
class RasterSummary:
    """Metadata and extracted cell elevation updates from a GeoTIFF file."""

    file_name: str
    crs_text: str
    width_px: int
    height_px: int
    nodata_value: float | None
    cells_sampled: int
    cells_missing: int
    cell_updates: list[tuple[int, float | None, float | None, float | None, float | None, str | None]]
    source_record: ElevationSourceRecord


class ElevationService:
    """Imports elevation GeoTIFF rasters into simulation grid cells without inventing values."""

    @staticmethod
    def is_supported() -> bool:
        return RASTERIO_AVAILABLE

    def load_geotiff_for_grid(
        self,
        file_path: Path | str,
        neighbourhood_id: int,
        cells: list[GridCell],
        source_name: str = "",
    ) -> RasterSummary:
        """Read a GeoTIFF DEM and extract center, min, max, and mean elevation per cell."""
        if not RASTERIO_AVAILABLE:
            raise ElevationImportError(
                "GeoTIFF import requires 'rasterio' and 'pyproj'. "
                "Install them with: pip install rasterio pyproj"
            )

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise ElevationImportError(f"Raster file not found: {path}")

        if not cells:
            raise ElevationImportError("No grid cells available to sample elevation.")

        try:
            with rasterio.open(path) as dataset:
                if dataset.count < 1:
                    raise ElevationImportError("Raster contains no elevation bands.")

                crs = dataset.crs
                crs_text = crs.to_string() if crs is not None else "Unknown (Assumed EPSG:4326)"
                transformer: Transformer | None = None
                if crs is not None and not crs.is_geographic:
                    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
                elif crs is not None and crs.to_epsg() not in (None, 4326):
                    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

                nodata = dataset.nodata
                band = dataset.read(1, masked=False)
                height_px, width_px = band.shape

                prov_label = f"Imported Raster: {path.name}"
                updates: list[
                    tuple[int, float | None, float | None, float | None, float | None, str | None]
                ] = []
                sampled_count = 0
                missing_count = 0

                for cell in cells:
                    if cell.id is None:
                        continue

                    # Transform cell bounds and center to raster CRS
                    if transformer is not None:
                        cx, cy = transformer.transform(cell.center_longitude, cell.center_latitude)
                        xs, ys = transformer.transform(
                            [cell.min_longitude, cell.max_longitude, cell.min_longitude, cell.max_longitude],
                            [cell.min_latitude, cell.min_latitude, cell.max_latitude, cell.max_latitude],
                        )
                        r_minx, r_maxx = min(xs), max(xs)
                        r_miny, r_maxy = min(ys), max(ys)
                    else:
                        cx, cy = cell.center_longitude, cell.center_latitude
                        r_minx, r_maxx = cell.min_longitude, cell.max_longitude
                        r_miny, r_maxy = cell.min_latitude, cell.max_latitude

                    # Center sample
                    center_elev: float | None = None
                    try:
                        row_idx, col_idx = dataset.index(cx, cy)
                        if 0 <= row_idx < height_px and 0 <= col_idx < width_px:
                            raw_val = float(band[row_idx, col_idx])
                            if self._is_valid_elev(raw_val, nodata):
                                center_elev = round(raw_val, 3)
                    except Exception:
                        center_elev = None

                    # Cell window min/max/mean
                    min_el = max_el = mean_el = None
                    try:
                        win = from_bounds(r_minx, r_miny, r_maxx, r_maxy, dataset.transform)
                        r0 = max(0, int(math.floor(win.row_off)))
                        r1 = min(height_px, int(math.ceil(win.row_off + win.height)))
                        c0 = max(0, int(math.floor(win.col_off)))
                        c1 = min(width_px, int(math.ceil(win.col_off + win.width)))
                        if r1 > r0 and c1 > c0:
                            patch = band[r0:r1, c0:c1].astype(np.float64, copy=False)
                            mask = np.isfinite(patch) & (patch >= -500.0) & (patch <= 9000.0)
                            if nodata is not None and math.isfinite(float(nodata)):
                                mask &= patch != float(nodata)
                            valid_vals = patch[mask]
                            if valid_vals.size > 0:
                                min_el = round(float(np.min(valid_vals)), 3)
                                max_el = round(float(np.max(valid_vals)), 3)
                                mean_el = round(float(np.mean(valid_vals)), 3)
                    except Exception:
                        pass

                    # If center missed due to boundary rounding but window mean exists, use mean
                    primary_elev = center_elev if center_elev is not None else mean_el
                    if primary_elev is not None:
                        sampled_count += 1
                        updates.append((cell.id, primary_elev, min_el, max_el, mean_el, prov_label))
                    else:
                        missing_count += 1
                        updates.append((cell.id, None, None, None, None, None))

                stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                rec = ElevationSourceRecord(
                    id=None,
                    neighbourhood_id=neighbourhood_id,
                    source_name=source_name.strip() or path.stem,
                    file_name=path.name,
                    coordinate_reference_system=crs_text,
                    imported_at=stamp,
                    source_description=(
                        f"{width_px}x{height_px}px raster; {sampled_count} cell(s) sampled, "
                        f"{missing_count} outside/nodata."
                    ),
                )
                return RasterSummary(
                    file_name=path.name,
                    crs_text=crs_text,
                    width_px=width_px,
                    height_px=height_px,
                    nodata_value=float(nodata) if nodata is not None and math.isfinite(float(nodata)) else None,
                    cells_sampled=sampled_count,
                    cells_missing=missing_count,
                    cell_updates=updates,
                    source_record=rec,
                )
        except ElevationImportError:
            raise
        except Exception as exc:
            logger.exception("Failed loading elevation GeoTIFF %s", path)
            raise ElevationImportError(f"Could not read GeoTIFF '{path.name}': {exc}") from exc

    @staticmethod
    def _is_valid_elev(val: float, nodata: Any) -> bool:
        if not math.isfinite(val):
            return False
        if nodata is not None:
            try:
                if math.isfinite(float(nodata)) and val == float(nodata):
                    return False
            except (TypeError, ValueError):
                pass
        return -500.0 <= val <= 9000.0
