# Provides mixins and classes to be inherited from, as well as decorators
import os
from contextlib import contextmanager
from typing import Union

from qtpy import QtCore
from pxr import Usd, Sdf


@contextmanager
def defer_file_deletion(path: str):
    try:
        yield None
    finally:
        os.remove(path)


@contextmanager
def defer_primpath_deletion(stage: Usd.Stage, path: Union[str, Sdf.Path]):
    if isinstance(path, str):
        path = Sdf.Path(path)
    try:
        yield None
    finally:
        stage.RemovePrim(path)


class RenderReportable:
    """
    Mixin class to set up signals for everything needing slots.
    """
    render_progress = QtCore.Signal(int)
    total_frames = QtCore.Signal(int)
