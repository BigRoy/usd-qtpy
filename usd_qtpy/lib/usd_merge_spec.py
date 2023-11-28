from typing import Union
from pxr import Sdf

from .qt import report_error


@report_error
def should_copy_value_fn(
        spec_type: Sdf.SpecType,
        field: str,
        src_layer: Sdf.Layer,
        src_path: Sdf.Path,
        field_in_src: bool,
        dest_layer: Sdf.Layer,
        dest_path: Sdf.Path,
        field_in_dest: bool
) -> Union[bool, tuple[bool, object]]:
    if field_in_dest and field_in_src:
        if field == "specifier":
            # Do not downgrade specifier to Over but do upgrade to Def
            # We only copy "SpecifierDef"
            value = src_layer.GetObjectAtPath(src_path).GetInfo(field)
            if value == Sdf.SpecifierOver or value == Sdf.SpecifierClass:
                return False
            else:
                return True
        elif field == "typeName":
            # Only override empty type name
            existing_value = dest_layer.GetObjectAtPath(dest_path).GetInfo(
                field)
            return not existing_value

        # TODO: For xform operations merge them together?
        # TODO: For payloads/references merge them together?

    return True


@report_error
def should_copy_children_fn(
        children_field: str,
        src_layer: Sdf.Layer,
        src_path: Sdf.Path,
        field_in_src: bool,
        dest_layer: Sdf.Layer,
        dest_path: Sdf.Path,
        field_in_dest: bool
) -> Union[bool, tuple[bool, list, list]]:
    if field_in_dest and not field_in_src:
        # Keep existing children
        return False
    if field_in_dest and field_in_src:
        # Copy over children with matching names but preserve existing children
        # that have no new match
        src = src_layer.GetObjectAtPath(src_path)
        dest = dest_layer.GetObjectAtPath(dest_path)
        src_children = src.GetInfo(children_field)
        dest_children = dest.GetInfo(children_field)
        src_children_lookup = set(src_children)
        keep_children = [
            child for child in dest_children
            if child not in src_children_lookup
        ]

        return True, src_children, src_children + keep_children

    return True


def copy_spec_merge(src_layer: Sdf.Layer,
                    src_path: Sdf.Path,
                    dest_layer: Sdf.Layer,
                    dest_path: Sdf.Path) -> bool:
    """Copy spec while merging into the existing opinions instead of replacing.

    The children hierarchy will be merged so that existing children will be
    preserved, but new children will be applied on top of the existing ones,
    including overlaying onto existing children prims with the same name.

    For copying values onto existing prims:
        - specifier is only copied if copied spec sets `Sdf.SpecifierDef`
        - type name is only copied if original spec had no or empty type name

    """
    return Sdf.CopySpec(src_layer, src_path, dest_layer, dest_path,
                        should_copy_value_fn, should_copy_children_fn)
