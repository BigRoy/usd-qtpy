from qtpy import QtWidgets, QtCore, QtGui


class DrawRectsDelegate(QtWidgets.QStyledItemDelegate):
    """Draws rounded rects 'tags' to the right hand side of items.

    The tags to be drawn should be returned by index's data via the
    BlockTagsRole on this class. The returned data should be a list
    with dicts defining each tag:
        {
            "text": "text",                  # text value in the block
            "background-color": "#FFFFFF",   # background color
            "color": "#FF9999"               # text color
        }

    These tags are clickable and will emit the `rect_clicked` event with
    the model's index and the `str` value of the tag.

    """

    RectDataRole = QtCore.Qt.UserRole + 1001

    rect_clicked = QtCore.Signal(QtCore.QEvent, QtCore.QModelIndex, dict)

    def iter_rects(self, blocks, option):
        """Yield each QRect used for drawing"""

        rect = QtCore.QRect(option.rect)
        padding_topbottom = 2
        padding_sides = 4
        width = 30
        for i, _block_data in enumerate(blocks):

            # Calculate left by computing offset from
            # right hand side to align right
            i = i + 1
            right = rect.right()
            left = right - (width * i) - (
                        2 * i * padding_sides) + padding_sides
            yield QtCore.QRect(left, rect.top() + padding_topbottom,
                               width, rect.height() - padding_topbottom * 2)

    def paint(self, painter, option, index):

        super(DrawRectsDelegate, self).paint(painter, option, index)

        corner_radius = 5
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        blocks = index.data(self.RectDataRole) or []

        for block_data, block_rect in zip(blocks, self.iter_rects(blocks,
                                                                  option)):

            text = block_data.get("text", "")
            background_color = QtGui.QColor(block_data.get("background-color",
                                                           "#FF9999"))
            text_color = QtGui.QColor(block_data.get("color", "#FFFFFF"))
            painter.setPen(text_color)

            # Draw the block rect
            path = QtGui.QPainterPath()
            path.addRoundedRect(block_rect, corner_radius, corner_radius)
            painter.fillPath(path, background_color)

            # Draw text in the block - vertically centered
            point = block_rect.topLeft()
            point.setY(point.y() + block_rect.height() * 0.5)

            painter.drawText(block_rect, QtCore.Qt.AlignCenter, text)

    def editorEvent(self, event, model, option, index) -> bool:
        if (
                isinstance(event, QtGui.QMouseEvent)
                and event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton
        ):
            blocks = index.data(self.RectDataRole) or []
            if blocks:
                point = event.position().toPoint()
                for block, rect in zip(blocks,
                                       self.iter_rects(blocks, option)):
                    if rect.contains(point):
                        self.rect_clicked.emit(event, index, block)
                        event.accept()
                        return True

        return super(DrawRectsDelegate, self).editorEvent(event,
                                                          model,
                                                          option,
                                                          index)

    def helpEvent(self,
                  event: QtGui.QHelpEvent,
                  view: QtWidgets.QAbstractItemView,
                  option: QtWidgets.QStyleOptionViewItem,
                  index: QtCore.QModelIndex) -> bool:
        if event.type() == QtCore.QEvent.ToolTip:

            blocks = index.data(self.RectDataRole) or []
            for block_data, block_rect in zip(blocks, self.iter_rects(blocks,
                                                                      option)):
                if block_rect.contains(event.pos()):
                    QtWidgets.QToolTip.showText(
                        event.globalPos(),
                        block_data.get("tooltip", ""),
                        view
                    )
                    return True

        return super(DrawRectsDelegate, self).helpEvent(event,
                                                        view,
                                                        option,
                                                        index)
