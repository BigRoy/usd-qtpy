import logging
import contextlib
from typing import Union, Optional

from qtpy import QtCore
from pxr import Usd, Sdf, Tf

from .lib.qt import report_error
from .lib.usd import rename_prim
from .prim_type_icons import PrimTypeIconProvider
from .prim_delegate import DrawRectsDelegate
from .prim_hierarchy_cache import HierarchyCache, Proxy


@contextlib.contextmanager
def layout_change_context(model: QtCore.QAbstractItemModel):
    """Context manager to ensure model layout changes are propagated if an
    exception is thrown.
    """
    model.layoutAboutToBeChanged.emit()
    try:
        yield
    finally:
        model.layoutChanged.emit()


class HierarchyModel(QtCore.QAbstractItemModel):
    """Base class for adapting a stage's prim hierarchy for Qt ItemViews

    Most clients will want to use a configuration of the `HierachyStandardModel`
    which has a standard set of columns and data or subclass this to provide
    their own custom set of columns.

    Clients are encouraged to subclass this module because it provides both
    robust handling of change notification and an efficient lazy population.
    This model listens for TfNotices and emits the appropriate Qt signals.
    """
    PrimRole = QtCore.Qt.UserRole + 1

    def __init__(
        self,
        stage: Usd.Stage=None,
        predicate=Usd.TraverseInstanceProxies(Usd.PrimIsDefined |
                                              ~Usd.PrimIsDefined),
        parent=None,
    ) -> None:
        """Instantiate a QAbstractItemModel adapter for a UsdStage.

        It's safe for the 'stage' to be None if the model needs to be
        instantiated without knowing the stage its interacting with.

        'predicate' specifies the prims that may be accessed via the model on
        the stage. A good policy is to be as accepting of prims as possible
        and rely on a QSortFilterProxyModel to interactively reduce the view.
        Changing the predicate is a potentially expensive operation requiring
        rebuilding internal caches, making not ideal for interactive filtering.
        """
        super(HierarchyModel, self).__init__(parent=parent)

        self._predicate = predicate
        self._stage = None
        self._index: Union[None, HierarchyCache] = None
        self._listeners = []
        self._icon_provider = PrimTypeIconProvider()
        self.log = logging.getLogger("HierarchyModel")

        # Set stage
        self.set_stage(stage)

    @property
    def stage(self):
        return self._stage

    @stage.setter
    def stage(self, stage):
        self.set_stage(stage)

    def set_stage(self, stage: Usd.Stage):
        """Resets the model for use with a new stage.

        If the stage isn't valid, this effectively becomes an empty model.
        """
        if stage == self._stage:
            return

        self.revoke_listeners()

        self._stage = stage
        with self.reset_model():
            if self._is_stage_valid():
                self._index = HierarchyCache(
                    root=stage.GetPrimAtPath("/"),
                    predicate=self._predicate
                )
                self.register_listeners()
            else:
                self._index = None

    def _is_stage_valid(self):
        return self._stage and self._stage.GetPseudoRoot()

    def register_listeners(self):
        """Register Tf.Notice listeners"""

        if self._listeners:
            # Do not allow to register more than once, clear old listeners
            self.revoke_listeners()

        if self._is_stage_valid():
            # Listen to state changes of the stage to stay in sync
            self._listeners.append(Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self.on_objects_changed,
                self._stage
            ))

    def revoke_listeners(self):
        """Revoke Tf.Notice listeners"""
        for listener in self._listeners:
            listener.Revoke()
        self._listeners.clear()

    @contextlib.contextmanager
    def reset_model(self):
        """Reset the model via context manager.

        During the context additional changes can be done before the reset
        of the model is 'finished', like e.g. changing Tf.Notice listeners.
        """
        self.beginResetModel()
        try:
            yield
        finally:
            self.endResetModel()

    @report_error
    def on_objects_changed(self, notice, sender):
        resynced_paths = notice.GetResyncedPaths()
        resynced_paths = {
            path for path in resynced_paths if path.IsPrimPath()
            # Also include the absolute root path (e.g. layer muting)
            or path.IsAbsoluteRootPath()
        }
        if not resynced_paths:
            return

        # Include parents so we can use it as lookup for the "sibling" check
        resynced_paths_and_parents = resynced_paths.copy()
        resynced_paths_and_parents.update(
            path.GetParentPath() for path in list(resynced_paths)
        )
        with layout_change_context(self):
            persistent_indices = self.persistentIndexList()
            index_to_path = {}
            for index in persistent_indices:
                index_prim = index.internalPointer().get_prim()
                index_path = index_prim.GetPath()
                if (
                        index_path in resynced_paths_and_parents
                        or index_path.GetParentPath() in resynced_paths_and_parents
                ):
                    index_to_path[index] = index_path

            self._index.resync_subtrees(resynced_paths)

            from_indices = []
            to_indices = []
            for index in index_to_path:
                path = index_to_path[index]

                if path in self._index:
                    new_proxy = self._index.get_proxy(path)
                    new_row = self._index.get_row(new_proxy)

                    if index.row() != new_row:
                        for _i in range(
                            self.columnCount(QtCore.QModelIndex())
                        ):
                            from_indices.append(index)
                            to_indices.append(self.createIndex(
                                new_row, index.column(), new_proxy)
                            )
                else:
                    from_indices.append(index)
                    to_indices.append(QtCore.QModelIndex())
            self.changePersistentIndexList(from_indices, to_indices)

    def _prim_to_row_index(self,
                           path: Sdf.Path) -> Optional[QtCore.QModelIndex]:
        """Given a path, retrieve the appropriate model index."""
        if path in self._index:
            proxy = self._index[path]
            row = self._index.get_row(proxy)
            return self.createIndex(row, 0, proxy)

    def _index_to_prim(self,
                       model_index: QtCore.QModelIndex) -> Optional[Usd.Prim]:
        """Retrieve the prim for the input model index

        External clients should use `UsdQt.roles.HierarchyPrimRole` to access
        the prim for an index.
        """
        if model_index.isValid():
            proxy = model_index.internalPointer()  # -> Proxy
            if type(proxy) is Proxy:
                return proxy.get_prim()

    # region Qt methods
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
                prim = self._index_to_prim(index)
                if not value:
                    # Keep original name
                    return False

                rename_prim(prim, value)
                return True

        return super(HierarchyModel, self).setData(index, value, role)

    def columnCount(self, parent):
        return 1

    def rowCount(self, parent):
        if not self._is_stage_valid():
            return 0

        if parent.column() > 0:
            return 0

        if not parent.isValid():
            return 1

        parent_proxy = parent.internalPointer()
        return self._index.get_child_count(parent_proxy)

    def index(self, row, column, parent):
        if not self._is_stage_valid():
            return QtCore.QModelIndex()

        if not self.hasIndex(row, column, parent):
            self.log.debug("Index does not exist: %s %s %s", row, column, parent)
            return QtCore.QModelIndex()

        if not parent.isValid():
            # We assume the root has already been registered.
            root = self._index.root
            return self.createIndex(row, column, root)

        parent_proxy = parent.internalPointer()
        child = self._index.get_child(parent_proxy, row)
        return self.createIndex(row, column, child)

    def parent(self, index):
        if not self._is_stage_valid():
            return QtCore.QModelIndex()

        if not index.isValid():
            return QtCore.QModelIndex()

        proxy = index.internalPointer()
        if proxy is None:
            return QtCore.QModelIndex()

        if self._index.is_root(proxy):
            return QtCore.QModelIndex()

        parent_proxy = self._index.get_parent(proxy)
        parent_row = self._index.get_row(parent_proxy)
        return self.createIndex(parent_row, index.column(), parent_proxy)

    def data(self, index, role):
        if not self._is_stage_valid():
            return

        if not index.isValid():
            return

        if role == QtCore.Qt.DisplayRole or role == QtCore.Qt.EditRole:
            prim = index.internalPointer().get_prim()
            return prim.GetName()

        if role == QtCore.Qt.DecorationRole:
            # icon
            prim = index.internalPointer().get_prim()
            return self._icon_provider.get_icon(prim)

        if role == QtCore.Qt.ToolTipRole:
            prim = index.internalPointer().get_prim()
            return prim.GetTypeName()

        if role == self.PrimRole:
            return index.internalPointer().get_prim()

        if role == DrawRectsDelegate.RectDataRole:
            prim = index.internalPointer().get_prim()
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
