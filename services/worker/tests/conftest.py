from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon


@pytest.fixture(autouse=True)
def deterministic_slicing(request, monkeypatch):
    """Force the estimator unless a test explicitly asks for the real slicer.

    Otherwise the suite behaves differently depending on whether PrusaSlicer happens to be
    installed — slower, and testing something other than what CI tests. Tests that want the
    real thing carry the `real_slicer` marker and skip when it is absent.
    """
    if request.node.get_closest_marker("real_slicer"):
        return
    monkeypatch.setattr("worker.slicing.find_slicer", lambda: None)


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


def l_bracket() -> trimesh.Trimesh:
    """A watertight L-bracket: an 80 x 60 x 6 mm base with a 6 mm web rising 50 mm above it.

    As modelled the web stands upright, so a sideways load on its tip bends the layer bonds at
    the root. Laid on its front face, every layer is the whole L and the load stays in-plane.
    """
    profile = Polygon([(0, 0), (80, 0), (80, 6), (6, 6), (6, 56), (0, 56)])
    bracket = trimesh.creation.extrude_polygon(profile, 60)
    # Profile into the XZ plane, so the 60 mm width runs along Y.
    bracket.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    return bracket


def hole_plate() -> trimesh.Trimesh:
    """An 80 x 50 x 14 mm plate: vertical holes of 3, 4 and 8 mm, horizontal ones of 3 and 6 mm."""
    plate = trimesh.creation.box(extents=(80, 50, 14))
    plate.apply_translation((40, 25, 7))
    cuts = []
    for x, d in ((12, 3), (28, 4), (46, 8)):
        cut = trimesh.creation.cylinder(radius=d / 2, height=30, sections=64)
        cut.apply_translation((x, 25, 7))
        cuts.append(cut)
    for x, d in ((62, 3), (72, 6)):
        cut = trimesh.creation.cylinder(radius=d / 2, height=70, sections=64)
        cut.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
        cut.apply_translation((x, 25, 7))
        cuts.append(cut)
    return trimesh.boolean.difference([plate, *cuts], engine="manifold")


@pytest.fixture(scope="session")
def l_bracket_mesh() -> trimesh.Trimesh:
    return l_bracket()


@pytest.fixture(scope="session")
def l_bracket_stl() -> Path:
    return _export(l_bracket())


@pytest.fixture(scope="session")
def hole_plate_mesh() -> trimesh.Trimesh:
    return hole_plate()


@pytest.fixture(scope="session")
def hole_plate_stl() -> Path:
    return _export(hole_plate())
