import os
import contextlib
import logging
from functools import partial
from typing import List

from qtpy import QtWidgets, QtCore, QtGui

from pxr import Sdf, Usd, Tf

from .tree.itemtree import ItemTree, TreeItem
from .tree.base import AbstractTreeModelMixin
from .lib.qt import schedule, iter_model_rows
from .layer_diff import LayerDiffWidget
from .resources import get_icon

log = logging.getLogger(__name__)


def remove_sublayer(
    identifier, parent
):
    """Remove a matching identifier as sublayer from parent layer
    
    The `identifier` may be the full path `layer.identifier` but can also
    be the relative anchored sublayer path (the actual value in the usd file).
    Hence, the sublayer paths *may* be relative paths even though a layer's
    identifier passed in may be the full path.
    
    Arguments:
        identifier (str): The layer identifier to remove; this may be the
            anchored relative identifier in
        parent (Sdf.Layer): The parent Sdf.Layer or layer 
            identifier to remove the child identifier for.
    
    Returns:
        Optional[int]: Returns an integer for the removed sublayer index
            if a removal occurred, otherwise returns None
    
    """
    absolute_identifier = parent.ComputeAbsolutePath(identifier)
    for i, path in enumerate(parent.subLayerPaths):
        if (
            path == identifier
            # Allow anchored relative paths to match the full identifier 
            or parent.ComputeAbsolutePath(path) == absolute_identifier
        ):
            del parent.subLayerPaths[i]
            return i


def set_tips(widget, tip):
    widget.setStatusTip(tip)
    widget.setToolTip(tip)


class LayerItem(TreeItem):
    __slots__ = ('layer', 'stack')

    def __init__(self, layer: Sdf.Layer, parents: List[Sdf.Layer] = None):

        # The key is the full layer stack (all parents) joined together
        # by a unique separator so the layer identifier can uniquely appear
        # anywhere on the layer stack
        parents = parents or []
        stack = list(parents)
        stack.append(layer)
        separator = "<--sublayer-->"
        key = separator.join(stack_layer.identifier for stack_layer in stack)

        super(LayerItem, self).__init__(key=key)
        self.layer = layer
        self.stack = stack


class LayerStackModel(AbstractTreeModelMixin, QtCore.QAbstractItemModel):
    """Basic tree model that exposes a Stage's layer stack."""
    # TODO: Tweak this more - currently loosely based on Luma Pictures
    #  Layer Model https://github.com/LumaPictures/usd-qt/tree/master/treemodel
    headerLabels = ('Name', 'Path')

    LayerRole = QtCore.Qt.UserRole + 10

    def __init__(self,
                 stage: Usd.Stage,
                 include_session_layer=False,
                 parent=None):
        """
        Parameters
        ----------
        stage : Usd.Stage
        include_session_layer : bool
        parent : Optional[QtCore.QObject]
        """
        super(LayerStackModel, self).__init__(parent=parent)
        self._stage = None
        self._listeners = []
        self._include_session_layer = include_session_layer
        self.log = logging.getLogger("LayerStackModel")
        self.set_stage(stage)

    # region Qt methods
    def columnCount(self, parent: QtCore.QModelIndex) -> int:
        return 2

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if orientation == QtCore.Qt.Horizontal and role == QtCore.Qt.DisplayRole:
            return self.headerLabels[section]

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return
        if role == QtCore.Qt.DisplayRole:
            # Show nothing because item widgets will be used instead
            return ""
        if role == QtCore.Qt.ToolTipRole:
            item = index.internalPointer()
            return item.layer.identifier
        if role == self.LayerRole:
            item = index.internalPointer()
            return item.layer

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return super(LayerStackModel, self).flags(index)

        return (
            QtCore.Qt.ItemIsDragEnabled |
            QtCore.Qt.ItemIsDropEnabled |
            QtCore.Qt.ItemIsEnabled |
            QtCore.Qt.ItemIsSelectable
        )

    def supportedDropActions(self):
        return QtCore.Qt.MoveAction | QtCore.Qt.CopyAction

    def mimeData(self, indexes):
        mimedata = QtCore.QMimeData()

        entries = []
        for index in indexes:
            layer = index.data(self.LayerRole).identifier

            # Pass along the source parent we're moving *from* so we will
            # take it away from there
            parent = self.parent(index)
            if parent.isValid():
                parent_layer = parent.data(self.LayerRole).identifier
            else:
                parent_layer = self._stage.GetRootLayer().identifier

            entries.append((layer, parent_layer))

        text_data = "\n".join(
            "<----".join(str(x) for x in entry)
            for entry in entries
        )
        mimedata.setText(text_data)
        return mimedata

    def dropMimeData(self, data, action, row, column, parent):
        if action == QtCore.Qt.IgnoreAction:
            return True
        if column > 0:
            return False

        new_parent_layer = parent.data(self.LayerRole)
        if not new_parent_layer:
            raise RuntimeError(
                "Can't drop on index that does not refer to a layer"
            )

        # If urls are in the data we consider only those. These are usually
        # URLs from file drops from e.g. OS file explorer or alike.
        if data.hasUrls():
            for url in reversed(data.urls()):
                path = url.toLocalFile()
                if not path:
                    continue

                if not os.path.isfile(path):
                    # Ignore dropped folders
                    continue

                # We first try to find or open the layer so see if it's a valid
                # file format that way
                try:
                    Sdf.Layer.FindOrOpen(path)
                except Tf.ErrorException as exc:
                    log.error("Unable to drop unsupported file: %s",
                              path,
                              exc_info=exc)
                    continue

                if row == -1:
                    # Dropped on parent
                    new_parent_layer.subLayerPaths.append(path)
                else:
                    # Dropped in-between other layers
                    new_parent_layer.subLayerPaths.insert(row, path)
            return True

        if not data.hasFormat("text/plain"):
            return False

        # Consider plain text data second
        # TODO: This is likely better represented as a custom byte stream
        #   and as internal mimetype data to the model
        value = data.text()
        # Parse the text data
        separator = "<----"
        sources = []
        for line in value.split("\n"):
            if separator not in line:
                continue

            identifier, parent_identifier = line.split(separator, 1)
            if parent_identifier == "None":
                parent_identifier = None

            sources.append((identifier, parent_identifier))

        if not sources:
            return False

        with Sdf.ChangeBlock():
            for source_identifier, source_parent_identifier in sources:

                removed_index = None
                source_parent_layer = None
                if source_parent_identifier:
                    source_parent_layer = Sdf.Find(source_parent_identifier)
                    removed_index = remove_sublayer(
                        source_identifier, 
                        parent=source_parent_layer
                    )

                if row < 0 and column < 0:
                    # Dropped on parent, add dropped layer as child
                    new_parent_layer.subLayerPaths.append(source_identifier)
                else:
                    # Dropped in-between, insert dropped layer to that index
                    # If we removed the layer from the same parent and the
                    # original index is lower than the row we want to move to
                    # we must now "shift" the row because we have already
                    # removed the index before it
                    if (
                        source_parent_layer
                        and source_parent_layer.identifier == new_parent_layer.identifier  # noqa
                        and removed_index is not None and row >= removed_index
                    ):
                        row -= 1

                    new_parent_layer.subLayerPaths.insert(row, source_identifier)

        return True

    def mimeTypes(self):
        return ["text/plain", "text/uri-list"]

    def canDropMimeData(self, data, action, row, column, parent) -> bool:

        layer = parent.data(self.LayerRole)
        if layer is not None and layer == self._stage.GetSessionLayer():
            # Do not allow reparenting to session layers
            return False

        return super(LayerStackModel, self).canDropMimeData(data,
                                                            action,
                                                            row,
                                                            column,
                                                            parent)

    # endregion

    # region Custom methods
    def layer_count(self):
        """Return the number of layers in the current stage's layer stack."""
        return self.itemTree.item_count()

    def set_stage(self, stage):
        # type: (Usd.Stage) -> None
        """Reset the model from a new stage.

        Parameters
        ----------
        stage : Usd.Stage
        """
        if stage == self._stage:
            return

        self._stage = stage
        self.refresh()

    def register_listeners(self):
        stage = self._stage
        if stage and stage.GetPseudoRoot():
            if self._listeners:
                # Remove any existing listeners
                self.revoke_listeners()

            self.log.debug("Adding Tf.Notice Listeners..")
            # Listen to changes
            self._listeners.append(Tf.Notice.Register(
                Usd.Notice.LayerMutingChanged,
                self.on_layers_changed,
                self._stage
            ))
            self._listeners.append(Tf.Notice.Register(
                Usd.Notice.StageEditTargetChanged,
                self.on_layers_changed,
                self._stage
            ))

            # TODO: These should actually be listening per layer if possible
            #   meaning we'd setup a listener per layer instead to ensure
            #   we are not getting signals from other stages.
            self._listeners.append(Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayersDidChange,
                self.on_layers_changed,
            ))
            self._listeners.append(Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayerIdentifierDidChange,
                self.on_layers_changed,
            ))
            self._listeners.append(Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayerMutenessChanged,
                self.on_layers_changed,
            ))
            # TODO: Can we rely on this instead of `LayersDidChange`?
            # self._listeners.append(Tf.Notice.RegisterGlobally(
            #     Sdf.Notice.LayerDirtinessChanged,
            #     self.on_layers_changed,
            # ))

    def revoke_listeners(self):
        if self._listeners:
            self.log.debug("Revoking Tf.Notice listeners: %s", self._listeners)
            # Tf.Notice.Revoke(self._listeners)
            for listener in self._listeners:
                listener.Revoke()

        self._listeners.clear()

    @contextlib.contextmanager
    def reset_context(self):
        """Reset the model via context manager.

        During the context additional changes can be done before the reset
        of the model is 'finished', like e.g. changing Tf.Notice listeners.
        """
        self.beginResetModel()
        try:
            yield
        finally:
            self.endResetModel()

    def refresh(self):
        # Complete refresh on currently set stage
        with self.reset_context():
            item_tree = self.item_tree = ItemTree()
            stage = self._stage
            if not stage or not stage.GetPseudoRoot():
                return

            def add_layer(layer: Sdf.Layer, parent=None):
                parent_layers = parent.stack if parent else None
                layer_item = LayerItem(layer, parents=parent_layers)
                item_tree.add_items(layer_item, parent=parent)

                for sublayer_path in layer.subLayerPaths:
                    sublayer = Sdf.Layer.FindOrOpenRelativeToLayer(
                        layer, sublayer_path
                    )
                    add_layer(sublayer, parent=layer_item)

                return layer_item

            if self._include_session_layer:
                session_layer = stage.GetSessionLayer()
                if session_layer:
                    add_layer(session_layer)

            root_layer = stage.GetRootLayer()
            add_layer(root_layer)

    def on_layers_changed(self, notice, sender):
        self.log.debug("Received notice: %s", notice)

        # We schedule this with a slight delay because
        # `Sdf.Notice.LayersDidChange` will also get a notice if e.g. in Maya
        # an object is interactively moved around. We don't want to be
        # rebuilding the layer list then at all actually. But we need the
        # signal otherwise we can't detect layers added/removed to begin with.
        schedule(self.refresh, 50, channel="layerschanged")
    # endregion


class LayerWidget(QtWidgets.QWidget):
    """Widget for a single Sdf.layer of a Usd.Stage

    Used for the LayerEditorWidget's tree view as index widget.
    """

    set_edit_target = QtCore.Signal(Sdf.Layer)

    def __init__(self, layer, stage, parent=None):
        super(LayerWidget, self).__init__(parent=parent)

        layout = QtWidgets.QHBoxLayout(self)

        # When not enabled the layer is "muted" on the stage
        enabled = QtWidgets.QCheckBox(self)
        set_tips(enabled,
            "Mute layer\nDisabling the active state will mute the layer.\n"
            "You can not mute root or session layers of the USD stage."
        )

        # Identifier label as display name
        label = QtWidgets.QLabel("", parent=self)

        # Save changes button
        save = QtWidgets.QPushButton(get_icon("save"), "", self)
        set_tips(
            save, "Save layer to disk"
        )
        save.setFixedWidth(25)
        save.setFixedHeight(25)

        # Set edit target (active or not button)
        edit_target_btn = QtWidgets.QPushButton(get_icon("edit-2"), "", self)
        edit_target_btn.setCheckable(True)
        set_tips(
            edit_target_btn,
            "Set Edit Target\nAny changes made to the USD stage will be "
            "applied to the current edit target layer"
        )
        edit_target_btn.setFixedWidth(25)
        edit_target_btn.setFixedHeight(25)

        layout.addWidget(enabled)
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(save)
        layout.addWidget(edit_target_btn)

        self.layer = layer
        self.stage = stage

        # Store widgets
        self.edit_target = edit_target_btn
        self.save = save
        self.enabled = enabled
        self.label = label

        self.update()

        edit_target_btn.clicked.connect(self.on_set_edit_target)
        enabled.clicked.connect(self.on_mute_layer)
        save.clicked.connect(self.on_save_layer)

    def update(self):

        edit_target_btn = self.edit_target
        save = self.save
        enabled = self.enabled
        label = self.label
        layer = self.layer
        stage = self.stage

        is_layer_muted = stage.IsLayerMuted(layer.identifier)
        is_root_layer = stage.GetRootLayer() == layer
        is_session_layer = stage.GetSessionLayer() == layer

        label_str = layer.GetDisplayName()
        if layer.anonymous:
            label_str = f"<i>{label_str}</i>"  # make anonymous layers italic
        if layer.dirty:
            label_str = f"{label_str}*"  # add * character when dirty

        # update the widgets
        label.setText(label_str)
        label.setToolTip(layer.identifier)
        enabled.setChecked(not is_layer_muted)
        if is_root_layer or is_session_layer:
            enabled.setEnabled(False)
        save.setHidden(not layer.dirty)
        edit_target_btn.setEnabled(not is_layer_muted)
        edit_target_btn.setChecked(stage.GetEditTarget() == layer)

    def on_set_edit_target(self, state):
        if not state:
            # Disallow disabling it
            self.edit_target.blockSignals(True)
            self.edit_target.setChecked(True)
            self.edit_target.blockSignals(False)
            return

        layer = self.layer
        stage = self.stage

        # Propagate this signal upwards so that others can respond
        # to it, by disabling all other edit target push buttons. Usually
        # it should work fine with the `Tf.Notice` responding but in
        # Maya there's something about this that it does not like.
        self.set_edit_target.emit(layer)

        edit_target = stage.GetEditTargetForLocalLayer(layer)
        stage.SetEditTarget(edit_target)

    def on_mute_layer(self, enabled):
        if enabled:
            self.stage.UnmuteLayer(self.layer.identifier)
        else:
            self.stage.MuteLayer(self.layer.identifier)

    def on_save_layer(self):
        layer = self.layer
        # TODO: Perform an actual save
        # TODO: Prompt for filepath if layer is anonymous?
        # TODO: Allow making filepath relative to parent layer?
        log.debug(f"Saving: {layer}")
        layer.Save()
        # TODO: Do not update using this but base it off of signals from
        #  Sdf.Notice.LayerDidSaveLayerToFile
        self.update()


class LayerTreeWidget(QtWidgets.QWidget):
    def __init__(self, stage, include_session_layer=False, parent=None):
        super(LayerTreeWidget, self).__init__(parent=parent)

        model = LayerStackModel(stage=stage,
                                include_session_layer=include_session_layer)
        view = QtWidgets.QTreeView()
        view.setModel(model)

        view.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        view.setDragDropOverwriteMode(False)
        view.setColumnHidden(1, True)
        view.setHeaderHidden(True)
        view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        view.customContextMenuRequested.connect(
            self.on_view_context_menu
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(view)
        layout.setContentsMargins(0, 0, 0, 0)

        self.model = model
        self.view = view

        self._item_widgets = []

        self.refresh_widgets()

        model.modelReset.connect(self.refresh_widgets)

    def on_view_context_menu(self, point):
        """Generate a right mouse click context menu for the layer view"""

        index = self.view.indexAt(point)
        stage = self.model._stage
        layer = index.data(self.model.LayerRole)
        if not layer:
            layer = stage.GetRootLayer()

        menu = QtWidgets.QMenu(self.view)

        action = menu.addAction("Add layer")  # todo: maybe submenu?
        action.setToolTip(
            "Add a new sublayer under the selected parent layer."
        )
        action.triggered.connect(partial(self.on_add_layer, index))

        if layer:
            action = menu.addAction("Reload")
            action.setToolTip(
                "Reloads the layer. This discards any unsaved local changes."
            )
            action.setStatusTip(
                "Reloads the layer. This discards any unsaved local changes."
            )
            action.triggered.connect(lambda: layer.Reload())

            is_root_layer = layer == stage.GetRootLayer()
            is_session_layer = layer == stage.GetSessionLayer()

            if not is_root_layer and not is_session_layer:
                # TODO: implement remove callback - should remove from parent
                action = menu.addAction("Remove")
                action.setToolTip(
                    "Removes the layer from the layer stack. "
                    "Does not remove files from disk"
                )
                action.triggered.connect(partial(self.on_remove_layer, index))

            action = menu.addAction("Show as text")
            action.setToolTip(
                "Shows the layer as USD ASCII"
            )

            def show_layer_as_text():
                text_edit = QtWidgets.QTextEdit(parent=self)
                text_edit.setProperty("font-style", "monospace")
                text_edit.setPlainText(layer.ExportToString())
                text_edit.setWindowTitle(layer.identifier)
                text_edit.setWindowFlags(QtCore.Qt.Dialog)
                text_edit.resize(700, 500)
                text_edit.show()

            action.triggered.connect(show_layer_as_text)

            action = menu.addAction("Show diff")
            action.setToolTip(
                "Show a USD ASCII diff for the unsaved changes comparing "
                "to the layer on disk"
            )
            action.setEnabled(not layer.anonymous)

            def show_layer_diff():
                widget = LayerDiffWidget(
                    layer,
                    layer_a_label=f"{layer.identifier} (on disk)",
                    layer_b_label=f"{layer.identifier} (active)",
                    parent=self)
                widget.show()

            action.triggered.connect(show_layer_diff)

        menu.exec_(self.view.mapToGlobal(point))

    def refresh_widgets(self):

        # keep temporary reference, to avoid garbage collection of the widgets
        previous_widgets = self._item_widgets[:]  # noqa
        self._item_widgets.clear()

        for row in iter_model_rows(self.model, column=0):
            layer = row.data(self.model.LayerRole)
            if layer is None:
                log.warning(f"Layer is None for %s", row)
                continue
            widget = LayerWidget(layer=layer,
                                 stage=self.model._stage,
                                 parent=self)
            widget.setAutoFillBackground(True)
            widget.set_edit_target.connect(self.on_set_edit_target)
            self._item_widgets.append(widget)  # keep a reference
            self.view.setIndexWidget(row, widget)

        # Always keep expanded by default
        self.view.expandAll()

        del previous_widgets

    def on_set_edit_target(self, layer):
        # Update all widgets directly, don't wait around for a USD notice
        # event to propagate; this is to avoid some issues in Maya where
        # it seems that Maya also performs some own changes on an edit
        # target change and the change itself isn't detected correctly
        for widget in self._item_widgets:
            widget.edit_target.blockSignals(True)
            widget.edit_target.setChecked(layer == widget.layer)
            widget.edit_target.blockSignals(False)
            
    def on_remove_layer(self, index):
        parent_index = self.model.parent(index)
        
        layer = index.data(LayerStackModel.LayerRole)
        parent_layer = parent_index.data(LayerStackModel.LayerRole)
        if not layer or not parent_layer:
            return

        removed_index = remove_sublayer(layer.identifier, parent=parent_layer)
        if removed_index is not None:
            log.debug(f"Removed layer: {layer.identifier}")

    def on_add_layer(self, index):
        layer = index.data(LayerStackModel.LayerRole)
        if not layer:
            return

        filenames, _selected_filter = QtWidgets.QFileDialog.getOpenFileNames(
            parent=self,
            caption="Sublayer USD file",
            filter="USD (*.usd *.usda *.usdc);"
        )
        if not filenames:
            return

        # TODO: Anchor path relative to the layer?
        # TODO: Should we first confirm none of the layers is already a child
        #  or just let it error once it hits one matching path?
        for filename in filenames:
            log.debug("Adding sublayer: %s", filename)
            layer.subLayerPaths.append(filename)

    def showEvent(self, event):
        self.model.register_listeners()

    def hideEvent(self, event: QtGui.QCloseEvent) -> None:
        # TODO: This should be on a better event when we know the window
        #   will be gone and unused after. The `closeEvent` doesn't seem
        #   to trigger by default on closing a parent dialog?
        self.model.revoke_listeners()
