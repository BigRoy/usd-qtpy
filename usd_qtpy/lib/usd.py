from collections import defaultdict

from pxr import Usd, Plug, Tf, Sdf
import logging


LIST_ATTRS = ['addedItems', 'appendedItems', 'deletedItems', 'explicitItems',
              'orderedItems', 'prependedItems']

NICE_PLUGIN_TYPE_NAMES = {
    "usdGeom": "Geometry",
    "usdLux": "Lighting",
    "mayaUsd_Schemas": "Maya Reference",
    "usdMedia": "Media",
    "usdRender": "Render",
    "usdRi": "RenderMan",
    "usdShade": "Shading",
    "usdSkel": "Skeleton",
    "usdUI": "UI",
    "usdVol": "Volumes",
    "usdProc": "Procedural",
    "usdPhysics": "Physics",
    "usdArnold": "Arnold",
    # Skip legacy AL schemas
    "AL_USDMayaSchemasTest": "",
    "AL_USDMayaSchemas": "",
}


def get_prim_types_by_group() -> dict:
    """Return all registered concrete type names by nice plug-in grouping.

    Returns:
        dict: Schema type names grouped by plug-in name.

    """

    plug_reg = Plug.Registry()
    schema_reg = Usd.SchemaRegistry

    # Get schema types by plug-in group
    types_by_group = defaultdict(list)
    for t in plug_reg.GetAllDerivedTypes(Tf.Type.FindByName("UsdSchemaBase")):
        if not schema_reg.IsConcrete(t):
            continue

        plugin = plug_reg.GetPluginForType(t)
        if not plugin:
            continue

        plugin_name = plugin.name
        plugin_name = NICE_PLUGIN_TYPE_NAMES.get(plugin_name, plugin_name)

        # We don't list empty names. This allows hiding certain plugins too.
        if not plugin_name:
            continue

        type_name = schema_reg.GetConcreteSchemaTypeName(t)
        types_by_group[plugin_name].append(type_name)

    return {
        key: sorted(value) for key, value in sorted(types_by_group.items())
    }


def iter_prim_type_names(prim):
    """Yield all concrete schema type names for the prim"""
    if not prim.IsValid():
        return

    if not prim.GetTypeName():
        # unknown type
        return

    type_info = prim.GetPrimTypeInfo()
    schema_type = type_info.GetSchemaType()
    for t in schema_type.GetAllAncestorTypes():
        yield Usd.SchemaRegistry.GetConcreteSchemaTypeName(t) or t.typeName


def repath_properties(layer, old_path, new_path):
    """Re-path property relationship targets and attribute connections.

    This will replace any relationship or connections from old path
    to new path by replacing start of any path that matches the new path.

    Args:
        layer (Sdf.Layer): Layer to move prim spec path.
        old_path (Union[Sdf.Path, str]): Source path to move from.
        new_path (Union[Sdf.Path, str]): Destination path to move to.

    Returns:
        bool: Whether any re-pathing occurred for the given paths.

    """

    old_path_str = str(old_path)
    state = {"changes": False}

    def replace_in_list(spec_list):
        """Replace paths in SdfTargetProxy or SdfConnectionsProxy"""
        for attr in LIST_ATTRS:
            entries = getattr(spec_list, attr)
            for i, entry in enumerate(entries):
                entry_str = str(entry)
                if entry == old_path or entry_str.startswith(
                        old_path_str + "/"):
                    # Repath
                    entries[i] = Sdf.Path(
                        str(new_path) + entry_str[len(old_path_str):])
                    state["changes"] = True

    def repath(path):
        spec = layer.GetObjectAtPath(path)
        if isinstance(spec, Sdf.RelationshipSpec):
            replace_in_list(spec.targetPathList)
        if isinstance(spec, Sdf.AttributeSpec):
            replace_in_list(spec.connectionPathList)

    # Repath any relationship pointing to this src prim path
    layer.Traverse("/", repath)

    return state["changes"]


def move_prim_spec(layer, src_prim_path, dest_prim_path):
    """Move a PrimSpec and repath connections.

    Note that the parent path of the destination must exist, otherwise the
    namespace edit to that path will fail.

    Args:
        layer (Sdf.Layer): Layer to move prim spec path.
        src_prim_path (Union[Sdf.Path, str]): Source path to move from.
        dest_prim_path (Union[Sdf.Path, str]): Destination path to move to.

    Returns:
        bool: Whether the move was successful

    """

    src_prim_path = Sdf.Path(src_prim_path)
    dest_prim_path = Sdf.Path(dest_prim_path)
    if src_prim_path == dest_prim_path:
        return

    src_name = src_prim_path.name
    dest_parent = dest_prim_path.GetParentPath()
    dest_name = dest_prim_path.name

    with Sdf.ChangeBlock():
        if dest_parent == src_prim_path.GetParentPath():
            # Rename, keep parent
            edit = Sdf.NamespaceEdit.Rename(
                src_prim_path,
                dest_name
            )

        else:
            if src_name == dest_name:
                # Reparent, keep name
                edit = Sdf.NamespaceEdit.Reparent(
                    src_prim_path,
                    dest_parent,
                    -1
                )

            else:
                # Reparent and rename
                edit = Sdf.NamespaceEdit.ReparentAndRename(
                    src_prim_path,
                    dest_parent,
                    dest_name,
                    -1
                )

        batch_edit = Sdf.BatchNamespaceEdit()
        batch_edit.Add(edit)
        if not layer.Apply(batch_edit):
            logging.warning("Failed prim spec move: %s -> %s",
                            src_prim_path,
                            dest_prim_path)
            return False

        repath_properties(layer, src_prim_path, dest_prim_path)

    return True


def rename_prim(prim: Usd.Prim, new_name: str) -> bool:
    if prim.GetName() == new_name:
        return True

    prim_path = prim.GetPath()
    new_prim_path = prim_path.ReplaceName(new_name)

    # We want to map the path to the current edit target of its stage so that
    # if the user is renaming a prim in an edit target within a variant set,
    # that we rename that particular opinion. However, we only do that if the
    # source prim path existed in the edit target otherwise we will edit it
    # on the layer regularly
    stage = prim.GetStage()
    edit_target = stage.GetEditTarget()
    remapped_prim_path = edit_target.MapToSpecPath(prim_path)
    if (
            prim_path != remapped_prim_path
    ):
        logging.debug("Remapping prim path to within edit target: %s",
                      remapped_prim_path)
        prim_path = remapped_prim_path
        new_prim_path = edit_target.MapToSpecPath(new_prim_path)

    stage = prim.GetStage()
    with Sdf.ChangeBlock():
        for layer in stage.GetLayerStack():
            if layer.GetPrimAtPath(prim_path):
                logging.debug("Moving prim in layer: %s", layer)
                move_prim_spec(layer,
                               src_prim_path=prim_path,
                               dest_prim_path=new_prim_path)

    # We deactivate the parent if renaming within a variant set edit target
    # because of known crash/bug:
    #   https://github.com/PixarAnimationStudios/OpenUSD/issues/2844
    if new_prim_path.ContainsPrimVariantSelection():
        prim = stage.GetPrimAtPath(new_prim_path.StripAllVariantSelections())
        if prim and prim.IsValid() and prim.GetPrimIndex() is None:
            parent = prim.GetParent()
            parent.SetActive(False)
            parent.SetActive(True)

    return True


def unique_name(stage: Usd.Stage, prim_path: Sdf.Path) -> Sdf.Path:
    """Return Sdf.Path that is unique under the current composed stage.

    Note that this technically does not ensure that the Sdf.Path does not
    exist in any of the layers, e.g. it could be defined within a currently
    unselected variant or a muted layer.

    """
    src = prim_path.pathString.rstrip("123456789")
    i = 1
    while stage.GetPrimAtPath(prim_path):
        prim_path = Sdf.Path(f"{src}{i}")
        i += 1
    return prim_path


def parent_prims(prims: list[Usd.Prim],
                 new_parent: Sdf.Path,
                 layers: list[Sdf.Layer] = None) -> bool:
    """Move Prims to a new parent in given layers.

    Note:
        This will only reparent prims to the new parent if the new parent
        exists in the layer.

    Arguments:
        prims (list[Usd.Prim]): The prims to move the new parent
        new_parent (Sdf.Path): Parent path to be moved to.
        layers (list[Sdf.Layer]): The layers to apply the reparenting
            in. If None are provided the stage's full layer stack will be used.

    """
    if not prims:
        return False

    # Only consider prims not already parented to the new parent
    prims = [
        prim for prim in prims if prim.GetPath().GetParentPath() != new_parent
    ]
    if not prims:
        return False

    if layers is None:
        stage = prims[0].GetStage()
        layers = stage.GetLayerStack()

    edit_batch = Sdf.BatchNamespaceEdit()
    for prim in prims:
        edit = Sdf.NamespaceEdit.Reparent(
            prim.GetPath(),
            new_parent,
            -1
        )
        edit_batch.Add(edit)

    any_edits_made = False
    with Sdf.ChangeBlock():
        for layer in layers:
            applied = layer.Apply(edit_batch)
            if applied:
                any_edits_made = True
                for edit in edit_batch.edits:
                    repath_properties(layer,
                                      edit.currentPath,
                                      edit.newPath)
    return any_edits_made


def remove_spec(spec):
    """Remove Sdf.Spec authored opinion."""
    if spec.expired:
        return

    if isinstance(spec, Sdf.PrimSpec):
        # PrimSpec
        parent = spec.nameParent
        if parent:
            view = parent.nameChildren
        else:
            # Assume PrimSpec is root prim
            view = spec.layer.rootPrims
        del view[spec.name]

    elif isinstance(spec, Sdf.PropertySpec):
        # Relationship and Attribute specs
        del spec.owner.properties[spec.name]

    elif isinstance(spec, Sdf.VariantSetSpec):
        # Owner is Sdf.PrimSpec (or can also be Sdf.VariantSpec)
        del spec.owner.variantSets[spec.name]

    elif isinstance(spec, Sdf.VariantSpec):
        # Owner is Sdf.VariantSetSpec
        spec.owner.RemoveVariant(spec)

    else:
        raise TypeError(f"Unsupported spec type: {spec}")
