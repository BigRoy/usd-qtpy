# Turn table utilities.

from typing import Union, Tuple, List
import logging

from pxr import Usd, UsdGeom, Sdf, Gf

from . import framing_camera, playblast
from .base import (
    RenderReportable
)

log = logging.getLogger(__name__)


def create_turntable_xform(stage: Usd.Stage,
                           path: Union[Sdf.Path, str],
                           length: int = 100, 
                           frame_start: int = 0, 
                           repeats: int = 1,
                           bounds: Gf.Range3d = None) -> UsdGeom.Xform:
    """
    Creates a turntable Xform that contains animation spinning around the up axis, in the center floor of the stage.
    We repeat the entire duration when repeats are given as an arguement.
    A length of 100 with 3 repeats will result in a 300 frame long sequence
    """
    is_z_up = framing_camera.get_stage_up(stage) == "Z"
    
    if bounds is None:
        bounds = framing_camera.get_stage_boundingbox(stage)
    centroid = bounds.GetMidpoint()

    xform = UsdGeom.Xform.Define(stage, path)

    if is_z_up:
        # Z axis = floor normal
        translate = Gf.Vec3d(centroid[0], centroid[1], 0)
    else:
        # Y axis = floor normal
        translate = Gf.Vec3d(centroid[0], 0, centroid[2])

    # Move to centroid of bounds, rotate, move back to origin
    precision = UsdGeom.XformOp.PrecisionDouble
    xform.AddTranslateOp(precision, "rotPivot").Set(translate)
    add_turntable_spin_op(xform, length, frame_start, repeats, is_z_up)
    xform.AddTranslateOp(precision, "rotPivot", isInverseOp=True)
    
    return xform


def create_turntable_camera(stage: Usd.Stage,
                            root: Union[Sdf.Path, str] = Sdf.Path("/"),
                            name: str = "turntableCam",
                            fit: float = 1.1,
                            width: int = 16,
                            height: int = 9,
                            length: int = 100,
                            frame_start: int = 0) -> UsdGeom.Camera:
    """
    Creates a complete setup with a stage framing perspective camera, within an animated, rotating Xform.
    """
    if isinstance(root, str):
        root = Sdf.Path(root)

    xform_path = root.AppendChild("turntableXform")
    create_turntable_xform(
        stage,
        path=xform_path,
        length=length,
        frame_start=frame_start
    )

    cam = framing_camera.create_framing_camera_in_stage(
        stage, xform_path, name, fit, width, height)

    return cam


def add_turntable_spin_op(xformable: UsdGeom.Xformable,
                          length: int = 100,
                          frame_start: int = 0,
                          repeats: int = 1,
                          is_z_up: bool = False) -> UsdGeom.XformOp:
    """Add Rotate XformOp with 360 degrees turntable rotation keys to prim"""
    # TODO: Maybe check for existing operations before blatantly adding one.
    if is_z_up:
        spin_op = xformable.AddRotateZOp(UsdGeom.XformOp.PrecisionDouble)
    else:
        spin_op = xformable.AddRotateYOp(UsdGeom.XformOp.PrecisionDouble)

    spin_op.Set(time=frame_start, value=0)

    # Avoid having the last frame the same as the first frame so the cycle
    # works out nicely over the full length. As such, we remove one step
    frame_end = frame_start + (length * repeats) - 1
    step_per_frame = 360 / length
    spin_op.Set(time=frame_end, value=(repeats * 360) - step_per_frame)

    return spin_op


def get_turntable_frames_string(length: int = 100,
                                frame_start: int = 0,
                                repeats: int = 1) -> str:
    """
    Get a usable string argument for frames from turntable time params.
    """
    frame_end = frame_start + (length * repeats) - 1
    return playblast.get_frames_string(frame_start, frame_end, 1)


def turntable_from_preset(
        stage: Usd.Stage,
        preset_filename: str = "./assets/turntable/turntable_preset.usda",
        camera_path: Union[str, Sdf.Path] = None
) -> Tuple[Usd.Stage, UsdGeom.Camera]:
    """Generate a turntable from a preset USD file.
    
    The turntable preset file must have the following structure:
    - /turntable <- default primitive Xform
    - /turntable/parent <- Xform that rotates
    - a camera somewhere under /turntable/
    
    Optional:
    - /turntable/bounds/bound_box <- a geometry primitive 
                                     that scales input to fit itself.
    """
    # TODO: Infer frame range from turntable stage.

    # Create scene in memory that references the turntable preset
    # and into it references the subject stage
    turntable_stage = Usd.Stage.CreateInMemory()
    turntable_ref = turntable_stage.OverridePrim("/turntable")
    turntable_ref.GetReferences().AddReference(preset_filename)

    # Conform turntable to Y up
    if _is_file_z_up_axis(preset_filename):
        turntable_ref_xformable = UsdGeom.Xformable(turntable_ref)
        turntable_ref_xformable.AddRotateXOp().Set(-90)

    # Get camera
    if camera_path:
        camera_path = Sdf.Path(camera_path)
        camera_prim = turntable_stage.GetPrimAtPath(camera_path)
        if not camera_prim.IsValid():
            raise RuntimeError(
                f"Turntable Camera at {camera_path.pathString} is missing."
            )

        turntable_camera = UsdGeom.Camera(camera_prim)
    else:
        # Find first camera in the stage
        turntable_camera = next(playblast.iter_stage_cameras(turntable_stage),
                                None)

    # Get turntable parent prim
    turntable_parent_prim = turntable_stage.GetPrimAtPath("/turntable/parent")

    # Validate
    missing = []
    if not turntable_parent_prim.IsValid():
        missing.append("Missing: /turntable/parent")
    if turntable_camera is None:
        missing.append("Missing: Usd Camera")
    if missing:
        raise RuntimeError(
            "Turntable file doesn't have all necessary components."
            "\n" + "\n".join(missing)
        )

    # Create a reference within the parent of the new turntable stage
    # References do need xformables created.
    subject_layer = stage.Flatten()
    subject_ref = turntable_stage.OverridePrim("/turntable/parent/subject")
    subject_ref.GetReferences().AddReference(subject_layer.identifier)
    subject_prim = turntable_stage.GetPrimAtPath("/turntable/parent")

    subject_ref_xformable = UsdGeom.Xformable(subject_ref)
    subject_zup = framing_camera.get_stage_up(stage) == "Z"
    if subject_zup:
        subject_ref_xformable.AddRotateXOp().Set(-90)

    # get bbox of subject and center stage
    timecode = 0
    bbox_cache = UsdGeom.BBoxCache(timecode, ["default"])

    # Get goal geometry boundingbox if it exists, and fit primitive to it
    bbox_prim = turntable_stage.GetPrimAtPath("/turntable/bounds")
    if bbox_prim.IsValid():
        subject_nofit_bound = bbox_cache.ComputeWorldBound(subject_prim)
        goal_bound = bbox_cache.ComputeWorldBound(bbox_prim)

        # Get minimum size ratio across different axes
        min_sizediff = min(
            _goal_size / _subject_size
            for _goal_size, _subject_size
            in zip(goal_bound.GetBox().GetSize(),
                   subject_nofit_bound.GetBox().GetSize())
        )

        # SCALE
        subject_ref_xformable.AddScaleOp(UsdGeom.XformOp.PrecisionDouble)\
                             .Set(Gf.Vec3d(min_sizediff))
    else:
        min_sizediff = 1

    subject_prim = turntable_stage.GetPrimAtPath("/turntable/parent")
    
    # clear bboxcache
    bbox_cache.Clear()

    # get bbox of subject and center stage
    subject_bbox = bbox_cache.ComputeWorldBound(subject_prim).GetBox()
    subject_bounds_min = subject_bbox.GetMin()
    subject_centroid = subject_bbox.GetMidpoint()

    # center geometry.
    if subject_zup:
        subject_center_translate = Gf.Vec3d(
            -subject_centroid[0] / min_sizediff,
            subject_centroid[2] / min_sizediff,
            -subject_bounds_min[1] / min_sizediff
        )
    else:
        subject_center_translate = Gf.Vec3d(
            -subject_centroid[0] / min_sizediff,
            -subject_bounds_min[1] / min_sizediff,
            -subject_centroid[2] / min_sizediff
        )
    
    subject_ref_xformable.AddTranslateOp(
        UsdGeom.XformOp.PrecisionDouble,
        "center_centroid"
    ).Set(subject_center_translate)

    return turntable_stage, turntable_camera


def render_turntable_from_preset(
        stage: Usd.Stage,
        preset_filename: str = "./assets/turntable/turntable_preset.usda",
        export_path: str = "./temp/render",
        renderer: str = "GL",
        length: int = 100,
        frame_start: int = 1,
        repeats: int = 1,
        width: int = 16,
        height: int = 9,
        camera_path: Union[str, Sdf.Path] = None,
        qt_report_instance: RenderReportable = None
) -> List[str]:
    turntable_stage, turntable_camera = turntable_from_preset(
        stage=stage,
        preset_filename=preset_filename,
        camera_path=camera_path
    )

    # turn off the lights if GL
    if renderer == "GL":
        # These will be turned off for GL renders, because GL renders are lit
        # by default. The introduction of lights would make the renders
        # overexposed.
        # TODO: Confirm whether this can be resolved by disabling the default
        #  camera light from the usdview stage.
        lights_prim = turntable_stage.GetPrimAtPath("/turntable/scene/lights")
        if lights_prim.IsValid():
            lights_prim.GetAttribute("visibility").Set("invisible", 0)

    framing_camera.camera_conform_sensor_to_aspect(
        turntable_camera,
        width,
        height
    )

    frames_string = get_turntable_frames_string(length, frame_start, repeats)
    return playblast.render_playblast(
        stage=turntable_stage,
        outputpath=export_path,
        frames=frames_string,
        width=width,
        camera=turntable_camera,
        renderer=renderer,
        qt_report_instance=qt_report_instance
    )


def _is_file_z_up_axis(path: str) -> bool:
    """Return whether layer has up axis opinion set to Z-axis"""
    layer = Sdf.Layer.FindOrOpen(path)
    return layer.pseudoRoot.GetInfo(UsdGeom.Tokens.upAxis) == "Z"
