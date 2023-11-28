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

def renderPlayblast(stage : Usd.Stage, outputpath : str, frames : str, width : int, 
                    camera : UsdGeom.Camera = None, renderer : str = None, complexity : Union[str,int] = "High"): 
    from pxr.UsdAppUtils.framesArgs import FrameSpecIterator, ConvertFramePlaceholderToFloatSpec
    from pxr.UsdAppUtils.complexityArgs import RefinementComplexities as Complex

    # rectify pathname for use in .format with path.format(frame = timeCode.getValue())
    if outputpath:
        if (outputpath := ConvertFramePlaceholderToFloatSpec(outputpath)) is None:
            raise ValueError("Invalid filepath for rendering")
    else:
        raise ValueError("No filepath entered")

    # ensure right complexity object is picked.
    if isinstance(complexity,str):
        # ensure key correctness
        complexity = complexity.lower() # set all to lowercase
        complexity = complexity.title() # Uppercase Each Word (In Case Of "Very High")
        if complexity not in ["Low", "Medium", "High", "Very High"]:
            raise ValueError(f"Value: {complexity} entered for complexity is not valid.")
        
        complex_level = Complex.fromName(complexity)
    elif isinstance(complexity,int):
        complexity = min(max(complexity,0),3) # clamp to range of 0-3, 4 elements
        complex_level = Complex.ordered[complexity]


    # TEMP: pick first found camera
    if camera is None:
        camera = next(findCameras(stage))

    # Use Usds own frame specification parser
    # The following are examples of valid FrameSpecs:
    # 123 - 101:105 - 105:101 - 101:109x2 - 101:110x2 - 101:104x0.5
    frame_iterator = FrameSpecIterator(frames)

    if not frame_iterator:
        frame_iterator = [Usd.TimeCode.EarliestTime()]

    for timeCode in frame_iterator:
        currentframe = outputpath.format(frame = timeCode.GetValue())