# Generates Stage framing camera.
# heavy inspiration taken from: 
# https://github.com/beersandrew/assets/tree/1df93f4da686e9040093027df1e42ff9ea694866/scripts/thumbnail-generator

import math
from typing import Union

from pxr import Usd, UsdGeom
from pxr import Sdf, Gf


def get_stage_up(stage: Usd.Stage) -> str:
    """Return Usd.Stage up axis"""
    return UsdGeom.GetStageUpAxis(stage)


def create_framing_camera_in_stage(stage: Usd.Stage,
                                   root: Union[Sdf.Path,str],
                                   name: str = "framingCam",
                                   fit: float = 1,
                                   width: int = 16,
                                   height: int = 9) -> UsdGeom.Camera:
    """
    Adds a camera that frames the whole stage.
    Can be specified to have a different aspect ratio, this will affect the sensor size internally.
    """
    if isinstance(root,str):
        root = Sdf.Path(root)

    # create camera
    camera_path = root.AppendChild(name)
    camera = create_perspective_camera_in_stage(stage, camera_path, width, height)

    # Do prerequisite math
    bounds = get_stage_boundingbox(stage)
    is_z_up = get_stage_up(stage) == "Z"

    distance_to_stage = calculate_distance_to_fit_bounds(camera, bounds,
                                                         is_z_up, fit)

    # setup attributes in camera
    set_camera_fitting_clipping_planes(camera, bounds,
                                       is_z_up, distance_to_stage)

    # translate THEN rotate. Translation is always done locally.
    # If this needs to be switched around, swizzle translation Vec3d.
    translation = calculate_camera_position(bounds, is_z_up, distance_to_stage)
    set_first_translation(camera, translation)

    if is_z_up:
        _orient_to_z_up(camera)
    
    return camera


def create_perspective_camera_in_stage(stage: Usd.Stage,
                                       path: Sdf.Path,
                                       width: int = 16,
                                       height: int = 9) -> UsdGeom.Camera:
    """
    Creates a camera in the scene with a certain sensor size. 
    Defaults to 16:9 aspect ratio.
    """
    # Calculate aspect ratio. Cast divisor to float to prevent integer division
    aspect_ratio: float = width / float(height) 

    camera = UsdGeom.Camera.Define(stage, path)

    camera.CreateFocusDistanceAttr(168.60936)
    camera.CreateFStopAttr(0)
    
    camera.CreateHorizontalApertureAttr(24 * aspect_ratio)
    camera.CreateHorizontalApertureOffsetAttr(0)
    camera.CreateVerticalApertureAttr(24)
    camera.CreateVerticalApertureOffsetAttr(0)

    camera.CreateProjectionAttr("perspective")

    return camera


def _orient_to_z_up(xformable: UsdGeom.Xformable):
    """Rotate around X-axis by 90 degrees to orient for Z-up axis."""
    xformable.AddRotateXOp().Set(90)


def set_first_translation(xformable: UsdGeom.Xformable,
                          translation: Gf.Vec3d) -> UsdGeom.XformOp:
    """Apply translation to first found translation operation in given Camera.

    If no translation op is found then one will be added.
    """
    # check for existing translation operation, if not found, add one to stack.
    for op in xformable.GetOrderedXformOps():
        op: UsdGeom.XformOp
        if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
            translate_op = op
            break
    else:
        translate_op = xformable.AddTranslateOp()

    translate_op.Set(translation)
    return translate_op


def set_camera_fitting_clipping_planes(
        camera: UsdGeom.Camera,
        bounds: Gf.Range3d = None,
        z_up: bool = False,
        distance: float = 1.0
):
    """Set camera clipping plane attributes to fit the bounds."""

    bounds_min = bounds.GetMin()
    bounds_max = bounds.GetMax()
    vertical_axis_index = 2 if z_up else 1

    # expand clipping planes out a bit.
    near_clip = max((distance + bounds_min[vertical_axis_index]) * 0.5,
                    0.0000001)
    far_clip = (distance + bounds_max[vertical_axis_index]) * 2
    clipping_planes = Gf.Vec2f(near_clip, far_clip)
    camera.GetClippingRangeAttr().Set(clipping_planes)


def get_stage_boundingbox(
        stage: Usd.Stage,
        time: Usd.TimeCode = Usd.TimeCode.EarliestTime(),
        purpose_tokens: list[str] = None
) -> Gf.Range3d:
    """
    Caclulate a stage's bounding box, with optional time and purposes.
    The default for time is the earliest registered TimeCode in the stage's animation.
    The default for purpose tokens is ["default"], 
    valid values are: default, proxy, render, guide.
    """
    if purpose_tokens is None:
        purpose_tokens = ["default"]

    bbox_cache = UsdGeom.BBoxCache(time, purpose_tokens)
    stage_root = stage.GetPseudoRoot()
    return bbox_cache.ComputeWorldBound(stage_root).GetBox()


def calculate_camera_position(bounds: Gf.Range3d,
                              z_up: bool,
                              distance: float) -> Gf.Vec3d:
    """
    Calculate the world position for the camera based off of the size of the bounds and the camera attributes.
    Bounds and distance can be calculated beforehand so

    Suppose a scene with a cone,
                ..
             ../  |    /\
     O O    /     |   /  \
    [cam]<| ------|  /I am\
            \..   | / cone \
               \. |/ fear me\
                  ^
                  |- The focus plane will be here, at the closest depth of the bounds
                     of the scene the camera is pointed at.

    The center of the camera will be positioned at the center of the vertical and horizontal axis,
    (Y and X respectively, assuming y up)
    and positioned back along the with the calculated frustrum-filling distance along the depth axis,
    (Z, assuming y up).
    """
    bounds_min = bounds.GetMin()
    bounds_max = bounds.GetMax()
    centroid = bounds.GetMidpoint()

    if z_up:
        camera_position = Gf.Vec3d(centroid[0],
                                   bounds_min[1]-distance,
                                   centroid[2])
    else:
        camera_position = Gf.Vec3d(centroid[0],
                                   centroid[1],
                                   bounds_max[2] + distance)

    return camera_position


def calculate_distance_to_fit_bounds(camera: UsdGeom.Camera,
                                     bounds: Gf.Range3d,
                                     z_up: bool = None,
                                     fit: float = 1.0) -> float:
    """
    Calculates a distance from the centroid of the stage that would allow a
    camera to frame it perfectly.
    Returns distance in stage units.
    """

    focal_length = camera.GetFocalLengthAttr().Get()
    hor_aperture = camera.GetHorizontalApertureAttr().Get()
    ver_aperture = camera.GetVerticalApertureAttr().Get()

    vertical_axis_index = 2 if z_up else 1

    # get size of bounds
    bounds_max = bounds.GetMax()
    bounds_min = bounds.GetMin()
    d_hor = bounds_max[0] - bounds_min[0]
    d_ver = bounds_max[vertical_axis_index] - bounds_min[vertical_axis_index]

    fov_hor = calculate_field_of_view(focal_length, hor_aperture)
    fov_ver = calculate_field_of_view(focal_length, ver_aperture)
    
    # calculate capture size. the sensor size was given in mm (24 mm sensor) 
    # so we need to pass in cm units from the scene as mm units for
    # correct calculation.
    capturesize_hor = calculate_perspective_distance(d_hor * 10, fov_hor, fit)
    capturesize_ver = calculate_perspective_distance(d_ver * 10, fov_ver, fit)

    # return units back to cm on return
    return max(capturesize_hor, capturesize_ver) / 10


def calculate_field_of_view(focal_length, sensor_size) -> float:
    # Math : https://sdk-forum.dji.net/hc/en-us/articles/11317874071065-How-to-calculate-the-FoV-of-the-camera-lens-
    """Returns field of view in radians.

    Calculates field of view for 1 measurement of the sensor size (width or height)

    With H being the full lens height, we need to divide H by 2
                       H / 2
    AFOV = 2 * atan(  -------  )
                         f
    multiply by 2 because we're only getting the angle towards 1 half of the
    lens from the center, getting the apex angle of an isosceles triangle.

    This expression is rewritten as 2 * atan(h * (2 * f))
    This is however mathematically the same.

    """
    return 2 * math.atan(sensor_size / (2 * focal_length))


def calculate_perspective_distance(subject_size,
                                   field_of_view,
                                   fit: float = 1) -> float:
    """
    Calculate appropriate distance towards the subject, so it can fill the view.
    Essentially, the inverse of calculate_field_of_view.

    We treat the subject_size as if it was the size of a lens here,
    and calculating a focal length that would match it.

    Keep in mind that we're drawing a right triangle towards the center of the
    subject, that is why we are dividing the size in half.

    The field of view is also divided in half, because the whole FOV represents
    the apex angle of the isosceles triangle.

    """
    subject_size *= fit
    return (subject_size / 2) / math.tan(field_of_view / 2)
