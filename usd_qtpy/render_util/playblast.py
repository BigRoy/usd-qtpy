# Playblast framework
# Inspired by: Prism, usdrecord

# NOTES:
# pxr.UsdViewq.ExportFreeCameraToStage will export the camera from the view (a FreeCamera/ pxr.Gf.Camera, purely OpenGL)

from pxr import Usd, UsdGeom
from pxr import UsdAppUtils
from pxr import Tf, Sdf

from pxr.Usdviewq.stageView import StageView
from viewer import CustomStageView

from qtpy import QtCore

from typing import Union
import logging

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

def cameraFromView(stage : Usd.Stage, stageview : Union[StageView, CustomStageView], name : str = "playblastCam") -> UsdGeom.Camera:
    """ Catches a stage view whether it'd be from the custom viewer or from the baseclass and calls the export to stage function."""
    stageview.ExportFreeCameraToStage(stage,name)
    return UsdGeom.Camera.Get(stage,Sdf.Path(f"/{name}"))

# Source: UsdAppUtils.colorArgs.py
def getColorArgs():
    return ("disabled","sRGB","openColorIO")

def getComplexityLevels():
    """
    Returns a generator that iterates through all registered complexity presets in UsdAppUtils.complexityArgs
    """
    from pxr.UsdAppUtils.complexityArgs import RefinementComplexities as Complex
    return (item.name for item in Complex._ordered)

def getAllRenderEngineNames():
    """
    Returns a generator that will iterate through all names of Render Engine Plugin / Hydra Delegates
    """
    from pxr.UsdImagingGL import Engine as En
    return (En.GetRendererDisplayName(pluginId) for pluginId in En.GetRendererPlugins())

def getRenderPlugin(enginestr : str):
    from pxr.UsdImagingGL import Engine as En
    for plug in En.GetRendererPlugins():
        if enginestr == En.GetRendererDisplayName(plug):
            return plug
    return None

def checkRenderEngineName(enginestr : str) -> Union[str, None]:
    plugnames = getAllRenderEngineNames()
    if enginestr in plugnames:
        return enginestr
    return None

def renderPlayblast(stage : Usd.Stage, outputpath : str, frames : str, width : int, 
                    camera : UsdGeom.Camera = None, complexity : Union[str,int] = "High",
                    renderer : str = "GL", colormode : str = "sRGB"): 
    from pxr.UsdAppUtils.framesArgs import FrameSpecIterator, ConvertFramePlaceholderToFloatSpec
    from pxr.UsdAppUtils.complexityArgs import RefinementComplexities as Complex
    from pxr import UsdUtils

    # rectify pathname for use in .format with path.format(frame = timeCode.getValue())gi
    if not (outputpath := ConvertFramePlaceholderToFloatSpec(outputpath)):
        raise ValueError("Invalid/Empty filepath for rendering")

    # ensure right complexity object is picked.
    # the internal _RefinementComplexity.value is used to set rendering quality
    if isinstance(complexity,str):
        # ensure key correctness
        complexity = complexity.lower() # set all to lowercase
        complexity = complexity.title() # Uppercase Each Word (In Case Of "Very High")
        preset_names = getComplexityLevels()
        if complexity not in preset_names:
            raise ValueError(f"Value: {complexity} entered for complexity is not valid")
        
        complex_level = Complex.fromName(complexity)
    elif isinstance(complexity,int):
        complexity = min(max(complexity,0),3) # clamp to range of 0-3, 4 elements
        complex_level = Complex._ordered[complexity]

    complex_level = complex_level.value

    # validate render engine
    if not checkRenderEngineName(renderer):
        raise ValueError(f"Render engine arguement invalid")
    renderer = getRenderPlugin(renderer)

    # TEMP: pick first found camera
    if not camera:
        camera = next(findCameras(stage), None)
        if not camera:
            # Same procedure as default for pxr.UsdAppUtils.cameraArgs.py
            path = Sdf.Path(UsdUtils.GetPrimaryCameraName())
            camera = UsdAppUtils.GetCameraAtPath(stage, path)

    if colormode not in getColorArgs():
        raise ValueError("Color correction mode specifier is invalid.")

    # Set up OpenGL FBO to write to within Widget
    # Actual size doesn't matter
    # it does need to be stored in a variable though, otherwise it'll be collected
    ogl_widget = _setupOGLWidget(width,width) 

    # Create FrameRecorder
    frameRecorder = UsdAppUtils.FrameRecorder()
    frameRecorder.SetRendererPlugin(renderer)
    frameRecorder.SetImageWidth(width) # Only width is needed, heigh will be computer from camera properties.
    frameRecorder.SetComplexity(complex_level)
    frameRecorder.SetColorCorrectionMode(colormode)
    #frameRecorder.SetIncludedPurposes(["default","render","proxy","guide"]) # set to all purposes for now.

    # Use Usds own frame specification parser
    # The following are examples of valid FrameSpecs:
    # 123 - 101:105 - 105:101 - 101:109x2 - 101:110x2 - 101:104x0.5
    frame_iterator = FrameSpecIterator(frames)

    if not frame_iterator:
        frame_iterator = [Usd.TimeCode.EarliestTime()]

    for timeCode in frame_iterator:
        currentframe = outputpath.format(frame = timeCode.GetValue())
        print(currentframe)
        try:
            print("attempting render")
            frameRecorder.Record(stage, camera, timeCode, currentframe)
            print("Done!")
        except Tf.ErrorException as e:
            logging.error("Recording aborted due to the following failure at time code {0}: {1}".format(timeCode, str(e)))
            break
    
    # Set reference to None so that it can be collected before Qt context.
    frameRecorder = None