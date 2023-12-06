# Turn table utilities.

from typing import Union
import os
import math

from pxr import Usd, UsdGeom
from pxr import Sdf, Gf
from qtpy import QtCore

from . import framing_camera, playblast
from ..layer_editor import LayerTreeWidget, LayerStackModel

def create_turntable_xform(stage: Usd.Stage, 
                           path: Union[Sdf.Path, str], 
                           name: str = "turntableXform",
                           length: int = 100, 
                           frame_start: int = 0, 
                           repeats: int = 1) -> UsdGeom.Xform:
    """
    Creates a turntable Xform that contains animation spinning around the up axis, in the center floor of the stage.
    We repeat the entire duration when repeats are given as an arguement.
    A length of 100 with 3 repeats will result in a 300 frame long sequence
    """
    from pxr.UsdGeom import XformOp
    
    if isinstance(path,str):
        path = Sdf.Path(path)
    
    path = path.AppendPath(name)

    is_z_up = framing_camera.get_stage_up(stage) == "Z"
    
    bounds = framing_camera.get_stage_boundingbox(stage)
    centroid = bounds.GetMidpoint()

    xform = UsdGeom.Xform.Define(stage, path)

    if is_z_up:
        translate = Gf.Vec3d(centroid[0], centroid[1], 0) # Z axis = floor normal
    else:
        translate = Gf.Vec3d(centroid[0], 0, centroid[2]) # Y axis = floor normal

    # Move to centroid of bounds, rotate, move back to origin
    xform.AddTranslateOp(XformOp.PrecisionDouble,"rotPivot").Set(translate)
    add_turntable_spin_op(xform, length, frame_start, repeats, is_z_up)
    xform.AddTranslateOp(XformOp.PrecisionDouble,"rotPivot",isInverseOp=True)
    
    return xform


def create_turntable_camera(stage: Usd.Stage, root: Union[Sdf.Path,str], 
                            name: str = "turntableCam", fit: float = 1.1,
                            width: int = 16, height: int = 9, 
                            length: int = 100, frame_start: int = 0) -> UsdGeom.Camera:
    """
    Creates a complete setup with a stage framing perspective camera, within an animated, rotating Xform.
    """
    if isinstance(root,str):
        root = Sdf.Path(root)

    xform = create_turntable_xform(
        stage, root, length=length, frame_start=frame_start
    )
    xform_path = xform.GetPath()

    cam = framing_camera.create_framing_camera_in_stage(
        stage, xform_path, name, fit, width, height, True)

    return cam

def add_turntable_spin_op(xformable: UsdGeom.Xformable,
                          length: int = 100,
                          frame_start: int = 0,
                          repeats: int = 1,
                          is_z_up: bool = False) -> UsdGeom.XformOp:
    """Add Rotate XformOp with 360 degrees turntable rotation keys to prim"""
    from pxr.UsdGeom import XformOp
    # TODO: Maybe check for existing operations before blatantly adding one.
    if is_z_up:
        spin_op = xformable.AddRotateZOp(XformOp.PrecisionDouble)
    else:
        spin_op = xformable.AddRotateYOp(XformOp.PrecisionDouble)

    spin_op.Set(time=frame_start, value=0)

    # Avoid having the last frame the same as the first frame so the cycle
    # works out nicely over the full length. As such, we remove one step
    frame_end = frame_start + (length * repeats) - 1
    step_per_frame = 360 / length
    spin_op.Set(time=frame_end, value=(repeats * 360) - step_per_frame)

    return spin_op

def turntable_from_file(stage: Usd.Stage,
                        turntable_filename: str, 
                        export_path: str):
    """
    #### STILL UNDER CONSTRUCTION

    Generates a turntable from a preset USD file, not unlike Prism.
    
    The turntable must have the following structure:
    - /turntable <- default primitive Xform
    - /turntable/parent <- Xform that rotates
    - a camera somewhere under /turntable/
    
    Optional:
    - /turntable/bounds/bound_box <- a geometry primitive 
                                     that scales input to fit itself.
    """

    # TODO: Infer frame range from turntable stage.

    # collect info about subject
    subject_zup = framing_camera.get_stage_up(stage) == "Z"
    
    # export subject
    turntable_filename = R"X:\VAULT_PROJECTS\COLORBLEED\Kitchen_set\Turntable_2.usda"
    subject_filename = R"./temp/subject.usda"
    
    # make temporary folder to cache current subject session to.
    if not os.path.isdir("./temp"):
        os.mkdir("./temp")

    stage.Export(subject_filename)

    # create scene in memory
    ttable_stage = Usd.Stage.CreateInMemory()

    print(UsdGeom.GetStageUpAxis(ttable_stage))

    turntable_ref = ttable_stage.OverridePrim("/turntable_reference")
    turntable_ref.GetReferences().AddReference(turntable_filename)

    # conform turntable to Y up
    turntable_zup = file_is_zup(turntable_filename)

    if turntable_zup:
        turntable_ref_xformable = UsdGeom.Xformable(turntable_ref)
        turntable_ref_xformable.AddRotateXOp().Set(-90)

    # check if required prims are actually there
    turntable_parent_prim = ttable_stage\
                            .GetPrimAtPath("/turntable_reference/parent")
    
    turntable_camera = next(playblast.iter_stage_cameras(ttable_stage),None)

    if not turntable_parent_prim.IsValid() or not turntable_camera:
        missing = []
        noparent = not turntable_parent_prim.IsValid()
        nocamera = not turntable_camera

        if noparent:
            missing.append("Missing: /turntable/parent")
        if nocamera:
            missing.append("Missing: Usd Camera")

        raise RuntimeError("Turntable file doesn't have all"
                           " nessecary components.\n" + "\n".join(missing))

    # Create a reference within the parent of the new turntable stage
    # References do need xformables created.

    ref_adress ="/turntable_reference/parent/subject_reference"
    subject_ref = ttable_stage.OverridePrim(ref_adress)
    subject_ref.GetReferences().AddReference(subject_filename)
    subject_prim = subject_ref.GetPrim()

    subject_ref_xformable = UsdGeom.Xformable(subject_ref)

    if subject_zup:
        subject_ref_xformable.AddRotateXOp().Set(-90)

    # get bbox of subject and center stage
    subject_nofit_bbox = UsdGeom.BBoxCache(Usd.TimeCode.EarliestTime(), 
                                           ["default"])\
                                           .ComputeWorldBound(subject_prim)\
                                           .GetBox()
    
    subject_nofit_size = subject_nofit_bbox.GetSize()

    # Get goal geometry boundingbox if it exists, and fit primitive to it
    
    bbox_prim = ttable_stage\
                .GetPrimAtPath("/turntable_reference/bounds/bound_box")
    
    if bbox_prim.IsValid():
        goal_bbox = UsdGeom.BBoxCache(Usd.TimeCode.EarliestTime(), ["default"])\
                                      .ComputeWorldBound(bbox_prim)\
                                      .GetBox()
        goal_size = goal_bbox.GetSize()
        max_sizediff = 0
        for index in range(3):
            max_sizediff = max(math.fabs(\
                               goal_size[index] / subject_nofit_size[index]), 
                               max_sizediff)

        # SCALE FIRST!
        subject_ref_xformable.AddScaleOp(UsdGeom.XformOp.PrecisionDouble)\
                             .Set(Gf.Vec3d(max_sizediff))

    # get bbox of subject and center stage
    subject_bbox = UsdGeom.BBoxCache(Usd.TimeCode.EarliestTime(),
                                    ["default"])\
                                    .ComputeWorldBound(subject_prim).GetBox()
    
    subject_bounds_min = subject_bbox.GetMin()
    subject_centroid = subject_bbox.GetMidpoint()

    # center geometry.
    if subject_zup:
        subject_center_translate = Gf.Vec3d(-subject_centroid[2], 
                                            subject_centroid[0], 
                                            -subject_bounds_min[1])
    else:
        subject_center_translate = Gf.Vec3d(-subject_centroid[0], 
                                            -subject_bounds_min[1], 
                                            -subject_centroid[2])
    
    subject_ref_xformable.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble)\
                         .Set(subject_center_translate)
    
    print(ttable_stage.GetRootLayer().ExportToString())
    ttable_stage.Export(R"./temp/test_turntable_fit.usd")


def file_is_zup(path: str) -> bool:
    stage = Usd.Stage.CreateInMemory(path)
    return framing_camera.get_stage_up(stage) == "Z"
    

def layer_from_layereditor(layer_editor:
                           LayerTreeWidget) -> Union[Sdf.Layer,None]:
    """
    Get current selected layer in layer view, 
    if none selected, return top of the stack.
    """
    
    if index := layer_editor.view.selectedIndexes():
        layertree_index = index[0]
    else:
        layertree_index = layer_editor.view.indexAt(QtCore.QPoint(0, 0))
    
    layer: Sdf.Layer = layertree_index.data(LayerStackModel.LayerRole)

    if not layer:
        return