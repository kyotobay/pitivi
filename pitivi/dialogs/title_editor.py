# -*- coding: utf-8 -*-
# PiTiVi , Non-linear video editor
#
#       dialogs/title_editor.py
#
# Copyright (c) 2012, Jean-François Fortin Tam <nekohayo@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.

import gtk
import os

from gettext import gettext as _

from pitivi.configure import get_ui_dir
from pitivi.dialogs.title_editor_canvas import TitlePreview


def get_color(c):
    return (
        c.props.current_color.red_float,
        c.props.current_color.green_float,
        c.props.current_color.blue_float,
        c.props.current_alpha / 65535.0)


def set_color(c, t):
    c.props.current_color = gtk.gdk.Color(
        int(t[0] * 65535.0), int(t[1] * 65535.0), int(t[2] * 65535.0))
    c.props.current_alpha = int(t[3] * 65535.0)


# FIXME: this is not used anywhere
#alignments = [
#        (0.0, 0.0), (0.5, 0.0), (1.0, 0.0),
#        (0.0, 0.5), (0.5, 0.5), (1.0, 0.5),
#        (0.0, 1.0), (0.5, 1.0), (1.0, 1.0)]

class TitleEditorDialog(object):

    def __init__(self, app, **kw):
        # **kw means any extra optional keyword arguments.
        # Here, we get those properties (or fallback to a default)
        self.text = kw.get('text', _("Hello! ☃"))
        self.font = kw.get('font', 'Sans')
        self.text_size = kw.get('text_size', 64)
        self.bg_color = kw.get('bg_color', (0, 0, 0, 1))
        self.fg_color = kw.get('fg_color', (1, 1, 1, 1))
        # Other default settings:
        self.x_alignment = 0.5
        self.y_alignment = 0.5

        self.builder = gtk.Builder()
        self.builder.add_from_file(os.path.join(get_ui_dir(), "texteditor.ui"))
        self.builder.connect_signals(self)

        self.window = self.builder.get_object("title_editor")
        self.preview_frame = self.builder.get_object("preview_frame")

        self.preview = TitlePreview(text=self.text)
        self.preview_frame.add(self.preview)
        # TODO: set preview_frame's aspect ratio
        self.preview.set_size_request(400, 300)

        buffer = self.builder.get_object("textview").get_buffer()
        buffer.connect('changed', self._buffer_changed)

        # Hack: GladeWindow hides TitleEditDialog's run() with gtk.Dialog's;
        # undo that.
        # FIXME: is this still needed with gtkbuilder now?
#        del self.run

#    def _run_color_dialog(self, _button):
#        dialog = gtk.Dialog()
#        content_area = dialog.get_content_area()

#        fg_frame = gtk.Frame("Foreground color")
#        fg_color_selection = gtk.ColorSelection()
#        fg_color_selection.props.has_opacity_control = True
#        set_color(fg_color_selection, self.fg_color)

#        bg_frame = gtk.Frame("Background color")
#        bg_color_selection = gtk.ColorSelection()
#        bg_color_selection.props.has_opacity_control = True
#        set_color(bg_color_selection, self.bg_color)

#        fg_frame.add(fg_color_selection)
#        bg_frame.add(bg_color_selection)
#        content_area.pack_start(fg_frame, True)
#        content_area.pack_start(bg_frame, True)
#        dialog.add_button(gtk.STOCK_APPLY, gtk.RESPONSE_OK)
#        dialog.add_button(gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL)

#        dialog.show_all()
#        response = dialog.run()
#        dialog.destroy()

#        if response == gtk.RESPONSE_OK:
#            self.fg_color = get_color(fg_color_selection)
#            self.bg_color = get_color(bg_color_selection)

    def _buffer_changed(self, buffer):
        text = buffer.get_text(*buffer.get_bounds())
        self.preview.props.text = text

    def set(self, **kw):
        self.__dict__.update(kw)

    def _copy_to_dialog(self):
        buffer = self.builder.get_object("textview").props.buffer
        buffer.set_text(self.text)

    def _copy_from_dialog(self):
        buffer = self.builder.get_object("textview").props.buffer
        self.text = buffer.get_text(*buffer.get_bounds())

    def run(self):
        self._copy_to_dialog()
        self.window.show_all()
        response = gtk.Dialog.run(self.window)
        # In the glade file, we set the OK button's response ID to 1.
        # Cancel is 0. If the dialog is closed by some other way, we get -4.
        if response == 1:
            self._copy_from_dialog()
        self.window.destroy()
        return response
