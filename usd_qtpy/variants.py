import logging
from functools import partial

from qtpy import QtWidgets, QtCore
from pxr import Usd, Tf

from .lib.usd import LIST_ATTRS
from .resources import get_icon

log = logging.getLogger(__name__)


def is_direct_variant_edit_target(
    edit_target: Usd.EditTarget,
    variant_set: Usd.VariantSet,
    variant_name: str
) -> bool:
    """Return whether edit target targets the variant set's variant.

    It does not care on which layer it is targeting and whether the prim
    or its variant sets even exist on that layer.

    This would return true for edit targets that were made directly on the
    layer, using e.g.:
        >>> Usd.EditTarget.ForLocalDirectVariant(layer, variant_path)
    Or:
        >>> layer_edit_target = stage.GetEditTargetForLocalLayer(layer)
        >>> stage.SetEditTarget(layer_edit_target)
        >>> variant_edit_target = variant_set.GetVariantEditContext(layer)

    See: https://forum.aousd.org/t/query-whether-stage-edit-target-is-targeting-a-particular-variant  # noqa

    """
    edit_target_mapping = edit_target.GetMapFunction()
    if edit_target_mapping.isIdentityPathMapping:
        # This is not mapping any variants
        return False

    prim = variant_set.GetPrim()
    variant_path = prim.GetPath().AppendVariantSelection(variant_set.GetName(),
                                                         variant_name)
    return variant_path in edit_target_mapping.sourceToTargetMap


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

    @classmethod
    def get_variant_set_name(cls, parent=None):
        prompt = cls(parent=parent)
        if prompt.exec_() == QtWidgets.QDialog.Accepted:
            name = prompt.name.text()
            if name:
                return name


class Separator(QtWidgets.QFrame):
    def __init__(self, thickness=2, parent=None):
        super(Separator, self).__init__(parent=parent)
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.setLineWidth(thickness)
        self.setFixedHeight(thickness)
        self.setSizePolicy(QtWidgets.QSizePolicy.Minimum,
                           QtWidgets.QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #21252B;")


class VariantSetWidget(QtWidgets.QWidget):
    """Widget for a single variant set"""

    variant_set_deleted = QtCore.Signal()

    def __init__(self, variant_set, parent=None):
        super(VariantSetWidget, self).__init__(parent=parent)

        self._listeners = []
        self._variant_set: Usd.VariantSet = variant_set
        self._stage: Usd.Stage = variant_set.GetPrim().GetStage()
        variant_set_name = variant_set.GetName()

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 13, 0, 0)

        layout.addWidget(Separator(thickness=1))
        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(f"<h3>{variant_set_name}</h3>")
        label.setAlignment(QtCore.Qt.AlignCenter)
        delete_button = QtWidgets.QPushButton(get_icon("x"), "")
        delete_button.setFixedWidth(20)
        delete_button.clicked.connect(self.on_delete_variant_set)
        header_layout.addWidget(label)
        header_layout.addWidget(delete_button)
        layout.addLayout(header_layout)
        layout.addWidget(Separator(thickness=1))

        group = QtWidgets.QGroupBox()
        grid_layout = QtWidgets.QGridLayout(group)
        # indent to variant set header
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setRowStretch(0, 1)
        layout.addWidget(group)

        add_icon = get_icon("plus")
        add_button = QtWidgets.QPushButton(add_icon, "Add variant")
        add_button.setToolTip(f"Add variant for {variant_set_name}")
        add_button.setFocusPolicy(QtCore.Qt.StrongFocus)
        add_button.clicked.connect(self.on_add_variant)
        layout.addWidget(add_button)
        layout.addStretch()

        self.grid_layout = grid_layout
        self.add_button = add_button

        self.destroyed.connect(self.revoke_listeners)

    def refresh(self):
        # Clear all widgets in the grid layout
        def clear(layout: QtWidgets.QGridLayout):
            """Clear a QGridLayout

            This does not consider items spanning more than one row.
            """
            for index in reversed(range(layout.count())):
                layout_item = layout.takeAt(index)
                widget = layout_item.widget()
                if widget:
                    widget.deleteLater()
            layout.invalidate()

        clear(self.grid_layout)

        for variant_name in self._variant_set.GetVariantNames():
            self._add_variant(variant_name)

    def on_notice(self, notice, sender):
        # TODO: We might want to 'schedule' a refresh with slight delay
        #  to ensure we're not continuously updating during quick successive
        #  edits
        self.refresh()

    def showEvent(self, event):
        # Refresh once, then register listeners to stay sync
        self.refresh()
        self.register_listeners()

    def hideEvent(self, event):
        self.revoke_listeners()

    def register_listeners(self):
        self.revoke_listeners()  # ensure cleaned up
        stage = self._stage
        self._listeners.append(Tf.Notice.Register(
            Usd.Notice.StageEditTargetChanged,
            self.on_notice,
            stage
        ))
        self._listeners.append(Tf.Notice.Register(
            Usd.Notice.ObjectsChanged,
            self.on_notice,
            stage
        ))

    def revoke_listeners(self):
        for listener in self._listeners:
            listener.Revoke()
        self._listeners.clear()

    def _add_variant(self, variant_name):
        grid_layout = self.grid_layout
        row = grid_layout.rowCount()

        # Select variant radio button
        select_button = QtWidgets.QRadioButton(variant_name)
        is_selected = self._variant_set.GetVariantSelection() == variant_name
        select_button.setChecked(is_selected)
        select_button.toggled.connect(partial(self.on_select_variant,
                                              variant_name))

        # Set edit target button
        is_edit_target = is_direct_variant_edit_target(
            edit_target=self._stage.GetEditTarget(),
            variant_set=self._variant_set,
            variant_name=variant_name
        )
        set_edit_target_button = QtWidgets.QPushButton(get_icon("edit-2"), "")
        set_edit_target_button.setFixedWidth(20)
        set_edit_target_button.setCheckable(True)
        set_edit_target_button.setChecked(is_edit_target)
        set_edit_target_button.toggled.connect(partial(self.on_set_edit_target,
                                               variant_name))

        # Delete button
        delete_button = QtWidgets.QPushButton(get_icon("x"), "")
        delete_button.setFixedWidth(20)
        delete_button.clicked.connect(partial(self.on_delete_variant,
                                              variant_name, row))

        grid_layout.addWidget(select_button, row, 0)
        grid_layout.addWidget(set_edit_target_button, row, 1)
        grid_layout.addWidget(delete_button, row, 2)

    def on_delete_variant_set(self):
        # Remove specs across all layers regarding this variant set
        # Question: Does this include specs by referenced/payloads as well.
        #   If so I presume we don't want to include those?
        prim: Usd.Prim = self._variant_set.GetPrim()
        variant_set_name = self._variant_set.GetName()
        for prim_spec in prim.GetPrimStack():
            if prim_spec.expired:
                continue

            if variant_set_name in prim_spec.variantSets:
                del prim_spec.variantSets[variant_set_name]

            for key in LIST_ATTRS:
                list_proxy = getattr(prim_spec.variantSetNameList, key)
                index = list_proxy.index(variant_set_name)
                if index != -1:
                    del list_proxy[index]

            # Remove variant selection opinion
            if variant_set_name in prim_spec.variantSelections:
                del prim_spec.variantSelections[variant_set_name]

        self.variant_set_deleted.emit()

    def on_add_variant(self):
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Create Variant",
            "Variant Name:"
        )
        if ok and name and not self._variant_set.HasAuthoredVariant(name):
            # Create the variant
            self._variant_set.AddVariant(name)

    def on_delete_variant(self, variant_name, row):
        """Callback when a variant is clicked to be deleted"""

        def remove_row(layout: QtWidgets.QGridLayout, remove_row):
            """Remove row in QGridLayout

            This does not consider items spanning more than one row.
            """
            for index in reversed(range(layout.count())):
                row, column, row_span, column_span = layout.getItemPosition(
                    index
                )
                if row == remove_row:
                    layout_item = layout.takeAt(index)
                    widget = layout_item.widget()
                    if widget:
                        widget.deleteLater()

        # Remove specs across all layers regarding this variant set
        # Question: Does this include specs by referenced/payloads as well.
        #   If so I presume we don't want to include those?
        prim: Usd.Prim = self._variant_set.GetPrim()
        variant_set_name = self._variant_set.GetName()
        for prim_spec in prim.GetPrimStack():
            variant_set_spec = prim_spec.variantSets.get(variant_set_name)
            if variant_set_spec.expired or not variant_set_spec:
                continue

            variant_spec = variant_set_spec.variants.get(variant_name)
            if variant_spec:
                variant_set_spec.RemoveVariant(variant_spec)

            # Also remove the variant selection if it's set to the removed
            # variant
            selected = prim_spec.variantSelections.get(variant_set_name)
            if variant_name == selected:
                del prim_spec.variantSelections[variant_set_name]

    def on_set_edit_target(self, variant_name, state):
        """Callback when a variant is set to be the edit target"""

        self.revoke_listeners()

        stage = self._stage

        # We keep the same target layer as current edit target
        current_edit_target = stage.GetEditTarget()
        layer = current_edit_target.GetLayer()

        if state:
            if self._variant_set.GetVariantSelection() != variant_name:
                # We force the variant selection in the target layer
                # so that the variant selection itself is not an opinion
                # any variant edit target mapping that might be active
                edit_target = stage.GetEditTargetForLocalLayer(layer)
                stage.SetEditTarget(edit_target)
                self._variant_set.SetVariantSelection(variant_name)

            # For now don't allow authoring variants in variants in variants
            # because it's complex to define how that edit context should
            # be visualized
            # TODO: Support editing in nested variant edit contexts
            layer = stage.GetEditTarget().GetLayer()  # preserve target layer
            prim = self._variant_set.GetPrim()
            variant_set_name = self._variant_set.GetName()
            variant_path = prim.GetPath().AppendVariantSelection(
                variant_set_name,
                variant_name
            )
            edit_target = Usd.EditTarget.ForLocalDirectVariant(layer,
                                                               variant_path)
            stage.SetEditTarget(edit_target)
        else:
            edit_target = stage.GetEditTargetForLocalLayer(layer)
            stage.SetEditTarget(edit_target)

        # Refresh once instead of during live changes as we tweak the
        # edit targets and variant selections, etc.
        self.refresh()
        self.register_listeners()

    def on_select_variant(self, variant_name, state):
        if not state:
            return

        # Make sure we're not target editing inside a variant since it's
        # most likely not what the artist wants and can be confusing
        stage = self._stage
        edit_target = stage.GetEditTarget()
        new_target = stage.GetEditTargetForLocalLayer(edit_target.GetLayer())
        if new_target != edit_target:
            stage.SetEditTarget(new_target)

        if self._variant_set.GetVariantSelection() != variant_name:
            self._variant_set.SetVariantSelection(variant_name)


class VariantSetsWidget(QtWidgets.QDialog):
    """Manage the variant sets and variants for a Usd.Prim"""
    def __init__(self, prim, parent=None):
        super(VariantSetsWidget, self).__init__(parent=parent)

        title = "Variant Sets"
        if prim and prim.IsValid():
            title = f"{title}: {prim.GetPath().pathString}"
        self.setWindowTitle(title)

        layout = QtWidgets.QVBoxLayout(self)

        add_icon = get_icon("plus")
        add_button = QtWidgets.QPushButton(add_icon, "Add variant set")
        add_button.setToolTip("Add variant set")
        add_button.clicked.connect(self.on_add_variant_set)
        layout.addWidget(add_button)

        variant_sets_layout = QtWidgets.QVBoxLayout()
        variant_sets_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(variant_sets_layout)

        layout.addStretch()

        self.prim = prim
        self.variant_sets_layout = variant_sets_layout

        self.refresh()

    def refresh(self):

        def clear(layout):
            for i in reversed(range(layout.count())):
                layout_item = layout.takeAt(i)
                widget = layout_item.widget()
                if widget:
                    widget.deleteLater()
            layout.invalidate()

        clear(self.variant_sets_layout)

        # Store items and widgets for the references
        prim = self.prim

        # TODO: It is possible to have an authored variant selection
        #  without the variant set being authored in the current stage.
        #  For those cases we might want to expose being able to set e.g.
        #  a custom variant selection and display those that do not have
        #  an existing variant or even variant set on the composed stage.
        #  E.g. see: Usd.VariantSets.GetAllVariantSelections

        variant_sets = prim.GetVariantSets()
        for variant_set_name in variant_sets.GetNames():
            # Add a variant set widget with its variants
            variant_set = variant_sets.GetVariantSet(variant_set_name)
            variant_set_widget = VariantSetWidget(variant_set=variant_set,
                                                  parent=self)
            variant_set_widget.variant_set_deleted.connect(self.refresh)
            self.variant_sets_layout.addWidget(variant_set_widget)

    def on_add_variant_set(self):
        log.debug("Add variant set")
        prim = self.prim
        assert prim.IsValid()
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Create Variant Set",
            "Variant Set Name:"
        )
        if ok and name:
            # Create the variant set, even allowing to create it
            # without populating a variant name. If it already exists
            # this does nothing.
            prim.GetVariantSets().AddVariantSet(name)

        self.refresh()
