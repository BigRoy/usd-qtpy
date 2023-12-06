# Turn table utilities.
# oh how the turns have tabled
from typing import Union
import os

from pxr import Usd, UsdGeom
from pxr import Sdf, Gf
from qtpy import QtCore

from . import framing_camera, playblast
from ..lib import usd
from ..layer_editor import LayerTreeWidget, LayerStackModel

def create_turntable_xform(stage: Usd.Stage, path: Union[Sdf.Path, str], name: str = "turntableXform",
                           length: int = 100, frame_start: int = 0, repeats: int = 1) -> UsdGeom.Xform:
    """
    Creates a turntable Xform that contains animation spinning around the up axis, in the center floor of the stage.
    We repeat the entire duration when repeats are given as an arguement.
    A length of 100 with 3 repeats will result in a 300 frame long sequence
    """
    from pxr.UsdGeom import XformOp

    frame_range = (frame_start, frame_start+(length-1))
    
    if isinstance(path,str):
        path = Sdf.Path(path)
    
    path = path.AppendPath(name)

    z_up = (framing_camera._stage_up(stage) == "Z")
    
    bounds = framing_camera.get_stage_boundingbox(stage)
    centroid = (bounds.GetMin() + bounds.GetMax()) / 2

    xform = UsdGeom.Xform.Define(stage, path)
    
    spinop = None
    translateop = xform.AddTranslateOp(XformOp.PrecisionDouble)

    if z_up:
        translateop.Set(Gf.Vec3d(centroid[0],centroid[1],0)) # Z axis = floor normal
        spinop = xform.AddRotateZOp(XformOp.PrecisionDouble)
    else:
        translateop.Set(Gf.Vec3d(centroid[0],0,centroid[2])) # Y axis = floor normal
        spinop = xform.AddRotateYOp(XformOp.PrecisionDouble)

    # add in rotation frames at specified times
    for i in range(repeats):
        frame_range = (frame_range[0] + (length * i), frame_range[1] + (length * i))
        spinop.Set(time=frame_range[0], value = 0)
        spinop.Set(time=frame_range[1], value = ((length - 1) / float(length)) * 360)

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

    xform = create_turntable_xform(stage,root,length=length,frame_start=frame_start)
    xform_path = xform.GetPath()

    cam = framing_camera.create_framing_camera_in_stage(stage,xform_path,name,fit,width,height,True)

    return cam


def turn_tableize_prim(stage: Usd.Stage, path: Union[Sdf.Path,str], 
                       length: int = 100, frame_start: int = 0, repeats: int = 1):
    """
    Insert turn table keys into a primitive of your choice!
    """
    from pxr.UsdGeom import XformOp

    if isinstance(path,str):
        path = Sdf.Path(path)

    prim = stage.GetPrimAtPath(path)

    z_up = (framing_camera._stage_up(stage) == "Z")

    xformable = UsdGeom.Xformable(prim)
    spinop = None

    # TODO: Maybe check for existing operations before blatantly adding one.
    if z_up:
        spinop = xformable.AddRotateZOp(XformOp.PrecisionDouble)
    else:
        spinop = xformable.AddRotateYOp(XformOp.PrecisionDouble)

    frame_range = (frame_start, frame_start+(length-1))

    # add in rotation frames at specified times
    for i in range(repeats):
        frame_range = (frame_range[0] + (length * i), frame_range[1] + (length * i))
        spinop.Set(time=frame_range[0], value = 0)
        spinop.Set(time=frame_range[1], value = ((length - 1) / float(length)) * 360)

    
# def _xform_parent_test(stage: Usd.Stage, name: str = "containerXform"):
#     """Works, Ready to be deprecated"""
# 
#     from_path = Sdf.Path("/Kitchen_set") # hardcoded for now
#     to_path = Sdf.Path(f"/{name}")
# 
#     child_prim = stage.GetPrimAtPath(from_path)
# 
#     usd.parent_prims([child_prim],to_path)


def turntable_from_file(stage: Usd.Stage):
    """
    WARNING, THIS FUNCTION IS UNDER CONSTRUCTION
    """
    # NEW PLAN: Use references
    # Save stage somewhere in a temporary folder,
    # create a new stage, add turntable preset 

    # collect info about subject
    subject_bbox = framing_camera.get_stage_boundingbox(stage)
    subject_zup = framing_camera._stage_up(stage) == "Z"
    
    # export subject
    turntable_filename = R"X:\VAULT_PROJECTS\COLORBLEED\Kitchen_set\Turntable_2.usda"
    subject_filename = R"./temp/subject.usda"
    
    # make temporary folder to write current subject session to.
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
    turntable_parent_prim = ttable_stage.GetPrimAtPath("/turntable/parent")
    turntable_camera = next(playblast.iter_stage_cameras(ttable_stage),None)

    if not turntable_parent_prim.IsValid() or not turntable_camera:
        missing = []
        noparent = not turntable_parent_prim.IsValid()
        nocamera = not turntable_camera

        if noparent:
            missing.append("Missing: /turntable/parent")
        if nocamera:
            missing.append("Missing: Usd Camera")

        raise RuntimeError("Turntable file doesn't have all nessecary components.\n" + "\n".join(missing))

    # Create a reference within the parent of the new turntable stage
    subject_ref = ttable_stage.OverridePrim("/turntable_reference/parent/subject_reference")
    subject_ref.GetReferences().AddReference(subject_filename)

    print(ttable_stage.GetRootLayer().ExportToString())

    # Get goal geometry boundingbox if it exists, and fit primitive to it
    
    bbox_prim = ttable_stage.GetPrimAtPath("/turntable_reference/bounds/bound_box")
    if bbox_prim.IsValid():
        goal_bbox = UsdGeom.BBoxCache(Usd.TimeCode.EarliestTime(),["default"]).ComputeWorldBound(bbox_prim).GetBox()

    ttable_stage.Export(R"X:\VAULT_PROJECTS\COLORBLEED\test_turntable.usd")


def file_is_zup(path: str) -> bool:
    stage = Usd.Stage.CreateNew(path)
    return framing_camera._stage_up(stage) == "Z"
    

def layer_from_layereditor(layer_editor: LayerTreeWidget) -> Union[Sdf.Layer,None]:
    """
    Get current selected layer in layer view, if none selected, return top of the stack.
    """
    
    if index := layer_editor.view.selectedIndexes():
        layertree_index = index[0]
    else:
        layertree_index = layer_editor.view.indexAt(QtCore.QPoint(0,0))
    
    layer: Sdf.Layer = layertree_index.data(LayerStackModel.LayerRole)

    if not layer:
        return