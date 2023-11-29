import contextlib
import difflib

from qtpy import QtWidgets, QtCore
from pxr import Sdf, Tf

from .lib.qt import DifflibSyntaxHighlighter


@contextlib.contextmanager
def preserve_scroll(scroll_area):
    """Preserve scrollbar positions by percentage after context."""
    def get_percent(scrollbar):
        value = scrollbar.value()
        minimum = scrollbar.minimum()
        maximum = scrollbar.maximum()
        if value <= minimum:
            return 0
        if value >= maximum:
            return 1
        if minimum == maximum:
            return 0
        return (value - minimum) / (maximum - minimum)

    def set_percent(scrollbar, percent):
        minimum = scrollbar.minimum()
        maximum = scrollbar.maximum()
        value = minimum + ((maximum - minimum) * percent)
        scrollbar.setValue(value)

    horizontal = scroll_area.horizontalScrollBar()
    h_percent = get_percent(horizontal)
    vertical = scroll_area.verticalScrollBar()
    v_percent = get_percent(vertical)
    try:
        yield
    finally:
        print(h_percent, v_percent)
        set_percent(horizontal, h_percent)
        set_percent(vertical, v_percent)


class LayerDiffWidget(QtWidgets.QDialog):
    """Simple layer ASCII diff text view"""
    # TODO: Add a dedicated 'toggle listen' and 'refresh' button to the widget
    #   so a user can only refresh e.g. when manually requested - especially
    #   since listing diffs can be slow (especially on large files)
    def __init__(self,
                 layer_a: Sdf.Layer,
                 layer_b: Sdf.Layer = None,
                 layer_a_label: str = None,
                 layer_b_label: str = None,
                 listen: bool = True,
                 parent: QtCore.QObject = None):
        super(LayerDiffWidget, self).__init__(parent=parent)

        self.setWindowTitle("USD Layer Diff")

        layout = QtWidgets.QVBoxLayout(self)
        text_edit = QtWidgets.QTextEdit()

        # Force monospace font for readability
        text_edit.setProperty("font-style", "monospace")
        text_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        highlighter = DifflibSyntaxHighlighter(text_edit)
        text_edit.setPlaceholderText("Layers match - no difference detected.")

        layout.addWidget(text_edit)

        if layer_b is None:
            # Load a clean copy (without unsaved changes) to compare with
            # its non-dirty state easily.
            layer_b = Sdf.Layer.OpenAsAnonymous(layer_a.identifier)
            # We will swap A/B around so that the layer from disk is the
            # "old" state in A
            layer_a, layer_b = layer_b, layer_a

        self._listen = listen
        self._text_edit = text_edit
        self._highlighter = highlighter
        self._layer_a = layer_a
        self._layer_b = layer_b
        self._layer_a_label = layer_a_label
        self._layer_b_label = layer_b_label
        self._listeners = []

        if not listen:
            self.refresh()

    def refresh(self):

        layer_a = self._layer_a
        layer_b = self._layer_b
        a_ascii = layer_a.ExportToString()
        b_ascii = layer_b.ExportToString()

        generator = difflib.unified_diff(
            a_ascii.splitlines(),
            b_ascii.splitlines(),
            fromfile=self._layer_a_label or f"{layer_a.identifier} (A)",
            tofile=self._layer_b_label or f"{layer_b.identifier} (B)",
            lineterm=""
        )

        with preserve_scroll(self._text_edit):
            self._text_edit.clear()
            for line in generator:
                self._text_edit.insertPlainText(f"{line}\n")

    def on_layers_changed(self, notice, sender):
        # TODO: We could also cache the ASCII of the USD files so that on
        #  layer change we only perform the `layer.ExportToString` on only the
        #  changed layer - optimizing this logic further.
        # TODO: Add a `schedule` call so that we delay the refresh ever so
        #  so slightly to avoid continuous refreshing when e.g. moving prims
        #  interactively in the viewport in Maya - we might want to put that
        #  behind a flag to toggle on/off to still allow interactive updates
        #  too
        self.refresh()

    def _register_listeners(self):

        self._listeners.append(Tf.Notice.Register(
            Sdf.Notice.LayersDidChangeSentPerLayer,
            self.on_layers_changed,
            self._layer_a
        ))

        self._listeners.append(Tf.Notice.Register(
            Sdf.Notice.LayersDidChangeSentPerLayer,
            self.on_layers_changed,
            self._layer_b
        ))

    def _revoke_listeners(self):
        for listener in self._listeners:
            listener.Revoke()
        self._listeners.clear()

    def showEvent(self, event):

        if self._listen:
            # Update whatever we missed while we were hidden
            # and re-attach any listeners
            self.refresh()
            self._register_listeners()

    def hideEvent(self, event):

        if self._listen:
            # Don't list while hidden
            self._revoke_listeners()
