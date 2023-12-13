# Provides mixins and classes to be inherited from, as well as decorators
import os
from functools import wraps
from typing import Callable

from qtpy import QtCore

TEMPFOLDER = "./temp"

def get_tempfolder() -> str:
    """
    Utility function to get temporary folder adress from module
    """
    return TEMPFOLDER

def using_tempfolder(func):
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





class RenderReportable:
    """
    Mixin class to set up signals for everything needing slots.
    """
    render_progress: QtCore.Signal = QtCore.Signal(int)
    total_frames: QtCore.Signal = QtCore.Signal(int)