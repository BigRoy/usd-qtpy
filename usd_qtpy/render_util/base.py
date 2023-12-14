# Provides mixins and classes to be inherited from, as well as decorators
import os
from contextlib import contextmanager
from functools import wraps
from typing import Callable, Union

from qtpy import QtCore
from pxr import Usd, Sdf

TEMPFOLDER = "./temp"


def get_tempfolder() -> str:
    """
    Utility function to get temporary folder adress from module
    """
    return TEMPFOLDER


def using_tempfolder(func: Callable):
    """
    Decorator to indicate use of temporary folder, 
    so that it may be cleaned up after.
    """

    tempfolder: str = TEMPFOLDER

    @wraps(func)
    def wrapper(*args,**kwargs):
        # make temp folder
        if not os.path.isdir(tempfolder):
            os.mkdir(tempfolder)

        # execute function
        result = func(*args,**kwargs)
        # remove temp folder

        os.rmdir(tempfolder)
    
        return result

    return wrapper


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
        

class TempStageOpen:
    """
    Context manager for Usd.Stage that needs to temporarily be open.
    """
    def __init__(self, path: str, remove_file: bool = False):
        self._stage = Usd.Stage.Open(path)
        self._remove_file = remove_file
        self._path = path

    def __enter__(self) -> Usd.Stage:
        return self._stage
    
    def __exit__(self, type, value, traceback):
        del self._stage
        if self._remove_file:
            os.remove(self._path)


class RenderReportable:
    """
    Mixin class to set up signals for everything needing slots.
    """
    render_progress: QtCore.Signal = QtCore.Signal(int)
    total_frames: QtCore.Signal = QtCore.Signal(int)