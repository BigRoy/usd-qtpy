import logging
import os
import contextlib

from qtpy import QtWidgets, QtGui, QtCore
from pxr import Usd, Sdf, Tf


from .lib.qt import report_error
from .lib.usd import get_prim_types_by_group


@contextlib.contextmanager
def layout_change_context(model):
    """Context manager to ensure model layout changes are propagated if an
    exception is thrown.
    """
    model.layoutAboutToBeChanged.emit()
    try:
        yield
    finally:
        model.layoutChanged.emit()


class PrimTypeIconProvider:
    """Return icon for a `Usd.Prim` based on type name with caching

    Note: Currently very simple/rudimentary implementation
    """
    # TODO: We might want to colorize the icon in the model based on some
    #   other piece of data. We might a custom icon painter then?

    def __init__(self):
        self._type_to_icon = {}

        self._root = os.path.join(os.path.dirname(__file__),
                                 "resources",
                                 "feathericons")

    def get_icon_from_type_name(self, type_name):
        if type_name in self._type_to_icon:
            return self._type_to_icon[type_name]

        # Icon by type matches
        # TODO: Rewrite the checks below to be based off of the base type
        #   instead of the exact type so that inherited types are also caught
        #   as material, light, etc.
        if type_name == "Scope":
            name = "crosshair.svg"
        elif type_name == "":
            name = "help-circle.svg"
        elif type_name == "Xform":
            name = "move.svg"
        elif type_name == "Camera":
            name = "video.svg"
        # Maybe use `prim.IsA(prim_type)` but preferably we can go based off
        # of only the type name so that cache makes sense for all types
        elif type_name in {"Material", "NodeGraph", "Shader"}:
            name = "globe.svg"
        elif type_name in {"Mesh",
                           "Capsule",
                           "Cone",
                           "Cube",
                           "Cylinder",
                           "Sphere"}:
            name = "box.svg"
        elif type_name.endswith("Light"):
            name = "sun.svg"
        elif type_name.startswith("Render"):
            name = "zap.svg"
        elif type_name.startswith("Physics"):
            name = "wind.svg"
        else:
            name = None

        # Define icon
        icon = None
        if name:
            path = os.path.join(self._root, name)
            icon = QtGui.QIcon(path)

        self._type_to_icon[type_name] = icon
        return icon

    def get_icon(self, prim):
        type_name = prim.GetTypeName()
        return self.get_icon_from_type_name(type_name)


class HierarchyModel(QtCore.QAbstractItemModel):

    PrimRole = QtCore.Qt.UserRole + 1

    def __init__(self, stage, *args, **kwargs):
        super(HierarchyModel, self).__init__(*args, **kwargs)

        self._stage = None
        self._listener = None
        self._prims = {}
        self._indices = {}
        self._icon_provider = PrimTypeIconProvider()
        self.log = logging.getLogger("HierarchyModel")

        # Set stage
        self.set_stage(stage)

    @property
    def stage(self):
        return self._stage

    @property
    def root(self):
        # Quick access to pseudoroot of stage
        return self._stage.GetPseudoRoot() if self._stage else None

    def set_stage(self, value):
        """Resets the model for use with a new stage.

        If the stage isn't valid, this effectively becomes an empty model.
        """
        if value == self._stage:
            return

        self._stage = value
        with self.reset_context():
            is_valid_stage = bool(self._stage and self._stage.GetPseudoRoot())
            if is_valid_stage:
                # Listen to state changes of the stage to stay in sync
                self._listener = Tf.Notice.Register(
                    Usd.Notice.ObjectsChanged,
                    self.on_objects_changed,
                    self._stage
                )

    @contextlib.contextmanager
    def reset_context(self):
        """Reset the model via context manager.

        During the context additional changes can be done before the reset
        of the model is 'finished', like e.g. changing Tf.Notice listeners.
        """
        self.beginResetModel()
        try:
            self._indices.clear()
            self._prims.clear()
            self._listener = None
            yield
        finally:
            self.endResetModel()

    @report_error
    def on_objects_changed(self, notice, sender):
        """Update changes on TfNotice signal"""
        resynced_paths = notice.GetResyncedPaths()
        resynced_paths = [path for path in resynced_paths if path.IsPrimPath()]

        if not resynced_paths:
            return

        self.log.debug("received changed prim signal: %s", resynced_paths)

        # For now do full reset since that seems less buggy than the manual
        # method below.
        # TODO: Fix sync object change
        # TODO: Do not error on deactivating prims
        with self.reset_context():
            # Remove all persistent indexes
            existing = self.persistentIndexList()
            null = [QtCore.QModelIndex()] * len(existing)
            self.changePersistentIndexList(existing, null)
            return

        with layout_change_context(self):
            persistent_indices = self.persistentIndexList()
            index_to_path = {}
            for index in persistent_indices:
                prim = index.internalPointer()
                path = prim.GetPath()

                for resynced_path in resynced_paths:
                    common_path = resynced_path.GetCommonPrefix(path)
                    # if the paths are siblings or if the
                    # index path is a child of resynced path, you need to
                    # update any persistent indices
                    are_siblings = (
                            common_path == resynced_path.GetParentPath()
                            and common_path != path
                    )
                    index_is_child = (common_path == resynced_path)

                    if are_siblings or index_is_child:
                        index_to_path[index] = path

            from_indices = []
            to_indices = []
            for index, path in index_to_path.items():
                new_prim = self.stage.GetPrimAtPath(path)
                if new_prim.IsValid():
                    # Update existing index
                    self.log.debug("update: update %s to new prim: %s",
                                   path,
                                   new_prim)
                    new_row = self._prim_to_row_index(new_prim)
                    if index.row() != new_row:
                        self.remove_path_cache(path)
                        for i in range(self.columnCount(QtCore.QModelIndex())):
                            from_indices.append(index)
                            to_indices.append(self.createIndex(
                                new_row, index.column(), new_prim)
                            )
                else:
                    # Removed index
                    self.log.debug("update: removing path index: %s", path)
                    from_indices.append(index)
                    to_indices.append(QtCore.QModelIndex())
            self.changePersistentIndexList(from_indices, to_indices)

            self.log.debug("Current cache: %s", self._indices)

    def remove_path_cache(self, path):
        """Remove Sdf.Path cache entry from internal reference"""
        path_str = path.pathString
        self._indices.pop(path_str)
        self._prims.pop(path_str)

    def _prim_to_row_index(self, prim):
        """Return the row index for Usd.Prim under its parent"""

        if not prim.IsValid():
            return 0

        # Find the index of prim under the parent
        if prim.IsPseudoRoot():
            return 0
        else:
            # TODO: Optimize this!
            parent = prim.GetParent()
            prim_path = prim.GetPath()
            children = list(parent.GetAllChildren())
            for i, child_prim in enumerate(children):
                if child_prim.GetPath() == prim_path:
                    return i

    # region Qt methods
    def createIndex(self, row, column, id):
        # We need to keep a reference to the prim otherwise it'll get
        # garbage collected - because `createIndex` does not hold a counted
        # reference to the object. So we do it ourselves, returning existing
        # created indices if the `id` matches a previous iteration. Is this ok?
        prim = id
        path = prim.GetPath().pathString
        if path in self._indices:
            return self._indices[path]
        self._prims[path] = prim

        index = super(HierarchyModel, self).createIndex(row, column, prim)
        self._indices[path] = index
        return index

    def flags(self, index):
        # Make name editable
        if index.column() == 0:
            return (
                QtCore.Qt.ItemIsEnabled
                | QtCore.Qt.ItemIsSelectable
                | QtCore.Qt.ItemIsEditable
            )
        return super(HierarchyModel, self).flags(index)

    def setData(self, index, value, role):
        if role == QtCore.Qt.EditRole:
            if index.column() == 0:
                # Rename prim
                prim = index.internalPointer()
                if not value:
                    # Keep original name
                    return False

                lib.rename_prim(prim, value)
                return True

        return super(HierarchyModel, self).setData(index, value, role)

    def columnCount(self, parent):
        return 1

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            # Return amount of children for root item
            return len(self.root.GetAllChildren())

        prim = parent.internalPointer()
        if not prim or not prim.IsValid():
            self.log.error("Parent prim not found for row count: %s", parent)
            return 0

        return len(list(prim.GetAllChildren()))

    def index(self, row, column, parent):

        if not self.hasIndex(row, column, parent):
            return QtCore.QModelIndex()

        if not parent.isValid():
            parent_prim = self.root
        else:
            parent_prim = parent.internalPointer()

        if not parent_prim or not parent_prim.IsValid():
            self.log.error("Invalid parent prim for index: %s", parent)
            return QtCore.QModelIndex()

        children = list(parent_prim.GetAllChildren())
        if row > len(children):
            return QtCore.QModelIndex()

        prim = children[row]
        return self.createIndex(row, column, prim)

    def parent(self, index):
        if not index.isValid():
            return QtCore.QModelIndex()

        prim = index.internalPointer()
        if prim is None or prim.IsPseudoRoot() or not prim.IsValid():
            return QtCore.QModelIndex()

        # If it has no parents we return the pseudoroot as an invalid index
        parent_prim = prim.GetParent()
        if parent_prim is None or parent_prim.IsPseudoRoot():
            return QtCore.QModelIndex()

        row = self._prim_to_row_index(parent_prim)
        return self.createIndex(row, 0, parent_prim)

    def data(self, index, role):
        if not index.isValid():
            return

        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
            prim = index.internalPointer()
            return prim.GetName()

        if role == QtCore.Qt.DecorationRole:
            # icon
            prim = index.internalPointer()
            return self._icon_provider.get_icon(prim)

        if role == QtCore.Qt.ToolTipRole:
            prim = index.internalPointer()
            return prim.GetTypeName()
    # endregion


class View(QtWidgets.QTreeView):
    # TODO: Add shortcuts
    #   CTRL + D: Duplicate
    #   CTRL + G: Group (add Xform above current selection)
    #   Delete or backspace: Remove the selected prims

    def __init__(self, *args, **kwargs):
        super(View, self).__init__(*args, **kwargs)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.on_context_menu)

    def on_context_menu(self, point):
        """Shows menu with loader actions on Right-click.

        Registered actions are filtered by selection and help of
        `loaders_from_representation` from avalon api. Intersection of actions
        is shown when more subset is selected. When there are not available
        actions for selected subsets then special action is shown (works as
        info message to user): "*No compatible loaders for your selection"

        """
        index = self.indexAt(point)

        model = self.model()
        stage = model.stage

        parent = index.internalPointer()
        if not parent:
            parent = stage.GetPseudoRoot()

        menu = QtWidgets.QMenu(self)

        def create_prim(action):
            type_name = action.text()

            # Ensure unique name
            base_path = parent.GetPath().AppendChild(type_name)
            prim_path = base_path
            i = 1
            while stage.GetPrimAtPath(prim_path):
                prim_path = Sdf.Path(f"{base_path.pathString}{i}")
                i += 1

            if type_name == "Def":
                # Typeless
                type_name = ""

            # Define prim and signal change to the model
            # TODO: Remove signaling once model listens to changes
            current_rows = model.rowCount(index)
            model.beginInsertRows(index, current_rows, current_rows+1)
            stage.DefinePrim(prim_path, type_name)
            model.endInsertRows()

        # Some nice quick access types
        menu.addAction("Def")
        menu.addAction("Scope")
        menu.addAction("Xform")
        menu.addSeparator()
        menu.addAction("Cone")
        menu.addAction("Cube")
        menu.addAction("Cylinder")
        menu.addAction("Sphere")
        menu.addSeparator()
        menu.addAction("DistantLight")
        menu.addAction("DomeLight")
        menu.addAction("RectLight")
        menu.addAction("SphereLight")
        menu.addSeparator()
        menu.addAction("Camera")
        menu.addSeparator()

        # TODO: Cache this submenu?
        types_by_group = get_prim_types_by_group()
        all_registered_menu = menu.addMenu("All Registered")
        for group, types in types_by_group.items():
            group_menu = all_registered_menu.addMenu(group)
            for t in types:
                group_menu.addAction(t)

        menu.triggered.connect(create_prim)

        # Get mouse position
        global_pos = self.viewport().mapToGlobal(point)
        menu.exec_(global_pos)


class HierarchyWidget(QtWidgets.QDialog):
    def __init__(self, stage, parent=None):
        super(HierarchyWidget, self).__init__(parent=parent)

        self.setWindowTitle("USD Outliner")
        layout = QtWidgets.QVBoxLayout(self)

        model = HierarchyModel(stage=stage)
        view = View()
        view.setModel(model)

        self.model = model
        self.view = view

        layout.addWidget(view)