# Dialog functions and wrappers to do with the rendering API.
import os
import re

from qtpy import QtWidgets
from pxr import Usd
from pxr.Usdviewq.stageView import StageView

from . import playblast


def _rectify_path_framenumberspec(path: str, padding: int = 4) -> str:
    """Ensure a placeholder for framenumbers exists in the path.

    >>> _rectify_path_framenumberspec("filename##.png")
    # "filename####.png"

    >>> _rectify_path_framenumberspec("filename###.png")
    # "filename####.png"

    Returns:
        str: The path with an ensured frame number hash.

    """
    base, file = os.path.split(path)
    file, extension = os.path.splitext(file)
    # if too little hashes were present, remove them.
    file.replace("#", "")
    file += "#" * padding

    return os.path.join(base, file + extension)


def _savepicture_dialog(stage: Usd.Stage,
                        stageview: StageView,
                        width: int = 16,
                        height: int = 9):
    """
    Save a simple snap of the scene to a given folder.
    """

    filename, _ = QtWidgets.QFileDialog.getSaveFileName(
        caption="Save frame",
        filter="PNG (*.png);;JPEG (*.jpg, *.jpeg)"
    )

    camera = playblast.camera_from_stageview(stage, stageview, "viewerCamera")

    # ensure there's at least two or more hashes, if not, put in 4.
    # QUESTION: Why do we need to enforce at least two hashes?
    REGEX_HASH = r"(#{2,})"
    hash_match = re.match(REGEX_HASH, filename)
    if not hash_match:
        filename = _rectify_path_framenumberspec(filename)    
    
    # ensure camera aspect ratio
    # QUESTION: Why 24? Why that magic number?
    aspect_ratio: float = width / float(height)
    camera.CreateHorizontalApertureAttr(24 * aspect_ratio)
    camera.CreateHorizontalApertureOffsetAttr(0)
    camera.CreateVerticalApertureAttr(24)
    camera.CreateVerticalApertureOffsetAttr(0)

    frame_timecode: Usd.TimeCode = stageview._dataModel.currentFrame
    
    # cannot be earliest timecode when passing as argument.
    if frame_timecode == Usd.TimeCode.EarliestTime():
        frame_timecode = None

    frames = "0" if frame_timecode is None else frame_timecode.GetValue()
    playblast.render_playblast(stage, filename,
                               frames=frames,
                               width=1920,
                               camera=camera)

    stage.RemovePrim(camera.GetPath())
    