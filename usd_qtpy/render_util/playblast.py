# Playblast framework
import logging
import sys
import os
from typing import Union
from collections.abc import Generator

from qtpy import QtCore
from pxr import Usd, UsdGeom
from pxr import UsdAppUtils
from pxr import Tf, Sdf
from pxr.Usdviewq.stageView import StageView


def _setup_opengl_widget(width: int, height: int, samples: int = 4):
    """
    Utility function to produce a Qt openGL widget capable of catching
    the output of a render
    """

    from qtpy import QtOpenGL

    # format object contains information about the Qt OpenGL buffer.
    QGLformat = QtOpenGL.QGLFormat()
    QGLformat.setSampleBuffers(True)  # Enable multisample buffer
    QGLformat.setSamples(samples)     # default samples is 4 / px

    GLWidget = QtOpenGL.QGLWidget(QGLformat)
    GLWidget.setFixedSize(QtCore.QSize(width, height))

    GLWidget.makeCurrent()  # bind widget buffer as target for OpenGL operations.

    return GLWidget


def iter_stage_cameras(stage: Usd.Stage, traverse_all=True) -> Generator[UsdGeom.Camera]:
    """
    Return a generator of all camera primitives.
    TraverseAll is on by default. This means that inactive cameras will also be shown.
    """
    # Ref on differences between traversal functions:
    #   https://openusd.org/dev/api/class_usd_stage.html#adba675b55f41cc1b305bed414fc4f178
    if traverse_all:
        gen = stage.TraverseAll()
    else: 
        gen = stage.Traverse()
    
    for prim in gen:
        if prim.IsA(UsdGeom.Camera):
            yield prim


def camera_from_stageview(stage: Usd.Stage,
                          stageview: StageView,
                          name: str = "playblastCam") -> UsdGeom.Camera:
    """Create Stage View's current free camera as a regular UsdGeom.Camera.

    Basically calls stage view's `ExportFreeCameraToStage` method.

    The `pxr.UsdViewq.ExportFreeCameraToStage` will export the camera from
    the view. A FreeCamera (`pxr.Gf.Camera`), which is purely OpenGL.
    """
    stageview.ExportFreeCameraToStage(stage, name)
    return UsdGeom.Camera.Get(stage, Sdf.Path(f"/{name}"))


# Source: UsdAppUtils.colorArgs.py
def get_color_args():
    return ("disabled", "sRGB", "openColorIO")


def get_complexity_levels() -> Generator[str]:
    """
    Returns a generator that iterates through all registered complexity presets in UsdAppUtils.complexityArgs
    """
    from pxr.UsdAppUtils.complexityArgs import RefinementComplexities
    return (item.name for item in RefinementComplexities.ordered())


def iter_renderplugin_names() -> Generator[str]:
    """
    Returns a generator that will iterate through all names of Render Engine Plugin / Hydra Delegates
    """
    from pxr.UsdImagingGL import Engine
    return (
        Engine.GetRendererDisplayName(pluginId)
        for pluginId in Engine.GetRendererPlugins()
    )


def get_renderplugin_by_display_name(renderer_display_name: str):
    from pxr.UsdImagingGL import Engine
    for plug in Engine.GetRendererPlugins():
        if renderer_display_name == Engine.GetRendererDisplayName(plug):
            return plug
    return None


def get_frames_string(start_time: int, end_time: int = None, frame_stride: float = None) -> str:
    """
    Takes a set of numbers and structures it so that it can be passed as frame string argument to e.g. render_playblast
    Given only a start time, it'll render a frame at that frame.
    Given a start and end time, it'll render a range from start to end, including end. (0-100 = 101 frames)
    Given a start, end, and stride argument, it'll render a range with a different frame interval. 
    (rendering every other frame can be done by setting this to 2.)
    Output for 1, 2 and 3 arguments respectively: 
    'start_time', 'start_time:end_time', 'start_time:end_timexframe_stride'
    as defined by the USD standard.
    """
    # Keep adhering to USD standard as internally defined.
    from pxr.UsdUtils import TimeCodeRange
    range_token = TimeCodeRange.Tokens.RangeSeparator   # ":"
    stride_token = TimeCodeRange.Tokens.StrideSeparator # "x"
    
    collect = f"{start_time}"

    if end_time is not None:
        collect += f"{range_token}{end_time}"
        if frame_stride is not None:
            collect += f"{stride_token}{frame_stride}"
    
    return collect


def tuples_to_frames_string(time_tuples: list[Union[tuple[int], tuple[int, int], tuple[int, int, float]]]) -> str:
    """
    Convert an iterable (e.g. list/generator) of tuples containing structured frame data:
    tuple(start_time, end_time, frame_stride), same as the arguments to get_frames_string,
    to a single string that can be parsed as a frames_string argument for multiple frames.
    example input: (1,) , (1 , 50, 0.5), (8,10)
    example output: '1,1:50x0.5,8:10'
    (according to standards defined for UsdAppUtils.FrameRecorder)
    """
    # keep adhering to USD standard as internally defined.
    from pxr.UsdAppUtils.framesArgs import FrameSpecIterator
    separator_token = FrameSpecIterator.FRAMESPEC_SEPARATOR # ","

    def tuple_gen(tuple_iterable):
        for val in tuple_iterable:
            if len(val) <= 3:
                yield get_frames_string(*val)
    
    return separator_token.join(tuple_gen(time_tuples))


def render_playblast(
        stage: Usd.Stage,
        outputpath: str,
        frames: str,
        width: int,
        camera: UsdGeom.Camera = None,
        complexity: Union[str, int] = "High",
        renderer: str = None,
        colormode: str = "sRGB") -> list[str]:
    """Render one or multiple frames from a usd stage's camera.

    Arguments:
        stage: The stage to process.
        outputpath (str): Output filepath to write to.
        frames (str): The frames to render as a string.
        width (int): The resolution width to output.
            The height will be based on camera properties.
        camera (UsdGeom.Camera): The camera to render from.
        complexity (Union[str, int]): Complexity to render, defaults to "High"
        renderer (str): The renderer to render with. Defaults to the current
            platform's default renderer, GL or Metal (osx)
        colormode (str): The color management mode to render with.
            Defaults to "sRGB". See `get_color_args` for available options.

    Returns:
        list[str]: The rendered output files.

    """

    from pxr.UsdAppUtils.framesArgs import FrameSpecIterator, ConvertFramePlaceholderToFloatSpec
    from pxr.UsdAppUtils.complexityArgs import RefinementComplexities as Complex
    from pxr import UsdUtils

    # check existence of directory.
    directory = os.path.dirname(outputpath)
    if not os.path.exists(directory):
        raise FileNotFoundError(
            f"Directory '{directory}' not found, directory must exist "
            "before rendering to it."
        )

    # rectify pathname for use in .format with path.format(frame = timeCode.getValue())
    if not (outputpath := ConvertFramePlaceholderToFloatSpec(outputpath)):
        raise ValueError("Invalid/Empty filepath for rendering")

    # ensure right complexity object is picked.
    # the internal _RefinementComplexity.value is used to set rendering quality
    if isinstance(complexity, str):
        # ensure key correctness
        complexity = complexity.lower()  # set all to lowercase
        complexity = complexity.title()  # Uppercase Each Word (In Case Of "Very High")
        preset_names = get_complexity_levels()
        if complexity not in preset_names:
            raise ValueError(f"Value: {complexity} entered for complexity is not valid")
        
        complex_level = Complex.fromName(complexity)
    elif isinstance(complexity, int):
        complexity = min(max(complexity, 0), 3)  # clamp to range of 0-3, 4 elements
        complex_level = Complex.ordered()[complexity]
    else:
        raise TypeError("Complexity must be eitehr `str` or `int`")

    complex_level = complex_level.value

    # deduce default renderer based on platform if not specified.
    if renderer is None:
        if sys.platform == "nt" or os == "win32":
            renderer = "GL"
        elif sys.platform == "darwin":
            renderer = "Metal"
        else:
            renderer = "GL"

    # validate render engine
    renderer = get_renderplugin_by_display_name(renderer)
    if renderer is None:
        raise ValueError("Render plugin argument invalid")

    # No Camera: Assume scene wide camera (same behavior as usdrecord)
    if not camera:
        # Same procedure as default for pxr.UsdAppUtils.cameraArgs.py
        print("No cam specified, using PrimaryCamera")
        path = Sdf.Path(UsdUtils.GetPrimaryCameraName())
        camera = UsdAppUtils.GetCameraAtPath(stage, path)

    if colormode not in get_color_args():
        raise ValueError("Color correction mode specifier is invalid.")

    # Set up OpenGL FBO to write to within Widget, actual size doesn't matter
    # We do need to keep a variable reference to avoid garbage collection
    ogl_widget = _setup_opengl_widget(width, width)  # noqa

    # Create FrameRecorder
    frame_recorder = UsdAppUtils.FrameRecorder()
    frame_recorder.SetRendererPlugin(renderer)
    frame_recorder.SetImageWidth(width)  # Only width is needed, height will be computed from camera properties.
    frame_recorder.SetComplexity(complex_level)
    frame_recorder.SetColorCorrectionMode(colormode)
    # frameRecorder.SetIncludedPurposes(["default","render","proxy","guide"])  # set to all purposes for now.

    # Use Usds own frame specification parser
    # The following are examples of valid FrameSpecs:
    # 123 - 101:105 - 105:101 - 101:109x2 - 101:110x2 - 101:104x0.5
    frame_iterator = FrameSpecIterator(frames)

    if not frame_iterator or not frames:
        frame_iterator = [Usd.TimeCode.EarliestTime()]

    output_files = []
    for time_code in frame_iterator:
        current_frame = outputpath.format(frame=time_code.GetValue())
        try:
            frame_recorder.Record(stage, camera, time_code, current_frame)
        except Tf.ErrorException as e:
            logging.error(
                "Recording aborted due to the following "
                "failure at time code %s: %s", time_code, e
            )
            break
        output_files.append(current_frame)
    
    # Set reference to None so that it can be collected before Qt context.
    frame_recorder = None

    return output_files
