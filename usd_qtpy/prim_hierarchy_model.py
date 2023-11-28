import logging
import contextlib

from qtpy import QtCore
from pxr import Usd, Tf

from .lib.qt import report_error
from .lib.usd import rename_prim
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

        if role == self.PrimRole:
            return index.internalPointer()

        if role == DrawRectsDelegate.RectDataRole:
            prim = index.internalPointer()
            rects = []
            if prim == self.stage.GetDefaultPrim():
                rects.append(
                    {"text": "DFT",
                     "tooltip": "This prim is the default prim on "
                                "the stage's root layer.",
                     "background-color": "#553333"}
                )
            if prim.HasAuthoredPayloads() or prim.HasAuthoredReferences():
                rects.append(
                    {"text": "REF",
                     "tooltip": "This prim has one or more references "
                                "and/or payloads.",
                     "background-color": "#333355"},
                )
            if prim.HasVariantSets():
                rects.append(
                    {"text": "VAR",
                     "tooltip": "One or more variant sets exist on this prim.",
                     "background-color": "#335533"},
                )

            return rects
    # endregion