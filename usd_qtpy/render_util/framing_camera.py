# Generates Stage framing camera.
# heavy inspiration taken from: 
# https://github.com/beersandrew/assets/tree/1df93f4da686e9040093027df1e42ff9ea694866/scripts/thumbnail-generator

import math
from typing import Union

from pxr import Usd, UsdGeom
from pxr import Sdf, Gf

def _stage_up(stage: Usd.Stage) -> str:
    return UsdGeom.GetStageUpAxis(stage)

def create_framing_camera_in_stage(stage: Usd.Stage, root: Union[Sdf.Path,str], 
                                   name: str = "framingCam", fit: float = 1 ,
                                   width: int = 16, height: int = 9) -> UsdGeom.Camera:
    """
    Adds a camera that frames the whole stage.
    Can be specified to have a different aspect ratio, this will affect the sensor size internally.
    """
    if isinstance(root,str):
        root = Sdf.Path(root)
    # create camera
    camera = create_perspective_camera_in_stage(stage, root, name, width, height)

    # Do prerequisite math so that functions don't have to run these same operations.

    bounds = get_stage_boundingbox(stage)
    bounds_min, bounds_max = bounds.GetMin(), bounds.GetMax()

    z_up = (_stage_up(stage) == "Z")

    distance_to_stage = calculate_stage_distance_to_camera(camera, stage, bounds_min, bounds_max, z_up, fit)

    # setup attributes in camera
    set_camera_clippingplanes_from_stage(camera, stage, bounds_min, bounds_max, z_up, distance_to_stage)

    translation = calculate_camera_position(camera, stage, bounds_min, bounds_max, z_up, distance_to_stage)

    # translate THEN rotate. Translation is always done locally. 
    # If this needs to be switched around, swizzle translation Vec3d.

    camera_apply_translation(camera, translation)

    camera_orient_to_stage_up(camera, stage, z_up)
    
    return camera


def create_perspective_camera_in_stage(stage: Usd.Stage, root: Sdf.Path, 
                                       name: str = "perspectiveCam", width: int = 16, height: int = 9) -> UsdGeom.Camera:
    """
    Creates a camera in the scene with a certain sensor size. 
    Defaults to 16:9 aspect ratio.
    """
    # Calculate aspect ratio. Cast divisor to float to prevent integer division
    aspect_ratio: float = width / float(height) 

    campath = root.AppendPath(name)
    
    camera = UsdGeom.Camera.Define(stage, campath)

    camera.CreateFocusDistanceAttr(168.60936)
    camera.CreateFStopAttr(0)
    
    camera.CreateHorizontalApertureAttr(24 * aspect_ratio)
    camera.CreateHorizontalApertureOffsetAttr(0)
    camera.CreateVerticalApertureAttr(24)
    camera.CreateVerticalApertureOffsetAttr(0)

    camera.CreateProjectionAttr("perspective")

    cam_prim = camera.GetPrim()
    xform_cam = UsdGeom.Xformable(cam_prim)
    xform_cam.ClearXformOpOrder() # Clear out default operation order if there is any. (may not be needed)

    return camera

def camera_orient_to_stage_up(camera: UsdGeom.Camera, stage: Usd.Stage, z_up: bool = None):
    if z_up is None:
        z_up = (_stage_up(stage) == "Z")

    if not z_up:
        return # do nothing when Y is up and all is good and right in the world.

    from pxr.UsdGeom import XformOp

    cam_prim = camera.GetPrim()
    xform_cam = UsdGeom.Xformable(cam_prim)
    xform_cam.AddRotateXOp(XformOp.PrecisionDouble).Set(90)

def camera_apply_translation(camera: UsdGeom.Camera, translation: Gf.Vec3d):
    """
    Apply translation to first found translation operation in
    """
    
    from pxr.UsdGeom import XformOp
    
    cam_prim = camera.GetPrim()
    xform_cam = UsdGeom.Xformable(cam_prim)
    
    translate_op = None
    # check for existing translation operation, if not found, add one to stack.
    for op in xform_cam.GetOrderedXformOps():
        op: XformOp
        if op.GetOpType() == XformOp.TypeTranslate:
            translate_op = op
            break
    else:
        translate_op = xform_cam.AddTranslateOp(XformOp.PrecisionDouble)

    translate_op.Set(translation)

def set_camera_clippingplanes_from_stage(camera: UsdGeom.Camera, stage: Usd.Stage,
                        bounds_min: Gf.Vec3d = None, bounds_max: Gf.Vec3d = None, 
                        z_up: bool = None, distance: float = None):
    """
    Set internal camera clipping plane attributes to fit the stage.
    """   
    # Convenience. Life is short.
    if not bounds_min or not bounds_max:
        boundingbox = get_stage_boundingbox(stage)
        bounds_min, bounds_max = boundingbox.GetMin(), boundingbox.GetMax()
    
    # Explicit None checks for values that can be False or 0
    if z_up is None:
        z_up = (_stage_up(stage) == "Z")

    if distance is None:
        distance = calculate_stage_distance_to_camera(camera, stage, bounds_min, bounds_max, z_up)

    ver_idx = 2 if z_up else 1

    # expand clipping planes out a bit.
    near_clip = max((distance + bounds_min[ver_idx]) * 0.5, 0.0000001)
    far_clip = (distance + bounds_max[ver_idx]) * 2
    clipping_planes = Gf.Vec2f(near_clip, far_clip)
    camera.GetClippingRangeAttr().Set(clipping_planes)

def get_stage_boundingbox(stage: Usd.Stage, time: Usd.TimeCode = Usd.TimeCode.EarliestTime(), 
                          purpose_tokens: list[str] = ["default"]) -> Gf.Range3d:
    """
    Caclulate a stage's bounding box, with optional time and purposes.
    The default for time is the earliest registered TimeCode in the stage's animation.
    The default for purpose tokens is ["default"], 
    valid values are: default, proxy, render, guide.
    """
    bbox_cache = UsdGeom.BBoxCache(time,purpose_tokens)
    stage_root = stage.GetPseudoRoot()
    return bbox_cache.ComputeWorldBound(stage_root).GetBox()

def calculate_camera_position(camera: UsdGeom.Camera, stage: Usd.Stage, bounds_min: Gf.Vec3d = None, 
                              bounds_max: Gf.Vec3d = None, z_up: bool = None, distance: float = None) -> Gf.Vec3d:
    """
    Calculate the world position for the camera based off of the size of the stage and the camera attributes.
    Bounds and distance can be calculated beforehand so 
    """
    # Convenience. Life is short.
    if not bounds_min or not bounds_max:
        boundingbox = get_stage_boundingbox(stage)
        bounds_min, bounds_max = boundingbox.GetMin(), boundingbox.GetMax()
    
    # Explicit None checks for values that can be False or 0
    if z_up is None:
        z_up = (_stage_up(stage) == "Z")

    if distance is None:
        distance = calculate_stage_distance_to_camera(camera, stage, bounds_min, bounds_max, z_up)

    # Suppose a scene with a cone,
    #             ..
    #          ../  |    /\
    #  O O    /     |   /  \
    # [cam]<| ------|  /I am\
    #         \..   | / cone \
    #            \..|/ fear me\
    #               ^       
    #               |- The focus plane will be here, at the closest depth of the bounds
    #                  of the scene the camera is pointed at.
    #
    # The center of the camera will be positioned at the center of the vertical and horizontal axis, 
    # (Y and X respectively, assuming y up)
    # and positioned back along the  with the calculated frustrum-filling distance along the depth axis,
    # (Z, assuming y up).
    
    centroid = (bounds_min + bounds_max) / 2

    if z_up:
        camera_position = Gf.Vec3d(centroid[0], bounds_min[1]-distance, centroid[2]) 
    else:
        camera_position = Gf.Vec3d(centroid[0], centroid[1], bounds_max[2] + distance)

    return camera_position

def calculate_stage_distance_to_camera(camera: UsdGeom.Camera, stage: Usd.Stage, 
                                       bounds_min: Gf.Vec3d = None, bounds_max: Gf.Vec3d = None, 
                                       z_up: bool = None, fit: float = 1) -> float:
    """
    Calculates a distance from the centroid of the stage that would allow a camera to frame it perfectly.
    Returns distance in stage units.
    """
    # Convenience. Life is short.
    if not bounds_min or not bounds_max:
        boundingbox = get_stage_boundingbox(stage)
        bounds_min, bounds_max = boundingbox.GetMin(), boundingbox.GetMax()
    
    if z_up is None:
        z_up = (_stage_up(stage) == "Z")

    focal_length = camera.GetFocalLengthAttr().Get()
    hor_aperture = camera.GetHorizontalApertureAttr().Get()
    ver_aperture = camera.GetVerticalApertureAttr().Get()

    ver_idx = 2 if z_up else 1

    # get size of bounds
    d_hor = bounds_max[0] - bounds_min[0]
    d_ver = bounds_max[ver_idx] - bounds_min[ver_idx]

    fov_hor, fov_ver = calculate_field_of_view(focal_length,hor_aperture), calculate_field_of_view(focal_length,ver_aperture)
    
    # calculate capture size. the sensor size was given in mm (24 mm sensor) 
    # so we need to pass in cm units from the scene as mm units for correct calculation. 
    capturesize_hor = calculate_perspective_distance(d_hor * 10, fov_hor, fit)
    capturesize_ver = calculate_perspective_distance(d_ver * 10, fov_ver, fit)

    # return units back to cm on return
    return max(capturesize_hor, capturesize_ver) / 10

def calculate_field_of_view(focal_length, sensor_size) -> float:
    # Math : https://sdk-forum.dji.net/hc/en-us/articles/11317874071065-How-to-calculate-the-FoV-of-the-camera-lens-
    """
    Calculates field of view for 1 measurement of the sensor size (width or height)
    Returns field of view in radians. 
    """
    # With H being the full lens height, we need to divide H by 2
    #                    H / 2
    # AFOV = 2 * atan(  -------  )
    #                      f
    # multiply by 2 because we're only getting the angle towards 1 half of the lens from the center,
    # getting the apex angle of an isosceles triangle.
    # 
    # This expression is rewritten as 2 * atan(h * (2 * f)), this is mathematically the same.
    return 2 * math.atan(sensor_size / (2 * focal_length))

def calculate_perspective_distance(subject_size, field_of_view, fit: float = 1) -> float:
    """
    Calculate appropriate distance towards the subject, so it can fill the view.
    Essentially, the inverse of calculate_field_of_view.
    """
    # We're treating the subject_size as if it was the size of a lens here,
    # and calculating a focal length that would match it.
    #
    # Keep in mind that we're drawing a right triangle towards the center of the subject,
    # that is why we are dividing the size in half.
    # 
    # The field of view is also divided in half, because the whole FOV represents the apex
    # angle of the isosceles traingle.
    subject_size *= fit
    return (subject_size / 2) / math.tan(field_of_view / 2)