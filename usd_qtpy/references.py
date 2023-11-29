import os
from collections import namedtuple, defaultdict
from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Sdf, Usd

from .resources import get_icon
from .lib.qt import DropFilesPushButton
from .prim_hierarchy_model import HierarchyModel


class PickPrimPath(QtWidgets.QDialog):

    picked_path = QtCore.Signal(Sdf.Path)

    def __init__(self, stage, prim_path, parent=None):
        super(PickPrimPath, self).__init__(parent=parent)

        layout = QtWidgets.QVBoxLayout(self)

        model = HierarchyModel(stage=stage)
        view = QtWidgets.QTreeView()
        view.setModel(model)
        view.setHeaderHidden(True)
        view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        layout.addWidget(view)

        if prim_path:
            # Set selection to the given prim path if it exists
            pass

        # Add some standard buttons (Cancel/Ok) at the bottom of the dialog
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self
        )
        layout.addWidget(buttons)

        self.model = model
        self.view = view

        view.doubleClicked.connect(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.accepted.connect(self.on_accept)

    def on_accept(self):
        indexes = self.view.selectedIndexes()
        if not indexes:
            return

        index = indexes[0]
        prim = index.data(HierarchyModel.PrimRole)
        if not prim:
            return
        path = prim.GetPath()
        self.picked_path.emit(path)


class RefPayloadWidget(QtWidgets.QWidget):
    """Widget for a single payload/reference entry.

    Used by `ReferenceListWidget`
    """

    delete_requested = QtCore.Signal()

    def __init__(self, item=None, item_type=None, parent=None):
        super(RefPayloadWidget, self).__init__(parent=parent)

        if item is None and item_type is None:
            raise ValueError(
                "Arguments `item` and/or `item_type` must be passed"
            )
        if item_type is None:
            item_type = type(item)

        self._original_item = item
        self._item_type = item_type

        layout = QtWidgets.QHBoxLayout(self)

        filepath = QtWidgets.QLineEdit()
        filepath.setPlaceholderText(
            "Set filepath to USD or supply file identifier"
        )
        filepath.setMinimumWidth(400)

        browser = QtWidgets.QPushButton(get_icon("folder"), "")
        default_prim_label = QtWidgets.QLabel("     Prim:")
        auto_prim = QtWidgets.QCheckBox("auto")
        auto_prim.setToolTip(
            "When enabled the default prim defined in the USD file will be "
            "used.\nIf the USD file defines no default prim the first prim "
            "will be used instead.\n"
            "When disabled, a default prim can be explicitly set in the field "
            "to the right."
        )
        default_prim = QtWidgets.QLineEdit()
        default_prim.setPlaceholderText("Pick prim path")

        pick_default_prim = QtWidgets.QPushButton(get_icon("edit-2"), "")
        pick_default_prim.setToolTip("Select default prim...")
        delete = QtWidgets.QPushButton(get_icon("x"), "")
        delete.setToolTip("Delete")

        auto_prim.setChecked(True)
        default_prim.setEnabled(False)
        if item:
            filepath.setText(item.assetPath)
            has_prim_path = bool(item.primPath)
            if has_prim_path:
                auto_prim.setChecked(False)
                default_prim.setEnabled(True)
                default_prim.setText(item.primPath.pathString)

        layout.addWidget(filepath)
        layout.addWidget(browser)
        layout.addWidget(default_prim_label)
        layout.addWidget(auto_prim)
        layout.addWidget(default_prim)
        layout.addWidget(pick_default_prim)
        layout.addWidget(delete)

        self.filepath = filepath
        self.auto_prim = auto_prim
        self.default_prim = default_prim
        self.pick_default_prim = pick_default_prim

        auto_prim.stateChanged.connect(self.on_auto_prim_changed)
        pick_default_prim.clicked.connect(self.on_pick_prim)
        browser.clicked.connect(self.on_browse)
        delete.clicked.connect(self.delete_requested)

    def on_auto_prim_changed(self, state):
        self.default_prim.setEnabled(not state)

    def on_pick_prim(self):

        filepath = self.filepath.text()
        if not filepath:
            raise ValueError("No file set")

        prim_path = self.default_prim.text()

        if not os.path.exists(filepath):
            raise ValueError(f"File does not exist: {filepath}")

        stage = Usd.Stage.Open(filepath)
        picker = PickPrimPath(stage=stage, prim_path=prim_path, parent=self)

        def on_picked(path):
            if path:
                self.default_prim.setText(path.pathString)
                self.auto_prim.setChecked(False)

        picker.picked_path.connect(on_picked)
        picker.exec_()

    def on_browse(self):
        filename, _filter = QtWidgets.QFileDialog.getOpenFileName(
            parent=self,
            caption="Sublayer USD file",
            filter="USD (*.usd *.usda *.usdc);",
            dir=self.filepath.text() or None
        )
        if filename:
            self.filepath.setText(filename)

    @property
    def item(self):

        # Do not return a valid item if no path is set
        asset_path = self.filepath.text()
        if not asset_path:
            return

        # Construct a new item based on current settings
        item_kwargs = {}
        if self._original_item and isinstance(self._original_item, Sdf.Reference):
            # Preserve custom data for references; payloads do not have this
            item_kwargs["customData"] = self._original_item.customData
        if self._original_item:
            # Preserve layer offset
            item_kwargs["layerOffset"] = self._original_item.layerOffset

        default_prim = Sdf.Path()
        if not self.auto_prim.isChecked():
            default_prim = Sdf.Path(self.default_prim.text())

        # Create a new instance of the same type as the current item value
        return self._item_type(
            assetPath=asset_path,
            primPath=default_prim,
            **item_kwargs
        )

    @property
    def original_item(self):
        return self._original_item


class ReferenceListWidget(QtWidgets.QDialog):
    """Manage lists of references/payloads for a single prim"""
    def __init__(self, prim, parent=None):
        super(ReferenceListWidget, self).__init__(parent=parent)

        title = "USD Reference/Payload Editor"
        if prim and prim.IsValid():
            title = f"{title}: {prim.GetPath().pathString}"
        self.setWindowTitle(title)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("References"))
        references = QtWidgets.QVBoxLayout()
        references.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(references)

        add_icon = get_icon("plus")
        add_button = DropFilesPushButton(add_icon, "")
        add_button.setToolTip("Add reference")
        add_button.clicked.connect(self.on_add_reference)
        add_button.files_dropped.connect(partial(self.on_dropped_files,
                                                 "references"))
        layout.addWidget(add_button)

        layout.addWidget(QtWidgets.QLabel("Payloads"))
        payloads = QtWidgets.QVBoxLayout()
        payloads.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(payloads)

        add_button = DropFilesPushButton(add_icon, "")
        add_button.setToolTip("Add payload")
        add_button.clicked.connect(self.on_add_payload)
        add_button.files_dropped.connect(partial(self.on_dropped_files,
                                                 "payloads"))
        layout.addWidget(add_button)

        layout.addStretch()

        # Add some standard buttons (Cancel/Ok) at the bottom of the dialog
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok |
            QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.prim = prim
        self.references_layout = references
        self.payloads_layout = payloads

        self.refresh()

        self.accepted.connect(self.on_accept)

    def refresh(self):

        def clear(layout):
            while layout_item:= layout.takeAt(0):
                widget = layout_item.widget()
                if widget:
                    widget.deleteLater()

        clear(self.payloads_layout)
        clear(self.references_layout)

        # Store items and widgets for the references
        prim = self.prim

        stack = prim.GetPrimStack()

        # Get all references/payloads across the prim stack
        references = []
        payloads = []
        for prim_spec in stack:
            for reference in prim_spec.referenceList.GetAppliedItems():
                references.append(reference)
            for payload in prim_spec.payloadList.GetAppliedItems():
                payloads.append(payload)

        for reference in references:
            self._add_widget(self.references_layout, item=reference)

        for payload in payloads:
            self._add_widget(self.payloads_layout, item=payload)

    def on_dropped_files(self, key, urls):
        files = [url.toLocalFile() for url in urls]
        if key == "references":
            for filepath in files:
                self._add_widget(self.references_layout,
                                 item=Sdf.Reference(assetPath=filepath))
        elif key == "payloads":
            for filepath in files:
                self._add_widget(self.payloads_layout,
                                 item=Sdf.Payload(assetPath=filepath))

    def on_add_payload(self):
        self._add_widget(self.payloads_layout, item_type=Sdf.Payload)

    def on_add_reference(self):
        self._add_widget(self.references_layout, item_type=Sdf.Reference)

    def _add_widget(self, layout, item=None, item_type=None):
        def remove_widget(layout, widget):
            index = layout.indexOf(widget)
            if index >= 0:
                layout.takeAt(index)
                widget.deleteLater()

        widget = RefPayloadWidget(item=item, item_type=item_type)
        widget.delete_requested.connect(partial(remove_widget, layout, widget))
        layout.addWidget(widget)

    def on_accept(self):
        Change = namedtuple("change", ["old", "new"])

        # Get the configured references/payloads
        items = defaultdict(list)
        for key, layout in {
            "references": self.references_layout,
            "payloads": self.payloads_layout
        }.items():
            for i in range(layout.count()):
                layout_item = layout.itemAt(i)
                widget = layout_item.widget()  # -> RefPayloadWidget

                new_item = widget.item
                if not new_item:
                    # Skip empty entries
                    continue
                change = Change(old=widget.original_item, new=new_item)
                items[key].append(change)

        # Update all prim specs on the prim's current stack to the references
        # TODO: Preserve references/payloads specs across the different layers
        #  and only update the changes that have an original item and remove
        #  entries not amongst the new changes + ensure ordering is correct
        #  For now we completely clear all specs
        prim = self.prim
        for prim_spec in list(prim.GetPrimStack()):
            if prim_spec.expired:
                continue

            # Remove any opinions on references/payloads
            prim_spec.referenceList.ClearEdits()
            prim_spec.payloadList.ClearEdits()

        references = prim.GetReferences()
        for reference_item in items["references"]:
            references.AddReference(reference_item.new)

        payloads = prim.GetPayloads()
        for payload_item in items["payloads"]:
            payloads.AddPayload(payload_item.new)
