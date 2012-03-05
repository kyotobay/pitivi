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

# TODO: stop updating last_x/last_y when pointer is outside widget
# TODO: set cursor to indicate draggability when over text item
# TODO: allow centering the text horizontally and vertically
# TODO: maintain right margin position when text is right aligned
# TODO: resize the text according to the scale % of the canvas (vs project resolution)
# TODO: calculate the canvas aspect ratio from project settings

import gobject
import goocanvas
import gtk
import pango

from gettext import gettext as _


def print_bounds(b):
    print '<(%r, %r) (%r, %r)>' % (b.x1, b.y1, b.x2, b.y2)


def text_size(text):
    ink, logical = text.get_natural_extents()
    x1, y1, x2, y2 = [pango.PIXELS(x) for x in logical]
    return x2 - x1, y2 - y1


class TitlePreview(gtk.EventBox):
    PADDING = 1

    __gproperties__ = {
        'text': (
            gobject.TYPE_STRING, 'text', 'text', ('Hello'),
            gobject.PARAM_READWRITE | gobject.PARAM_CONSTRUCT),
        'x': (
            gobject.TYPE_UINT, 'x position', 'x position', 0, 0xffff, 10,
            gobject.PARAM_READWRITE | gobject.PARAM_CONSTRUCT),
        'y': (
            gobject.TYPE_UINT, 'y position', 'y position', 0, 0xffff, 10,
            gobject.PARAM_READWRITE | gobject.PARAM_CONSTRUCT),
        'alignment': (
            gobject.TYPE_UINT, 'alignment', 'alignment', 0, 2, 0,
            gobject.PARAM_READWRITE | gobject.PARAM_CONSTRUCT),
    }

    def __init__(self, **kw):
        gtk.EventBox.__init__(self)
        self.add_events(
            gtk.gdk.BUTTON_PRESS_MASK |
            gtk.gdk.BUTTON_RELEASE_MASK |
            gtk.gdk.BUTTON1_MOTION_MASK)

        self.set_properties(**kw)
        self.last_x = None
        self.last_y = None

        self.canvas = goocanvas.Canvas()
        self.canvas.props.background_color = 'black'

        self.text_item = goocanvas.Text(
            fill_color_rgba=0xffffffff,
            x=self.PADDING,
            y=self.PADDING,
            font='Sans Bold 24',
            text=self.text)

        # TODO: Ideally we'd invert the colour underneath the outline.
        # The width and height don't need to be calculated here;
        # the "text" property being set will trigger the updateTextFrame method
        self.rect1 = goocanvas.Rect(
            stroke_color_rgba=0xffffffff,
            width=0,
            height=0,
            radius_x=0,
            radius_y=0)
        self.rect2 = goocanvas.Rect(
            stroke_color_rgba=0x000000ff,
            line_dash=goocanvas.LineDash([3.0, 3.0]),
            width=0,
            height=0,
            radius_x=0,
            radius_y=0)

        self.group = goocanvas.Group()
        self.group.add_child(self.rect1)
        self.group.add_child(self.rect2)
        self.group.add_child(self.text_item)
        root = self.canvas.get_root_item()
        root.add_child(self.group)
        self.add(self.canvas)

        #print (self.x, self.y)
        #print (self.group.get_bounds().x1, self.group.get_bounds().y1)
        self.group.translate(self.props.x, self.props.y)
        #print (self.group.get_bounds().x1, self.group.get_bounds().y1)

        self.connect('button-press-event', self.button_press)
        self.connect('button-release-event', self.button_release)
        self.connect('motion-notify-event', self.motion_notify)
        self.connect('size-allocate', lambda w, a: self.update_position(0, 0))

    def do_get_property(self, property):
        if property.name == 'text':
            return self.text
        elif property.name == 'x':
            return self.x
        elif property.name == 'y':
            return self.y
        elif property.name == 'alignment':
            return self.alignment
        else:
            raise AttributeError

    def do_set_property(self, property, value):
        """
        Handle additional things to be done when self's properties change.
        """
        # Use if clauses with "hasattr" to ensure that the property we're trying
        # to set really has a target object to receive it. This is necessary
        # because do_set_property may be called multiple times before the
        # canvas' widgets are even created.
        if property.name == 'text':
            self.text = value
            if hasattr(self, 'text_item'):
                self.text_item.props.text = value
                self.updateTextFrame()
                self.update_position(0, 0)
        elif property.name == 'x':
            # TODO: sync to canvas items
            self.x = value
        elif property.name == 'y':
            # TODO: sync to canvas items
            self.y = value
        elif property.name == 'alignment':
            self.alignment = value
            if hasattr(self, 'text_item'):
                self.text_item.props.alignment = value
        else:
            raise AttributeError(property.name)

    def button_press(self, widget, event):
        bounds = self.group.get_bounds()

        if ((bounds.x1 <= event.x <= bounds.x2) and
            (bounds.y1 <= event.y <= bounds.y2)):
            self.last_x = event.x
            self.last_y = event.y

        return False

    def button_release(self, widget, event):
        self.last_x = None
        self.last_y = None
        return False

    def motion_notify(self, widget, event):
        if self.last_x is None:
            return False

        dx = event.x - self.last_x
        dy = event.y - self.last_y
        self.update_position(dx, dy)
        self.last_x = event.x
        self.last_y = event.y

    def updateTextFrame(self):
        """
        Update rectangle sizes to match text.
        """
        text_w, text_h = text_size(self.text_item)
        self.rect1.props.width = text_w + 2 * self.PADDING
        self.rect1.props.height = text_h + 2 * self.PADDING
        self.rect2.props.width = text_w + 2 * self.PADDING
        self.rect2.props.height = text_h + 2 * self.PADDING

    def update_position(self, dx, dy):
        #print 'before', (dx, dy)
        alloc = self.canvas.get_allocation()
        canvas_bounds = goocanvas.Bounds(0, 0, alloc.width, alloc.height)
        group_bounds = self.group.get_bounds()
        #print_bounds(canvas_bounds)
        #print_bounds(group_bounds)
        canvas_width = canvas_bounds.x2 - canvas_bounds.x1
        canvas_height = canvas_bounds.y2 - canvas_bounds.y1
        group_width = group_bounds.x2 - group_bounds.x1
        group_height = group_bounds.y2 - group_bounds.y1

        if canvas_height == 1:
            # This happens when starting up. Avoid moving the text around
            # before we get a proper size allocation.
            return

        if group_width > canvas_width:
            dx = (canvas_width - group_width) / 2 - group_bounds.x1
        elif group_bounds.x1 + dx < canvas_bounds.x1:
            dx = canvas_bounds.x1 - group_bounds.x1
        elif group_bounds.x2 + dx > canvas_bounds.x2:
            dx = canvas_bounds.x2 - group_bounds.x2

        if group_height > canvas_height:
            dy = (canvas_height - group_height) / 2 - group_bounds.y1
        elif group_bounds.y1 + dy < canvas_bounds.y1:
            dy = canvas_bounds.y1 - group_bounds.y1
        elif group_bounds.y2 + dy > canvas_bounds.y2:
            dy = canvas_bounds.y2 - group_bounds.y2

        self.group.translate(dx, dy)
        #print 'after', (dx, dy)
        return False
