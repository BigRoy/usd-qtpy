from .resources import get_icon


class PrimTypeIconProvider:
    """Return icon for a `Usd.Prim` based on type name with caching

    Note: Currently very simple/rudimentary implementation
    """
    # TODO: We might want to colorize the icon in the model based on some
    #   other piece of data. We might need a custom icon painter then?

    def __init__(self):
        self._type_to_icon = {}

    def get_icon_from_type_name(self, type_name):
        if type_name in self._type_to_icon:
            return self._type_to_icon[type_name]

        # Icon by type matches
        # TODO: Rewrite the checks below to be based off of the base type
        #   instead of the exact type so that inherited types are also caught
        #   as material, light, etc.
        if type_name == "Scope":
            name = "crosshair"
        elif type_name == "":
            name = "help-circle"
        elif type_name == "Xform":
            name = "move"
        elif type_name == "Camera":
            name = "video"
        # Maybe use `prim.IsA(prim_type)` but preferably we can go based off
        # of only the type name so that cache makes sense for all types
        elif type_name in {"Material", "NodeGraph", "Shader"}:
            name = "globe"
        elif type_name in {"Mesh",
                           "Capsule",
                           "Cone",
                           "Cube",
                           "Cylinder",
                           "Sphere"}:
            name = "box"
        elif type_name.endswith("Light"):
            name = "sun"
        elif type_name.startswith("Render"):
            name = "zap"
        elif type_name.startswith("Physics"):
            name = "wind"
        else:
            name = None

        # Define icon
        icon = None
        if name:
            icon = get_icon(name)

        self._type_to_icon[type_name] = icon
        return icon

    def get_icon(self, prim):
        type_name = prim.GetTypeName()
        return self.get_icon_from_type_name(type_name)
