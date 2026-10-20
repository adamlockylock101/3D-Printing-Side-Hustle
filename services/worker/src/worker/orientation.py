"""The six ways a part can sit on the plate, named for the face that goes down.

Faces are named as the customer modelled the part: +Z is the top, -Y the front, -X the left.
"bottom" is the part exactly as uploaded.
"""

from __future__ import annotations

import numpy as np
import trimesh

# Outward direction of each face, in the uploaded model's coordinates.
FACE_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "bottom": (0.0, 0.0, -1.0),
    "top": (0.0, 0.0, 1.0),
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
}

# Which model axis becomes the build (layer-stacking) axis when that face is down.
FACE_AXIS = {"bottom": 2, "top": 2, "front": 1, "back": 1, "left": 0, "right": 0}

AXIS_NAMES = ("X", "Y", "Z")

FACE_PHRASES = {
    "bottom": "as modelled, on its bottom face",
    "top": "upside down, on its top face",
    "front": "on its front face",
    "back": "on its back face",
    "left": "on its left side",
    "right": "on its right side",
}


def face_down_transform(face: str) -> np.ndarray:
    """4x4 rotation that turns `face` to point straight down at the bed."""
    if face not in FACE_DIRECTIONS:
        raise ValueError(f"Unknown face {face!r}")
    if face == "bottom":
        return np.eye(4)
    return trimesh.geometry.align_vectors(FACE_DIRECTIONS[face], (0.0, 0.0, -1.0))


def orient_mesh(mesh: trimesh.Trimesh, face: str) -> trimesh.Trimesh:
    """A copy of the mesh with `face` down. The slicer drops it onto the bed itself."""
    turned = mesh.copy()
    turned.apply_transform(face_down_transform(face))
    return turned
