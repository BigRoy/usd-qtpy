import logging
from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Sdf

from .lib.usd import (
    get_prim_types_by_group,
    parent_prims,
    remove_spec,
    unique_name,
)
from .lib.usd_merge_spec import copy_spec_merge
from .lib.qt import iter_model_rows
from .prim_delegate import DrawRectsDelegate
from .prim_hierarchy_model import HierarchyModel
from .references import ReferenceListWidget
from .variants import CreateVariantSetDialog, VariantSetsWidget

log = logging.getLogger(__name__)


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
        self.setItemDelegateForColumn(0, self._delegate)
        self._delegate.rect_clicked.connect(self.on_prim_tag_clicked)

    def on_context_menu(self, point):
        index = self.indexAt(point)

        model = self.model()
        stage = model.stage

        parent = index.data(HierarchyModel.PrimRole)
        if not parent:
            parent = stage.GetPseudoRoot()
        parent_path = parent.GetPath()

        menu = QtWidgets.QMenu(self)

        def create_prim(action):
            type_name = action.text()

            # Ensure unique name
            prim_path = parent_path.AppendChild(type_name)
            prim_path = unique_name(stage, prim_path)
            if type_name == "Def":
                # Typeless
                type_name = ""

            # Define prim and signal change to the model
            # TODO: Remove signaling once model listens to changes
            current_rows = model.rowCount(index)
            model.beginInsertRows(index, current_rows, current_rows+1)
            new_prim = stage.DefinePrim(prim_path, type_name)
            self.select_paths([new_prim.GetPath()])
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
        if parent_path.IsRootPrimPath():
            # This prim is a primitive directly under root so can be an
            # active prim
            if parent == stage.GetDefaultPrim():
                label = "Clear default prim"
                action = menu.addAction(label)
                tip = (
                    "Clear the default prim from the stage's root layer.\n"
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
        if not parent_path.IsAbsoluteRootPath():
            action = menu.addAction("Add reference/payload..")
            action.triggered.connect(partial(
                self.on_manage_prim_reference_payload, parent)
            )

            def _add_variant_set(prim):
                # TODO: maybe directly allow managing the individual variants
                #  from the same UI; and allow setting the default variant
                # Prompt for a variant set name
                name = CreateVariantSetDialog.get_variant_set_name(parent=self)
                if name is not None:
                    # Create the variant set, even allowing to create it
                    # without populating a variant name
                    prim.GetVariantSets().AddVariantSet(name)

            action = menu.addAction("Create Variant Set")
            action.triggered.connect(partial(_add_variant_set, parent))

        # Get mouse position
        global_pos = self.viewport().mapToGlobal(point)
        menu.exec_(global_pos)

    def on_manage_prim_reference_payload(self, prim):
        widget = ReferenceListWidget(prim=prim, parent=self)
        widget.resize(800, 300)
        widget.show()

    def on_prim_tag_clicked(self, event, index, block):
        text = block.get("text")
        if text == "DFT":
            # Allow to clear the prim from a menu
            model = self.model()
            stage = model.stage
            menu = QtWidgets.QMenu(parent=self)
            action = menu.addAction("Clear default prim")
            tip = (
                "Clear the default prim from the stage's root layer.\n"
            )
            action.setToolTip(tip)
            action.setStatusTip(tip)
            action.triggered.connect(partial(stage.ClearDefaultPrim))
            point = event.position().toPoint()
            menu.exec_(self.mapToGlobal(point))

        elif text == "REF":
            prim = index.data(HierarchyModel.PrimRole)
            self.on_manage_prim_reference_payload(prim)

        elif text == "VAR":
            prim = index.data(HierarchyModel.PrimRole)
            widget = VariantSetsWidget(prim=prim, parent=self)
            widget.resize(250, 100)
            widget.show()

    def select_paths(self, paths: list[Sdf.Path]):
        """Select prims in the hierarchy view that match the Sdf.Path

        If an empty path list is provided or none matching paths are found
        the selection is just cleared.

        Arguments:
            paths (list[Sdf.Path]): The paths to select.

        """

        model: HierarchyModel = self.model()
        assert isinstance(model, HierarchyModel)
        selection = QtCore.QItemSelection()

        if not paths:
            self.selectionModel().clear()
            return

        search = set(paths)
        path_to_index = {}
        for index in iter_model_rows(model, column=0):
            # We iterate the model using its regular methods so we support both
            # the model directly but also a proxy model. Also, this forces it
            # to fetch the data if the model is lazy.
            # TODO: This can be optimized by pruning the traversal if we
            #   the current prim path is not a parent of the path we search for
            if not search:
                # Found all
                break

            prim = index.data(HierarchyModel.PrimRole)
            if not prim:
                continue

            path = prim.GetPath()
            path_to_index[path] = index
            search.discard(path)

        for path in paths:
            index = path_to_index.get(path)
            if not index:
                # Path not found
                continue

            selection.select(index, index)

        selection_model = self.selectionModel()
        selection_model.select(selection,
                               QtCore.QItemSelectionModel.ClearAndSelect |
                               QtCore.QItemSelectionModel.Rows)

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        ctrl_pressed = QtCore.Qt.ControlModifier & modifiers

        # Group selected with Ctrl + G
        if (
            ctrl_pressed
            and event.key() == QtCore.Qt.Key_G
            and not event.isAutoRepeat()
        ):
            self._group_selected()
            event.accept()
            return

        # Delete selected with delete key
        if (
            event.key() == QtCore.Qt.Key_Delete
            and not event.isAutoRepeat()
        ):
            self._delete_selected()
            event.accept()
            return

        # Duplicate selected with Ctrl + D
        if (
            ctrl_pressed
            and event.key() == QtCore.Qt.Key_D
            and not event.isAutoRepeat()
        ):
            self._duplicate_selected()
            event.accept()
            return

        # Enter rename mode on current index when enter is pressed
        if (
            self.state() != QtWidgets.QAbstractItemView.EditingState
            and event.key() in [QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter]
        ):
            self.edit(self.currentIndex())
            event.accept()
            return

        return super(View, self).keyPressEvent(event)

    def _group_selected(self):
        """Group selected prims under a new Xform"""
        selected = self.selectionModel().selectedIndexes()
        prims = [index.data(HierarchyModel.PrimRole) for index in selected]

        # Exclude root prims
        prims = [prim for prim in prims if not prim.IsPseudoRoot()]
        if not prims:
            return

        stage = prims[0].GetStage()

        # Consider only prims that have opinions in the stage's layer stack
        # disregard opinions inside payloads/references
        stage_layers = set(stage.GetLayerStack())

        # Exclude prims not defined in the stage's layer stack
        prims = [
            prim for prim in prims
            if any(spec.layer in stage_layers for spec in prim.GetPrimStack())
        ]
        if not prims:
            log.warning("Skipped all prims because they are not defined in "
                        "the stage's layer stack but likely originate from a "
                        "reference or payload.")
            return

        parent_path = prims[0].GetPath().GetParentPath()

        group_path = parent_path.AppendChild("group")
        group_path = unique_name(stage, group_path)

        # Define a group
        stage.DefinePrim(group_path, "Xform")

        # We want to group across all prim specs to ensure whatever we're
        # moving gets put into the group, so we define the prim across all
        # layers of the layer stack if it contains any of the objects
        for layer in stage.GetLayerStack():
            # If the layer has opinions on any of the source prims we ensure
            # the new parent also exists, to ensure the movement of the input
            # prims
            if (
                    any(layer.GetObjectAtPath(prim.GetPath())
                        for prim in prims)
                    and not layer.GetPrimAtPath(group_path)
            ):
                Sdf.CreatePrimInLayer(layer, group_path)

        # Now we want to move all selected prims into this
        parent_prims(prims, group_path)

        # If the original group was renamed but there's now no conflict
        # anymore, e.g. we grouped `group` itself from the parent path
        # then now we can safely rename it to `group` without conflicts
        # TODO: Ensure grouping `group` doesn't make a `group1`
        self.select_paths([group_path])

    def _delete_selected(self):
        """Delete prims across all layers in the layer stack"""
        selected = self.selectionModel().selectedIndexes()
        prims = [index.data(HierarchyModel.PrimRole) for index in selected]

        # Exclude root prims
        prims = [prim for prim in prims if not prim.IsPseudoRoot()]
        if not prims:
            return

        stage = prims[0].GetStage()
        stage_layers = stage.GetLayerStack()

        # We first collect the prim specs before removing because the Usd.Prim
        # will become invalid as we start removing specs
        specs = []
        for prim in prims:
            # We only allow deletions from layers in the current layer stack
            # and exclude those that are from loaded references/payloads to
            # avoid editing specs inside references/layers
            for spec in prim.GetPrimStack():
                if spec.layer in stage_layers:
                    specs.append(spec)
                else:
                    logging.warning("Skipping prim spec not in "
                                    "stage's layer stack: %s", spec)

        with Sdf.ChangeBlock():
            for spec in specs:
                if spec.expired:
                    continue

                # Warning: This would also remove it from layers from
                #   references/payloads!
                # TODO: Filter specs for which their `.getLayer()` is a layer
                #   from the Stage's layer stack?
                remove_spec(spec)

    def _duplicate_selected(self):
        """Duplicate prim specs across all layers in the layer stack"""
        selected = self.selectionModel().selectedIndexes()
        prims = [index.data(HierarchyModel.PrimRole) for index in selected]

        # Exclude root prims
        prims = [prim for prim in prims if not prim.IsPseudoRoot()]
        if not prims:
            return []

        new_paths = []
        for prim in prims:
            path = prim.GetPath()
            stage = prim.GetStage()
            new_path = unique_name(stage, path)
            for spec in prim.GetPrimStack():
                layer = spec.layer
                copy_spec_merge(layer, path, layer, new_path)
            new_paths.append(new_path)
        self.select_paths(new_paths)


class HierarchyWidget(QtWidgets.QDialog):
    def __init__(self, stage, parent=None):
        super(HierarchyWidget, self).__init__(parent=parent)

        self.setWindowTitle("USD Outliner")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        model = HierarchyModel(stage=stage)
        view = View()
        view.setSelectionMode(QtWidgets.QTreeView.ExtendedSelection)
        view.setModel(model)

        self.model = model
        self.view = view

        layout.addWidget(view)
