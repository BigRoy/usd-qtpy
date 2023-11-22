import logging

from pxr import Usd, Tf, Sdf
from PySide2 import QtCore, QtWidgets, QtGui

from .lib.qt import schedule
from .lib.usd import remove_spec, LIST_ATTRS


log = logging.getLogger(__name__)


# See: https://github.com/PixarAnimationStudios/OpenUSD/blob/release/pxr/usd/sdf/fileIO_Common.cpp#L879-L892
SPECIFIER_LABEL = {
    Sdf.SpecifierDef: "def",
    Sdf.SpecifierOver: "over",
    Sdf.SpecifierClass: "abstract"
}


def shorten(s, width, placeholder="..."):
    """Shorten string to `width`"""
    if len(s) <= width:
        return s
    return "{}{}".format(s[:width], placeholder)


class TreeModel(QtCore.QAbstractItemModel):
    Columns = list()
    ItemRole = QtCore.Qt.UserRole + 1

    def __init__(self, parent=None):
        super(TreeModel, self).__init__(parent)
        self._root_item = Item()

    def rowCount(self, parent=None):
        if parent is None or not parent.isValid():
            parent_item = self._root_item
        else:
            parent_item = parent.internalPointer()
        return parent_item.childCount()

    def columnCount(self, parent):
        return len(self.Columns)

    def data(self, index, role):
        if not index.isValid():
            return None

        if role == QtCore.Qt.DisplayRole:
            item = index.internalPointer()
            column = index.column()

            key = self.Columns[column]
            return item.get(key, None)

        if role == self.ItemRole:
            return index.internalPointer()

    def setColumns(self, keys):
        assert isinstance(keys, (list, tuple))
        self.Columns = keys

    def headerData(self, section, orientation, role):

        if role == QtCore.Qt.DisplayRole:
            if section < len(self.Columns):
                return self.Columns[section]
        return

        return super(TreeModel, self).headerData(section, orientation, role)

    def flags(self, index):
        flags = QtCore.Qt.ItemIsEnabled

        item = index.internalPointer()
        if item.get("enabled", True):
            flags |= QtCore.Qt.ItemIsSelectable

        return flags

    def parent(self, index):

        item = index.internalPointer()
        parent_item = item.parent()

        # If it has no parents we return invalid
        if parent_item == self._root_item or not parent_item:
            return QtCore.QModelIndex()

        return self.createIndex(parent_item.row(), 0, parent_item)

    def index(self, row, column, parent=None):
        """Return index for row/column under parent"""

        if parent is None or not parent.isValid():
            parent_item = self._root_item
        else:
            parent_item = parent.internalPointer()

        child_item = parent_item.child(row)
        if child_item:
            return self.createIndex(row, column, child_item)
        else:
            return QtCore.QModelIndex()

    def add_child(self, item, parent=None):
        if parent is None:
            parent = self._root_item

        parent.add_child(item)

    def column_name(self, column):
        """Return column key by index"""

        if column < len(self.Columns):
            return self.Columns[column]

    def clear(self):
        self.beginResetModel()
        self._root_item = Item()
        self.endResetModel()


class Item(dict):
    """An item that can be represented in a tree view using `TreeModel`.

    The item can store data just like a regular dictionary.

    >>> data = {"name": "John", "score": 10}
    >>> item = Item(data)
    >>> assert item["name"] == "John"

    """

    def __init__(self, data=None):
        super(Item, self).__init__()

        self._children = list()
        self._parent = None

        if data is not None:
            assert isinstance(data, dict)
            self.update(data)

    def childCount(self):
        return len(self._children)

    def child(self, row):

        if row >= len(self._children):
            log.warning("Invalid row as child: %s", row)
            return

        return self._children[row]

    def children(self):
        return self._children

    def parent(self):
        return self._parent

    def row(self):
        """
        Returns:
             int: Index of this item under parent"""
        if self._parent is not None:
            siblings = self.parent().children()
            return siblings.index(self)
        return -1

    def add_child(self, child):
        """Add a child to this item"""
        child._parent = self
        self._children.append(child)


class StageSdfModel(TreeModel):
    Columns = [
        "name", "specifier", "typeName", "default", "type",
        # "variantSelections", "variantSetNameList", "variantSets",
        # "referenceList", "payloadList", "relocates"
    ]

    Colors = {
        "Layer": QtGui.QColor("#008EC5"),
        "PseudoRootSpec": QtGui.QColor("#A2D2EF"),
        "PrimSpec": QtGui.QColor("#A2D2EF"),
        "RelationshipSpec": QtGui.QColor("#FCD057"),
        "AttributeSpec": QtGui.QColor("#FFC8DD"),
    }

    def __init__(self, stage=None, parent=None):
        super(StageSdfModel, self).__init__(parent)
        self._stage = stage

        from .prim_hierarchy import PrimTypeIconProvider
        self._icon_provider = PrimTypeIconProvider()

    def setStage(self, stage):
        self._stage = stage

    def refresh(self):
        self.clear()

        stage = self._stage
        if not stage:
            return

        for layer in stage.GetLayerStack():

            layer_item = Item({
                "name": layer.GetDisplayName(),
                "identifier": layer.identifier,
                "specifier": None,
                "type": layer.__class__.__name__
            })
            self.add_child(layer_item)

            items_by_path = {}

            def _traverse(path):
                spec = layer.GetObjectAtPath(path)
                if not spec:
                    # ignore target list binding entries
                    items_by_path[path] = Item({
                        "name": path.elementString,
                        "path": path,
                        "type": path.__class__.__name__
                    })
                    return

                icon = None
                spec_item = Item({
                    "name": spec.name,
                    "spec": spec,
                    "path": path,
                    "type": spec.__class__.__name__
                })

                if hasattr(spec, "GetTypeName"):
                    spec_type_name = spec.GetTypeName()
                    icon = self._icon_provider.get_icon_from_type_name(
                        spec_type_name)
                    if icon:
                        spec_item["icon"] = icon

                if isinstance(spec, Sdf.PrimSpec):
                    if not icon:
                        # If the current layer doesn't specify a type, e.g.
                        # it is an "Over" but another layer does specify
                        # a type, then use that type instead
                        prim = stage.GetPrimAtPath(path)
                        if prim:
                            icon = self._icon_provider.get_icon(prim)
                            if icon:
                                spec_item["icon"] = icon

                    spec_item["specifier"] = SPECIFIER_LABEL.get(
                        spec.specifier
                    )
                    type_name = spec.typeName
                    spec_item["typeName"] = type_name

                    # TODO: Implement some good UX for variants, references,
                    #  payloads and relocates
                    # "variantSelections",
                    # "variantSets",
                    # for variant_selection in spec.variantSelections:
                    #    selection_item = Item({
                    #        "name": "TEST",
                    #        "type": "variantSelection"
                    #    })
                    #    spec_item.add_child(selection_item)

                    for key in [
                        #"variantSetName",  # todo: these don't have `.assetPath`
                        "reference",
                        "payload"
                    ]:
                        list_changes = getattr(spec, key + "List")
                        for change_type in LIST_ATTRS:
                            changes_for_type = getattr(list_changes,
                                                       change_type)
                            for change in changes_for_type:
                                list_change_item = Item({
                                    "name": change.assetPath,
                                    # Strip off "Items"
                                    "default": change_type[:-5],
                                    "type": key
                                })
                                spec_item.add_child(list_change_item)
                        if list_changes:
                            spec_item[key] = str(list_changes)

                elif isinstance(spec, Sdf.AttributeSpec):
                    spec_item["default"] = shorten(str(spec.default), 60)

                items_by_path[path] = spec_item

            layer.Traverse("/", _traverse)

            # Build hierarchy of item of specs
            for path, item in sorted(items_by_path.items()):
                parent = path.GetParentPath()
                parent_item = items_by_path.get(parent, layer_item)
                parent_item.add_child(item)

    def data(self, index, role):

        if role == QtCore.Qt.ForegroundRole:
            item = index.data(TreeModel.ItemRole)
            class_type_name = item.get("type")
            color = self.Colors.get(class_type_name)
            return color

        if index.column() == 2 and role == QtCore.Qt.DecorationRole:
            item = index.data(TreeModel.ItemRole)
            return item.get("icon")

        return super(StageSdfModel, self).data(index, role)


class Proxy(QtCore.QSortFilterProxyModel):

    def __init__(self, *args, **kwargs):
        super(Proxy, self).__init__(*args, **kwargs)
        self._filter_types = {"RelationshipSpec"}

    def set_types_filter(self, types):
        self._filter_types = set(types)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if not index.isValid():
            return False

        item = index.data(TreeModel.ItemRole)
        item_type = item.get("type")
        if (
                self._filter_types
                and item_type
                and item_type not in self._filter_types
        ):
            return False

        return super(Proxy, self).filterAcceptsRow(source_row, source_parent)


class FilterListWidget(QtWidgets.QListWidget):
    def __init__(self):
        super(FilterListWidget, self).__init__()
        self.addItems([
            "Layer",
            "PseudoRootSpec",
            "PrimSpec",
            "AttributeSpec",
            "RelationshipSpec",

            # PrimSpec changes
            "variantSetName",
            "reference",
            "payload",

            "variantSelections",
            "variantSets",
            "relocates"
        ])
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)


class SpecEditorWindow(QtWidgets.QDialog):
    def __init__(self, stage, parent=None):
        super(SpecEditorWindow, self).__init__(parent=parent)

        self.setWindowTitle("USD Layer Spec Editor")

        layout = QtWidgets.QVBoxLayout(self)
        self.setContentsMargins(0, 0, 0, 0)
        splitter = QtWidgets.QSplitter()

        filter_list = FilterListWidget()
        filter_list.itemSelectionChanged.connect(
            self._on_filter_selection_changed
        )

        editor = SpecEditsWidget(stage)

        splitter.addWidget(filter_list)
        splitter.addWidget(editor)
        splitter.setSizes([100, 700])
        layout.addWidget(splitter)

        self.editor = editor
        self.filter_list = filter_list

    def _on_filter_selection_changed(self):
        items = self.filter_list.selectedItems()
        types = {item.text() for item in items}
        self.editor.proxy.set_types_filter(types)
        self.editor.view.expandAll()


class SpecEditsWidget(QtWidgets.QWidget):
    def __init__(self, stage=None, parent=None):
        super(SpecEditsWidget, self).__init__(parent=parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        filter_edit = QtWidgets.QLineEdit()
        filter_edit.setPlaceholderText("Filter")

        model = StageSdfModel(stage)
        proxy = Proxy()
        proxy.setRecursiveFilteringEnabled(True)
        proxy.setSourceModel(model)
        view = QtWidgets.QTreeView()
        view.setModel(proxy)
        view.setIndentation(10)
        view.setIconSize(QtCore.QSize(20, 20))
        view.setStyleSheet(
            "QTreeView::item { height: 20px; padding: 0px; margin: 1px 5px 1px 5px; }")
        view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        view.setUniformRowHeights(True)

        auto_refresh = QtWidgets.QCheckBox("Auto Refresh on Stage Changes")
        auto_refresh.setChecked(True)
        refresh = QtWidgets.QPushButton("Refresh")
        delete = QtWidgets.QPushButton("Delete")

        layout.addWidget(filter_edit)
        layout.addWidget(view)
        layout.addWidget(auto_refresh)
        layout.addWidget(refresh)
        layout.addWidget(delete)

        self.filter_edit = QtWidgets
        self.auto_refresh = auto_refresh
        self.model = model
        self.proxy = proxy
        self.view = view

        auto_refresh.stateChanged.connect(self.set_refresh_on_changes)
        refresh.clicked.connect(self.on_refresh)
        delete.clicked.connect(self.on_delete)
        filter_edit.textChanged.connect(self.on_filter_changed)

        self._listeners = []

        self.set_refresh_on_changes(True)
        self.on_refresh()

    def set_refresh_on_changes(self, state):
        if state:
            if self._listeners:
                return
            log.debug("Adding Prim Spec listener")
            sender = self.model._stage
            listener = Tf.Notice.Register(Usd.Notice.StageContentsChanged,
                                          self.on_stage_changed_notice,
                                          sender)
            self._listeners.append(listener)
        else:
            if not self._listeners:
                return
            log.debug("Removing Prim Spec listeners")
            for listener in self._listeners:
                listener.Revoke()
            self._listeners.clear()

    def on_stage_changed_notice(self, notice, sender):
        self.proxy.invalidate()
        schedule(self.on_refresh, 100, channel="changes")

    def on_filter_changed(self, text):
        self.proxy.setFilterRegularExpression(".*{}.*".format(text))
        self.proxy.invalidateFilter()
        self.view.expandAll()

    def showEvent(self, event):
        state = self.auto_refresh.checkState() == QtCore.Qt.Checked
        self.set_refresh_on_changes(state)

    def hideEvent(self, event):
        # Remove any callbacks if they exist
        self.set_refresh_on_changes(False)

    def on_refresh(self):
        self.model.refresh()
        self.proxy.invalidate()
        self.view.resizeColumnToContents(0)
        self.view.expandAll()
        self.view.resizeColumnToContents(1)
        self.view.resizeColumnToContents(2)
        self.view.resizeColumnToContents(3)
        self.view.resizeColumnToContents(4)

    def on_delete(self):
        selection_model = self.view.selectionModel()
        rows = selection_model.selectedRows()
        specs = []
        for row in rows:
            item = row.data(TreeModel.ItemRole)
            spec = item.get("spec")
            if item.get("type") == "PseudoRootSpec":
                continue

            if spec:
                specs.append(spec)

        if not specs:
            return

        with Sdf.ChangeBlock():
            for spec in specs:
                print(f"Removing spec: {spec.path}")
                remove_spec(spec)

        if not self._listeners:
            self.on_refresh()
