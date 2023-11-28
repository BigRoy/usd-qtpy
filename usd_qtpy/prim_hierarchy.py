from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Sdf

from .lib.usd import get_prim_types_by_group
from .prim_delegate import DrawRectsDelegate
from .prim_hierarchy_model import HierarchyModel
from .references import ReferenceListWidget


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
        self.setItemDelegateForColumn(0, self._delegate)
        self._delegate.rect_clicked.connect(self.on_prim_tag_clicked)

    def on_context_menu(self, point):
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
            action = menu.addAction("Add reference/payload..")
            action.triggered.connect(partial(
                self.on_manage_prim_reference_payload, parent)
            )

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

    def on_manage_prim_reference_payload(self, prim):
        widget = ReferenceListWidget(prim=prim, parent=self)
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
            prim = index.internalPointer()
            self.on_manage_prim_reference_payload(prim)

        elif text == "VAR":
            raise NotImplementedError("To be implemented")


class HierarchyWidget(QtWidgets.QDialog):
    def __init__(self, stage, parent=None):
        super(HierarchyWidget, self).__init__(parent=parent)

        self.setWindowTitle("USD Outliner")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        model = HierarchyModel(stage=stage)
        view = View()
        view.setModel(model)

        self.model = model
        self.view = view

        layout.addWidget(view)
