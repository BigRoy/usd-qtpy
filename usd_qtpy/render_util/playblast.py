# Playblast framework
# Inspired by: Prism, usdrecord

# NOTES:
# pxr.UsdViewq.ExportFreeCameraToStage will export the camera from the view (a FreeCamera/ pxr.Gf.Camera, purely OpenGL)

from pxr import Usd, UsdGeom
from pxr import UsdAppUtils
from pxr import Tf

from pxr.Usdviewq.stageView import StageView
from viewer import CustomStageView

from qtpy import QtWidgets, QtCore

from typing import Union

def _setupOGLWidget(width : int, height : int, samples : int = 4):
    """
    Utility function to produce a Qt openGL widget capable of catching
    the output of a render
    """

    from qtpy import QtOpenGL

    # format object contains information about the Qt OpenGL buffer.
    QGLformat = QtOpenGL.QGLFormat()
    QGLformat.setSampleBuffers(True) # Enable multisample buffer
    QGLformat.setSamples(samples) # default samples is 4 / px

    GLWidget = QtOpenGL.QGLWidget(QGLformat)
    GLWidget.setFixedSize(QtCore.QSize(width,height))

    GLWidget.makeCurrent() # bind widget buffer as target for OpenGL operations.

    return GLWidget

def findCameras(stage : Usd.Stage, TraverseAll = True) -> list[UsdGeom.Camera]:
    """
    Return all camera primitives.
    TraverseAll is on by default. This means that inactive cameras will also be shown.
    """

    if TraverseAll:
        gen = stage.TraverseAll()
    else: 
        gen = stage.Traverse()
    
    cams = [c for c in gen if UsdGeom.Camera(c)]
    return cams

def camera_from_view(stage : Usd.Stage, stageview : Union[StageView, CustomStageView], name : str = "playblastCam"):
    """ Catches a stage view whether it'd be from the custom viewer or from the baseclass and calls the export to stage function."""
    stageview.ExportFreeCameraToStage(stage,name)


def renderPlayblast(stage : Usd.Stage, width : int, height : int): 
    ...