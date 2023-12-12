# Provides mixins and classes to be inherited from.

from qtpy import QtCore

class RenderReportable:
    """
    Mixin class to set up signals for everything needing slots.
    """
    render_progress: QtCore.Signal = QtCore.Signal(int)
    total_frames: QtCore.Signal = QtCore.Signal(int)