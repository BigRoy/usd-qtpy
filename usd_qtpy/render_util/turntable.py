# Turn table utilities.
# oh how the turns have tabled
from typing import Union

from pxr import Usd, UsdGeom
from pxr import Sdf, Gf
from qtpy import QtCore

from . import framing_camera
from ..lib import usd
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
    if isinstance(path, str):
        path = Sdf.Path(path)
    
    path = path.AppendPath(name)

    z_up = (framing_camera.get_stage_up(stage) == "Z")
    
    bounds = framing_camera.get_stage_boundingbox(stage)
    centroid = (bounds.GetMin() + bounds.GetMax()) / 2

    xform = UsdGeom.Xform.Define(stage, path)

    # Translate first, then add spin turntable
    if z_up:
        translate = Gf.Vec3d(centroid[0], centroid[1], 0)  # Z axis = floor normal
    else:
        translate = Gf.Vec3d(centroid[0], 0, centroid[2])  # Y axis = floor normal

    xform.AddTranslateOp().Set(translate)
    add_turntable_spin_op(xform, length, frame_start, repeats, z_up)

    return xform


def create_turntable_camera(stage: Usd.Stage,
                            root: Union[Sdf.Path, str],
                            name: str = "turntableCam",
                            fit: float = 1.1,
                            width: int = 16,
                            height: int = 9,
                            length: int = 100,
                            frame_start: int = 0) -> UsdGeom.Camera:
    """
    Create a stage framing perspective camera, within an animated, rotating Xform.
    """
    if isinstance(root, str):
        root = Sdf.Path(root)

    xform = create_turntable_xform(
        stage, root, length=length, frame_start=frame_start
    )
    xform_path = xform.GetPath()

    cam = framing_camera.create_framing_camera_in_stage(
        stage, xform_path, name, fit, width, height, True
    )

    return cam


def add_turntable_spin_op(prim: Usd.Prim,
                          length: int = 100,
                          frame_start: int = 0,
                          repeats: int = 1,
                          z_up: bool = False) -> UsdGeom.XformOp:
    """Add Rotate XformOp with 360 degrees turntable rotation keys to prim"""
    # TODO: Maybe check for existing operations before blatantly adding one.
    xformable = UsdGeom.Xformable(prim)
    if z_up:
        spin_op = xformable.AddRotateZOp()
    else:
        spin_op = xformable.AddRotateYOp()

    spin_op.Set(time=frame_start, value=0)

    # Avoid having the last frame the same as the first frame so the cycle
    # works out nicely over the full lenght. As such, we remove one step
    frame_end = frame_start + (length * repeats) - 1
    step_per_frame = 360 / length
    spin_op.Set(time=frame_end, value=(repeats * 360) - step_per_frame)

    return spin_op


def turntable_from_file(stage: Usd.Stage, layer_editor: LayerTreeWidget):
    """
    WARNING, THIS FUNCTION IS UNDER CONSTRUCTION
    """
    
    # WARNING: HARDCODED for now
    
    if index := layer_editor.view.selectedIndexes():
        layertree_index = index[0]
    else:
        layertree_index = layer_editor.view.indexAt(QtCore.QPoint(0, 0))
    
    layer: Sdf.Layer = layertree_index.data(LayerStackModel.LayerRole)

    if not layer:
        return

    filename = R"X:\VAULT_PROJECTS\COLORBLEED\Kitchen_set\Turntable.usda"
    kitchenfile = R"X:\VAULT_PROJECTS\COLORBLEED\Kitchen_set\Kitchen_set.usd"
    # layer.subLayerPaths.append(filename)

    # this needs to be done the other way around
    # load turntable stage,
    # sublayer scene
    # parent scene to /turntable/parent
    # DOESNT WORK ^

    # NEW PLAN: Use references
    # Save stage somewhere in a temporary folder,
    # create a new stage, add turntable preset 

    #subject_prim = stage.GetPrimAtPath("/Kitchen_set")
    #print(subject_prim)
    #goal_path = Sdf.Path("/turntable")

    #parent_prim = stage.GetPrimAtPath(goal_path)
    #print(parent_prim)
    
    ## parenting the sublayered scene to base scene (unsuccesfully)
    #usd.parent_prims([parent_prim],Sdf.Path("/Kitchen_set"))

    # Create a stage in memory, then add a reference to the turntable first.
    ttable_stage = Usd.Stage.CreateInMemory()

    turntable_ref = ttable_stage.OverridePrim("/turntable_reference")
    turntable_ref.GetReferences().AddReference(filename)
    

    # TODO: check if parent prim and is of type  is actually there
    # Create a reference within the parent of the 
    subject_ref = ttable_stage.OverridePrim("/turntable_reference/parent/subject_reference")
    subject_ref.GetReferences().AddReference(kitchenfile)

    print(ttable_stage.GetRootLayer().ExportToString())
    
    
    ttable_stage.Export(R"X:\VAULT_PROJECTS\COLORBLEED\test_turntable.usd")