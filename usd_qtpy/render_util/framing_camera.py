# Generates Stage framing camera.
# heavy inspiration taken from: 
# https://github.com/beersandrew/assets/tree/1df93f4da686e9040093027df1e42ff9ea694866/scripts/thumbnail-generator

import logging
from typing import Union
from collections.abc import Generator
import math

from qtpy import QtCore
from pxr import Usd, UsdGeom
from pxr import UsdAppUtils
from pxr import Tf, Sdf, Gf

def _stage_up(stage: Usd.Stage) -> str:
    return UsdGeom.GetStageUpAxis(stage)

def create_framing_camera_in_stage(stage: Usd.Stage, root: Sdf.Path, 
                                   name: str = "framingCam", width: int = 16, height: int = 9) -> UsdGeom.Camera:
    ...


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

    return camera

def get_stage_boundingbox(stage: Usd.Stage, time: Usd.TimeCode = Usd.TimeCode.EarliestTime(), 
                          purpose_tokens: list[str] = ["default"]) -> Gf.Range3d:
    """
    Caclulate a stage's bounding box, with optional time and purposes.
    The default for time is the earliest registered TimeCode in the stage's animation.
    The default for purpose tokens is ["default"], valid values are: default, proxy, render, guide.
    """
    bbox_cache = UsdGeom.BBoxCache(time,purpose_tokens)
    stage_root = stage.GetPseudoRoot()
    return bbox_cache.ComputeWorldBound(stage_root).GetBox()

def set_camera_clippingplanes_from_stage(camera: UsdGeom.Camera, stage: Usd.Stage,
                        bounds_min: Gf.Vec3d = None, bounds_max: Gf.Vec3d = None, z_up: bool = None):
    """
    Set internal camera clipping plane attributes to fit the stage.
    """   
    # Convenience. Life is short.
    if not bounds_min or not bounds_max:
        boundingbox = get_stage_boundingbox(stage)
        bounds_min, bounds_max = boundingbox.GetMin(), boundingbox.GetMax()
    
    if z_up is None:
        z_up = (_stage_up(stage) == "Z")

    distance = calculate_stage_distance_to_camera(camera, stage, bounds_min, bounds_max, z_up)

    ver_idx = 2 if z_up else 1

    near_clip = max((distance + bounds_min[ver_idx]) * 0.5, 0.0000001)
    far_clip = (distance + bounds_max[ver_idx]) * 2
    clipping_planes = Gf.Vec2f(near_clip, far_clip)
    camera.GetClippingRangeAttr().Set(clipping_planes)

def calculate_stage_distance_to_camera(camera: UsdGeom.Camera, stage: Usd.Stage, 
                                       bounds_min: Gf.Vec3d = None, bounds_max: Gf.Vec3d = None, z_up: bool = None) -> float:
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
    capturesize_hor = calculate_perspective_distance(d_hor * 10, fov_hor)
    capturesize_ver = calculate_perspective_distance(d_ver * 10, fov_ver)

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

def calculate_perspective_distance(subject_size, field_of_view) -> float:
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

    return (subject_size / 2) / math.tan(field_of_view / 2)