import collections
from collections.abc import Iterable


class ItemLookupError(Exception):
    pass


class TreeItem(object):
    """Formalized data structure of an item with a hashable key"""
    __slots__ = ('key',)

    def __init__(self, key):
        """
        Parameters
        ----------
        key : Hashable
            An identifier for this item. Must be unique within any trees it is
            added to.
        """
        self.key = key

    def __repr__(self):
        return '{0.__class__.__name__}({0.key!r})'.format(self)


class ItemTree(object):
    """A basic tree of hashable items, each of which can also be looked up
    using an associated key.
    """
    def __init__(self, root_item=None):
        """
        Parameters
        ----------
        root_item : Optional[TreeItem]
            Explicit item to use as the root of the tree. If omitted, a new
            `TreeItem` instance will be used.
        """
        if root_item is None:
            root_item = TreeItem('__ROOT__')
        else:
            self._validate_item_type(root_item)

        self._root = root_item
        self._parent_to_children = {root_item: self._make_initial_children_value(root_item)}  # type: Dict[TreeItem, List[TreeItem]]
        self._child_to_parent = {}  # type: Dict[TreeItem, TreeItem]
        self._key_to_item = {root_item.key: root_item}  # type: Dict[Hashable, TreeItem]

    def __contains__(self, item):
        return item in self._parent_to_children

    def _validate_item_type(self, item):
        pass

    @property
    def root(self):
        return self._root

    def is_empty(self):
        return len(self._parent_to_children) == 1

    def item_count(self):
        """Return the number of items in the tree, excluding the root item.

        Returns
        -------
        int
        """
        return len(self._parent_to_children) - 1

    def item_by_key(self, key):
        """Directly return an item by its associated key.

        Parameters
        ----------
        key : Hashable

        Returns
        -------
        TreeItem
        """
        try:
            return self._key_to_item[key]
        except KeyError:
            raise ItemLookupError('Given item key not in tree')

    def parent(self, item):
        """Return the given item's parent.

        Parameters
        ----------
        item : TreeItem

        Returns
        -------
        TreeItem
        """
        if item is self._root:
            raise ValueError('Root item has no parent')
        try:
            return self._child_to_parent[item]
        except KeyError:
            raise ItemLookupError('Given item {0!r} not in tree'.format(item))

    def _get_item_children(self, parent):
        """Internal method called to look up the children of the given parent
        item.

        If overridden by a subclass, this must return a (possibly empty) list of
        child items, or raise an ``ItemLookupError`` if the given parent is not
        part of the tree.

        Parameters
        ----------
        parent : TreeItem

        Returns
        -------
        List[TreeItem]
        """
        try:
            return self._parent_to_children[parent]
        except KeyError:
            raise ItemLookupError('Given parent {0!r} not in tree'.format(parent))

    def child_count(self, parent=None):
        """Return the number of items that are children of the given parent.

        This is useful mainly as a way to avoid the list copy associated with
        calling `len(self.Children())`.

        Parameters
        ----------
        parent : Optional[TreeItem]

        Returns
        -------
        int
        """
        if parent is None:
            parent = self._root
        return len(self._get_item_children(parent))

    def children(self, parent=None):
        """Return the list of immediate children under the given parent.

        Parameters
        ----------
        parent : Optional[TreeItem]
            If None, defaults to the root item.

        Returns
        -------
        List[TreeItem]
        """
        if parent is None:
            parent = self._root
        return list(self._get_item_children(parent))

    def iter_children(self, parent=None):
        """Return an iterator over the immediate children of the given parent.

        Parameters
        ----------
        parent : Optional[TreeItem]
            If None, defaults to the root item.

        Returns
        -------
        Iterator[TreeItem]
        """
        if parent is None:
            parent = self._root
        return iter(self._get_item_children(parent))

    def child_at_row(self, parent, row):
        """Return the given parent's child item at the given index.

        Parameters
        ----------
        parent : TreeItem
        row : int

        Returns
        -------
        TreeItem
        """
        return self._get_item_children(parent)[row]

    def row_index(self, item):
        """Return the index of the given item in its parent's list of children.

        Parameters
        ----------
        item : TreeItem

        Returns
        -------
        int
        """
        try:
            parent = self._child_to_parent[item]
        except KeyError:
            raise ItemLookupError('Given item {0!r} not in tree'.format(item))
        return self._get_item_children(parent).index(item)

    def _make_initial_children_value(self, parent):
        """Internal method called when adding new items to the tree to return
        the default value that should be added to `self.parentToChildren` for
        the given parent.

        The default simply returns an empty list.

        Parameters
        ----------
        parent : TreeItem

        Returns
        -------
        object
        """
        return []

    def add_items(self, items, parent=None):
        """Add one or more items to the tree, parented under `parent`, or the
        root item if `parent` is None.

        Parameters
        ----------
        items : Union[TreeItem, Iterable[TreeItem]]
        parent : Optional[TreeItem]

        Returns
        -------
        List[TreeItem]
            The newly added items from `items`.
        """
        if not items:
            return []
        if not isinstance(items, Iterable):
            items = [items]

        if parent is None:
            parent = self._root
        elif parent not in self._parent_to_children:
            raise ItemLookupError('Given parent {0!r} not in tree'.format(parent))

        newItems = []
        newKeys = set()
        for item in items:
            self._validate_item_type(item)
            if item not in self._child_to_parent:
                key = item.key
                if key in self._key_to_item:
                    raise ValueError('Item key shadows existing key '
                                     '{0!r}'.format(key))
                if key in newKeys:
                    raise ValueError('Duplicate incoming item key: '
                                     '{0!r}'.format(key))
                newKeys.add(key)
                newItems.append(item)

        makeChildrenValue = self._make_initial_children_value
        for item in newItems:
            self._key_to_item[item.key] = item
            self._parent_to_children[item] = makeChildrenValue(item)
            self._child_to_parent[item] = parent
        if self._parent_to_children[parent] is None:
            self._parent_to_children[parent] = []
        self._parent_to_children[parent].extend(newItems)

        return newItems

    def remove_items(self, items, childAction='delete'):
        """Remove one or more items (and optionally their children) from the
        tree.

        Parameters
        ----------
        items : Iterable[TreeItem]
        childAction : str
            {'delete', 'reparent'}
            The action to take for children of the items that will be removed.
            If this is 'reparent', any children of a given input item will be
            re-parented to that item's parent. If this is 'delete', any children
            of the input items will be deleted as well.

        Returns
        -------
        List[TreeItem]
            The removed items from `items`.
        """
        if childAction not in ('delete', 'reparent'):
            raise ValueError('Invalid child action: {0!r}'.format(childAction))
        if isinstance(items, Iterable):
            items = set(items)
        else:
            items = {items}

        items.discard(self._root)
        if not items:
            return []

        removed = []
        for item_to_delete in items:
            children = self._get_item_children(item_to_delete)
            if children:
                if childAction == 'delete':
                    # TODO: Can we get rid of this recursion?
                    removed.extend(
                        self.remove_items(children, childAction='delete')
                    )
                else:
                    newParent = self._child_to_parent[item_to_delete]
                    while newParent in items:
                        newParent = self._child_to_parent[newParent]
                    self._parent_to_children[newParent].extend(children)
                    self._child_to_parent.update((c, newParent) for c in children)

            itemParent = self._child_to_parent.pop(item_to_delete)
            self._parent_to_children[itemParent].remove(item_to_delete)
            self._key_to_item.pop(item_to_delete.key)
            del self._parent_to_children[item_to_delete]
            removed.append(item_to_delete)
        return removed

    def walk_items(self, startParent=None):
        """Walk down the tree from the given starting item (which defaults to
        the root), recursively yielding each child item in breadth-first order.

        Parameters
        ----------
        startParent : Optional[TreeItem]

        Returns
        -------
        Iterator[TreeItem]
        """
        if startParent is None:
            startParent = self._root
        stack = collections.deque(self._get_item_children(startParent))
        while stack:
            item = stack.popleft()
            stack.extend(self._get_item_children(item))
            yield item

    def iter_items(self):
        """Return an iterator over all of the key-item pairs in the tree, in an
        undefined order.

        Returns
        -------
        Iterator[Tuple[Hashable, TreeItem]]
        """
        return self._key_to_item.iteritems()


class LazyItemTree(ItemTree):
    """Basic implementation of an `ItemTree` subclass that can fetch each
    item's children lazily as they are requested.

    This is a pretty basic approach that uses None as a placeholder value for
    each item's entry in the parent-to-children mapping when they are first
    added. Then, the first time an item's children are actually requested, the
    internal method `self._FetchItemChildren` will be called with the item as an
    argument, and its result will be stored in the parent-to-children mapping.
    """
    def __init__(self, root_item=None):
        super(LazyItemTree, self).__init__(root_item=root_item)
        self.blockUpdates = False

    def _fetch_item_children(self, parent):
        """Called by `self._GetItemChildren` to actually fetch the child items
        for the given parent.

        This is called when the given parent's placeholder value in
        `self._parentToChildren` is set to None, and should return a (possibly
        empty) list of items.

        Parameters
        ----------
        parent : TreeItem

        Returns
        -------
        List[TreeItem]
        """
        raise NotImplementedError

    def _get_item_children(self, parent):
        children = super(LazyItemTree, self)._get_item_children(parent)
        if children is None:
            if self.blockUpdates:
                # Pretend there are no children without updating internal state.
                return []
            self._parent_to_children[parent] = []
            children = self._fetch_item_children(parent)
            if children:
                self.add_items(children, parent=parent)
        return children

    def _make_initial_children_value(self, parent):
        return None

    def forget_children(self, parent):
        """Recursively remove all children of the given parent from the tree,
        and reset its internal state so that `self._FetchItemChildren` will be
        called the next time its children are requested.

        Parameters
        ----------
        parent : TreeItem

        Returns
        -------
        List[TreeItem]
            All items removed from the tree as a result.
        """
        if parent in (None, self._root):
            raise ValueError('Cannot forget all direct children of the root '
                             'item. Maybe you just want a new tree instead?')
        self.blockUpdates = True
        try:
            children = super(LazyItemTree, self)._get_item_children(parent)
            if children:
                result = self.remove_items(children, childAction='delete')
            else:
                result = []
            self._parent_to_children[parent] = None
        finally:
            self.blockUpdates = False
        return result
