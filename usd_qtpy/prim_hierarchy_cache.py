import logging
from typing import List, Dict

from pxr import Usd, Sdf


log = logging.getLogger(__name__)


class Proxy:
    def __init__(self, prim: Usd.Prim):
        self._prim: Usd.Prim = prim
        self._children: List[Sdf.Path] = []

    def refresh_children(self, predicate):
        self._children = [
            child_prim.GetPath()
            for child_prim in self._prim.GetFilteredChildren(predicate)
        ]

    def get_children(self) -> List[Sdf.Path]:
        return self._children

    def get_prim(self) -> Usd.Prim:
        return self._prim


class HierarchyCache:
    def __init__(self,
                 root: Usd.Prim,
                 predicate: Usd.PrimDefaultPredicate):
        self._predicate = predicate
        self._path_to_proxy: Dict[Sdf.Path, Proxy] = {}

        self._register_prim(root)
        self._root: Proxy = self._path_to_proxy[root.GetPath()]
        self._invalid_prim: Proxy = Proxy(Usd.Prim())

    def _register_prim(self, prim: Usd.Prim):
        path = prim.GetPath()
        if path not in self._path_to_proxy:
            proxy = Proxy(prim)
            self._path_to_proxy[path] = proxy
            proxy.refresh_children(self._predicate)

    @property
    def root(self) -> Proxy:
        return self._root

    @property
    def predicate(self):
        return self._predicate

    def __contains__(self, item) -> bool:
        return item in self._path_to_proxy

    def __getitem__(self, item):
        return self.get_proxy(item)

    def get_proxy(self, path: Sdf.Path) -> Proxy:
        return self._path_to_proxy[path]

    def get_child(self, proxy: Proxy, index: int) -> Proxy:
        if not proxy or not proxy.get_prim():
            return self._invalid_prim
        if index >= self.get_child_count(proxy):
            return self._invalid_prim

        child_path = proxy.get_children()[index]

        if child_path not in self._path_to_proxy:
            child_prim = proxy.get_prim().GetChild(child_path.name)
            self._register_prim(child_prim)

        return self._path_to_proxy[child_path]

    def get_parent(self, proxy: Proxy):
        prim = proxy.get_prim()
        path = prim.GetPath()
        parent_path = path.GetParentPath()
        return self._path_to_proxy[parent_path]

    def get_child_count(self, proxy: Proxy) -> int:
        if not proxy or not proxy.get_prim():
            return 0

        return len(proxy.get_children())

    def _invalidate_subtree(self, path: Sdf.Path):
        proxy = self._path_to_proxy.get(path)
        if proxy is not None:
            prim = proxy.get_prim()
            if prim.IsValid() and self.predicate(prim):
                for child in proxy.get_children():
                    self._invalidate_subtree(child)
                proxy.refresh_children(self.predicate)
            else:
                self._delete_subtree(path)
        else:
            log.debug("Skipping invalidation of uninstantiated path '%s'",
                      path.pathString)

    def _delete_subtree(self, path: Sdf.Path):
        if self._path_to_proxy.pop(path, None) is None:
            log.debug("Deleting instantiated path: '%s'", path)
        else:
            log.debug("Skipping deletion of uninstantiated path: '%s'", path)

    def resync_subtrees(self, paths: set[Sdf.Path]):
        root_path = Sdf.Path("/")
        if root_path in paths:
            # Resync all
            unique_parents = {root_path}
        else:
            unique_parents = {path.GetParentPath() for path in paths}

        for parent_path in unique_parents:
            proxy = self._path_to_proxy.get(parent_path)
            if not proxy:
                continue

            log.debug("Updating children of parent: '%s'", parent_path)
            original_children = set(proxy.get_children())
            proxy.refresh_children(self.predicate)
            new_children = set(proxy.get_children())

            for child_path in original_children.union(new_children):
                self._invalidate_subtree(child_path)

    def is_root(self, proxy):
        return self._root.get_prim() == proxy.get_prim()

    def get_row(self, proxy: Proxy) -> int:
        if not proxy:
            return 0

        if self.is_root(proxy):
            return 0

        parent_path = proxy.get_prim().GetPath().GetParentPath()
        parent = self._path_to_proxy[parent_path]

        prim = proxy.get_prim()
        path = prim.GetPath()
        return parent.get_children().index(path)