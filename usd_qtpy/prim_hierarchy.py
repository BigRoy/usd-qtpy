import logging
import contextlib
from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Usd, Sdf, Tf

from .lib.qt import report_error
from .lib.usd import get_prim_types_by_group, rename_prim
from .prim_type_icons import PrimTypeIconProvider
from .prim_delegate import DrawRectsDelegate


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

                rename_prim(prim, value)
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

        if role == DrawRectsDelegate.RectDataRole:
            prim = index.internalPointer()
            rects = []
            if prim == self.stage.GetDefaultPrim():
                rects.append(
                    {"text": "DFT",
                     "background-color": "#553333"}
                )
            if prim.HasAuthoredPayloads() or prim.HasAuthoredReferences():
                rects.append(
                    {"text": "REF",
                     "background-color": "#333355"},
                )
            if prim.HasVariantSets():
                rects.append(
                    {"text": "VAR",
                     "background-color": "#335533"},
                )

            return rects
    # endregion


class CreateVariantSetDialog(QtWidgets.QDialog):
    """Prompt for variant set name"""
    def __init__(self, parent=None):
        super(CreateVariantSetDialog, self).__init__(parent=parent)

        self.setWindowTitle("Create Variant Set")

        form = QtWidgets.QFormLayout(self)

        name = QtWidgets.QLineEdit()
        form.addRow(QtWidgets.QLabel("Variant Set Name:"), name)

        # Add some standard buttons (Cancel/Ok) at the bottom of the dialog
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self
        )
        form.addRow(buttons)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.name = name


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
        self._delegate = DrawRectsDelegate(parent=self)
        self.setItemDelegate(self._delegate)
        self._delegate.rect_clicked.connect(self.on_prim_tag_clicked)

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
        root = stage.GetPseudoRoot()
        default_prim = stage.GetDefaultPrim()
        if not parent:
            parent = root

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

        # Create Prims
        create_prim_menu = menu.addMenu("Create Prim")

        create_prim_menu.addAction("Def")
        create_prim_menu.addAction("Scope")
        create_prim_menu.addAction("Xform")
        create_prim_menu.addSeparator()
        create_prim_menu.addAction("Cone")
        create_prim_menu.addAction("Cube")
        create_prim_menu.addAction("Cylinder")
        create_prim_menu.addAction("Sphere")
        create_prim_menu.addSeparator()
        create_prim_menu.addAction("DistantLight")
        create_prim_menu.addAction("DomeLight")
        create_prim_menu.addAction("RectLight")
        create_prim_menu.addAction("SphereLight")
        create_prim_menu.addSeparator()
        create_prim_menu.addAction("Camera")
        create_prim_menu.addSeparator()

        # TODO: Cache this submenu?
        types_by_group = get_prim_types_by_group()
        all_registered_menu = create_prim_menu.addMenu("All Registered")
        for group, types in types_by_group.items():
            group_menu = all_registered_menu.addMenu(group)
            for type_name in types:
                group_menu.addAction(type_name)

        create_prim_menu.triggered.connect(create_prim)

        # Set and clear default prim
        if parent != root and parent.GetParent() == root:
            # This prim is a primitive directly under root so can be an
            # active prim
            is_default_prim = parent == default_prim
            if is_default_prim:
                label = "Clear default prim"
                action = menu.addAction(label)
                tip = (
                    "Clear the default prim from the stage's root layer.\n"
                    f"The current default prim is {default_prim.GetName()}"
                )
                action.setToolTip(tip)
                action.setStatusTip(tip)
                action.triggered.connect(partial(stage.ClearDefaultPrim))
            else:
                label = "Set as default prim"
                action = menu.addAction(label)
                tip = "Set prim as default prim on the stage's root layer."
                action.setToolTip(tip)
                action.setStatusTip(tip)
                action.triggered.connect(partial(stage.SetDefaultPrim, parent))

        # Allow referencing / payloads / variants management
        if parent != root:

            def _add_reference(prim):
                filenames, _filter = QtWidgets.QFileDialog.getOpenFileNames(
                    parent=self,
                    caption="Sublayer USD file",
                    filter="USD (*.usd *.usda *.usdc);"
                )
                references = prim.GetReferences()
                for filename in filenames:
                    references.AddReference(filename)

            action = menu.addAction("Add reference")
            action.triggered.connect(partial(_add_reference, parent))

            def _add_variant_set(prim):
                # Prompt for a variant set name (and maybe directly allow
                # managing the individual variants from the same UI; and allow
                # picking the default variant?)
                prompt = CreateVariantSetDialog(parent=self)
                if prompt.exec_() == QtWidgets.QDialog.Accepted:
                    name = prompt.name.text()
                    if name:
                        # Create the variant set, even allowing to create it
                        # without populating a variant name
                        prim.GetVariantSets().AddVariantSet(name)

            action = menu.addAction("Create Variant Set")
            action.triggered.connect(partial(_add_variant_set, parent))

        # Get mouse position
        global_pos = self.viewport().mapToGlobal(point)
        menu.exec_(global_pos)

    def on_prim_tag_clicked(self, index, text):
        print(index.data())
        if text == "DFT":
            print("DFT YES")
        elif text == "REF":
            print("REF YES")
        elif text == "VAR":
            print("VAR YES")


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
