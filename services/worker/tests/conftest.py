from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import trimesh


def _export(mesh: trimesh.Trimesh, suffix: str = ".stl") -> Path:
    path = Path(tempfile.mkdtemp()) / f"part{suffix}"
    mesh.export(path)
    return path


@pytest.fixture(scope="session")
def box_stl() -> Path:
    """A 40 x 30 x 20 mm block: watertight, no overhangs, sits flat."""
    return _export(trimesh.creation.box(extents=(40, 30, 20)))


@pytest.fixture(scope="session")
def thin_tube_stl() -> Path:
    """A 0.3 mm walled tube: below what a 0.4 mm nozzle can print."""
    return _export(trimesh.creation.annulus(r_min=9.7, r_max=10.0, height=40, sections=96))


@pytest.fixture(scope="session")
def oversized_stl() -> Path:
    """Larger than the configured 256 mm build volume in every axis."""
    return _export(trimesh.creation.box(extents=(400, 300, 300)))


@pytest.fixture(scope="session")
def inch_scale_stl() -> Path:
    """A part modelled in inches and exported as millimetres: 25.4x too small."""
    return _export(trimesh.creation.box(extents=(2.0, 1.5, 0.8)))


@pytest.fixture(scope="session")
def tall_spike_stl() -> Path:
    """Tall, narrow and top-heavy: the shape most likely to come off the plate."""
    return _export(trimesh.creation.cone(radius=6, height=90, sections=48))


@pytest.fixture(scope="session")
def open_mesh_stl() -> Path:
    """Two overlapping boxes concatenated: a valid part, but not a watertight mesh.

    This is what an L-bracket exported from a sketchy CAD workflow looks like, and it is the
    case that used to produce a zero-volume quote.
    """
    plate = trimesh.creation.box(extents=(80, 60, 6))
    plate.apply_translation((0, 0, 3))
    web = trimesh.creation.box(extents=(6, 60, 50))
    web.apply_translation((-37, 0, 31))
    return _export(trimesh.util.concatenate([plate, web]))
