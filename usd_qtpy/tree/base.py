from qtpy import QtCore

from .itemtree import ItemTree

NULL_INDEX = QtCore.QModelIndex()


class AbstractTreeModelMixin(object):
    """Mixin class that implements the necessary methods for Qt model to reflect
    the structure of an ``ItemTree`` instance.
    """
    def __init__(self, item_tree=None, parent=None):
        """
        Parameters
        ----------
        item_tree : Optional[ItemTree]
        parent
        """
        super(AbstractTreeModelMixin, self).__init__(parent=parent)

        self.item_tree = None  # type: ItemTree
        self.set_item_tree(item_tree or ItemTree())

    # region Qt methods
    def hasChildren(self, parentIndex: QtCore.QModelIndex) -> bool:
        return bool(self.rowCount(parentIndex))

    def index(self,
              row: int,
              column: int,
              parent_index: QtCore.QModelIndex) -> QtCore.QModelIndex:
        if parent_index.isValid():
            parentItem = parent_index.internalPointer()
        else:
            parentItem = self.item_tree.root
        return self.item_index(row, column, parentItem)

    def parent(self, index: QtCore.QModelIndex) -> QtCore.QModelIndex:
        if index.isValid():
            parent = self.item_tree.parent(index.internalPointer())
            if parent is not self.item_tree.root:
                return self.createIndex(self.item_tree.row_index(parent), 0, parent)
        return NULL_INDEX

    def rowCount(self, parent_index: QtCore.QModelIndex) -> int:
        """Return number of child rows under the parent index."""
        if parent_index.column() > 0:
            return 0
        if parent_index.isValid():
            parent = parent_index.internalPointer()
        else:
            parent = self.item_tree.root
        return self.item_tree.child_count(parent=parent)
    # endregion

    # region Custom methods
    def set_item_tree(self, item_tree):
        """
        Parameters
        ----------
        item_tree : ItemTree
        """
        assert isinstance(item_tree, ItemTree)
        self.beginResetModel()
        self.item_tree = item_tree
        self.endResetModel()

    def item_index(self, row, column, parent_item):

        """
        Parameters
        ----------
        row : int
        column : int
        parent_item: TreeItem

        Returns
        -------
        QtCore.QModelIndex
        """
        try:
            child_item = self.item_tree.child_at_row(parent_item, row)
        except (KeyError, IndexError):
            return NULL_INDEX
        else:
            return self.createIndex(row, column, child_item)

    def get_item_index(self, item, column=0) -> QtCore.QModelIndex:
        """Return QModelIndex for a TreeItem"""
        return self.item_index(self.item_tree.row_index(item), column,
                               self.item_tree.parent(item))
    # endregion
