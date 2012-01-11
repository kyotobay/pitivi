# PiTiVi , Non-linear video editor
#
#       pitivi/ui/timeline.py
#
# Copyright (c) 2005, Edward Hervey <bilboed@bilboed.com>
# Copyright (c) 2009, Brandon Lewis <brandon_lewis@berkeley.edu>
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
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""
    Main Timeline widgets
"""

import gtk
import gst
import ges
import ruler
import gobject
import goocanvas

from gettext import gettext as _

from pitivi.check import soft_deps
from pitivi.effects import AUDIO_EFFECT, VIDEO_EFFECT
from pitivi.autoaligner import AlignmentProgressDialog

from pitivi.settings import GlobalSettings

from curve import KW_LABEL_Y_OVERFLOW
from track import TrackControls, TRACK_CONTROL_WIDTH, Track, TrackObject
from pitivi.utils.timeline import Controller, MoveContext, SELECT, Zoomable

from pitivi.ui.depsmanager import DepsManager
from pitivi.ui.filelisterrordialog import FileListErrorDialog
from pitivi.ui.prefs import PreferencesDialog

from pitivi.utils.receiver import receiver, handler
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import SPACING, TRACK_SPACING, LAYER_HEIGHT_EXPANDED,\
    LAYER_SPACING, TYPE_PITIVI_FILESOURCE, VIDEO_EFFECT_TUPLE, \
    AUDIO_EFFECT_TUPLE, EFFECT_TUPLE, FILESOURCE_TUPLE, TYPE_PITIVI_EFFECT, \
    unpack_cairo_pattern, Point

# FIXME GES Port regression
# from pitivi.utils.align import AutoAligner

GlobalSettings.addConfigOption('edgeSnapDeadband',
    section="user-interface",
    key="edge-snap-deadband",
    default=5,
    notify=True)

PreferencesDialog.addNumericPreference('edgeSnapDeadband',
    section=_("Behavior"),
    label=_("Snap distance"),
    description=_("Threshold (in pixels) at which two clips will snap together "
        "when dragging or trimming."),
    lower=0)


# cursors to be used for resizing objects
ARROW = gtk.gdk.Cursor(gtk.gdk.ARROW)
# TODO: replace this with custom cursor
PLAYHEAD_CURSOR = gtk.gdk.Cursor(gtk.gdk.SB_H_DOUBLE_ARROW)

# Drag and drop constants/tuples
# FIXME, rethink the way we handle that as it is quite 'hacky'
DND_EFFECT_LIST = [[VIDEO_EFFECT_TUPLE[0], EFFECT_TUPLE[0]],\
                  [AUDIO_EFFECT_TUPLE[0], EFFECT_TUPLE[0]]]
VIDEO_EFFECT_LIST = [VIDEO_EFFECT_TUPLE[0], EFFECT_TUPLE[0]],
AUDIO_EFFECT_LIST = [AUDIO_EFFECT_TUPLE[0], EFFECT_TUPLE[0]],

# tooltip text for toolbar
DELETE = _("Delete Selected")
SPLIT = _("Split clip at playhead position")
KEYFRAME = _("Add a keyframe")
PREVFRAME = _("Move to the previous keyframe")
NEXTFRAME = _("Move to the next keyframe")
ZOOM_IN = _("Zoom In")
ZOOM_OUT = _("Zoom Out")
ZOOM_FIT = _("Zoom Fit")
UNLINK = _("Break links between clips")
LINK = _("Link together arbitrary clips")
UNGROUP = _("Ungroup clips")
GROUP = _("Group clips")
ALIGN = _("Align clips based on their soundtracks")
SELECT_BEFORE = ("Select all sources before selected")
SELECT_AFTER = ("Select all after selected")

ui = '''
<ui>
    <menubar name="MainMenuBar">
        <menu action="View">
            <placeholder name="Timeline">
                <menuitem action="ZoomIn" />
                <menuitem action="ZoomOut" />
                <menuitem action="ZoomFit" />
            </placeholder>
        </menu>
        <menu action="Timeline">
            <placeholder name="Timeline">
                <menuitem action="Split" />
                <menuitem action="Keyframe" />
                <separator />
                <menuitem action="DeleteObj" />
                <menuitem action="LinkObj" />
                <menuitem action="UnlinkObj" />
                <menuitem action="GroupObj" />
                <menuitem action="UngroupObj" />
                <menuitem action="AlignObj" />
                <separator />
                <menuitem action="Prevframe" />
                <menuitem action="Nextframe" />
            </placeholder>
        </menu>
    </menubar>
    <toolbar name="TimelineToolBar">
        <placeholder name="Timeline">
            <separator />
            <toolitem action="Split" />
            <toolitem action="Keyframe" />
            <separator />
            <toolitem action="DeleteObj" />
            <toolitem action="UnlinkObj" />
            <toolitem action="LinkObj" />
            <toolitem action="GroupObj" />
            <toolitem action="UngroupObj" />
            <toolitem action="AlignObj" />
        </placeholder>
    </toolbar>
    <accelerator action="DeleteObj" />
    <accelerator action="ControlEqualAccel" />
    <accelerator action="ControlKPAddAccel" />
    <accelerator action="ControlKPSubtractAccel" />
</ui>
'''


class PlayheadController(Controller, Zoomable):

    _cursor = PLAYHEAD_CURSOR

    def __init__(self, *args, **kwargs):
        Controller.__init__(self, *args, **kwargs)

    def set_pos(self, item, pos):
        x, y = pos
        x += self._hadj.get_value()
        self._canvas.app.current.seeker.seek(Zoomable.pixelToNs(x))


class TimelineCanvas(goocanvas.Canvas, Zoomable, Loggable):
    """
        The goocanvas widget representing the timeline
    """

    __gtype_name__ = 'TimelineCanvas'
    __gsignals__ = {
        "expose-event": "override",
    }

    _tracks = None

    def __init__(self, instance, timeline=None):
        goocanvas.Canvas.__init__(self)
        Zoomable.__init__(self)
        Loggable.__init__(self)
        self.app = instance
        self._selected_sources = []
        self._tracks = []
        self.height = 0
        self._position = 0

        self._block_size_request = False
        self.props.integer_layout = True
        self.props.automatic_bounds = False
        self.props.clear_background = False
        self.get_root_item().set_simple_transform(0, 2.0, 1.0, 0)

        self._createUI()
        self._timeline = timeline
        self.settings = instance.settings

    def _createUI(self):
        self._cursor = ARROW
        root = self.get_root_item()
        self.tracks = goocanvas.Group()
        self.tracks.set_simple_transform(0, KW_LABEL_Y_OVERFLOW, 1.0, 0)
        root.add_child(self.tracks)
        self._marquee = goocanvas.Rect(
            parent=root,
            stroke_pattern=unpack_cairo_pattern(0x33CCFF66),
            fill_pattern=unpack_cairo_pattern(0x33CCFF66),
            visibility=goocanvas.ITEM_INVISIBLE)
        self._playhead = goocanvas.Rect(
            y=-10,
            parent=root,
            line_width=1,
            fill_color_rgba=0x000000FF,
            stroke_color_rgba=0xFFFFFFFF,
            width=3)
        self._playhead_controller = PlayheadController(self._playhead)
        self.connect("size-allocate", self._size_allocate_cb)
        root.connect("motion-notify-event", self._selectionDrag)
        root.connect("button-press-event", self._selectionStart)
        root.connect("button-release-event", self._selectionEnd)
        self.height = (LAYER_HEIGHT_EXPANDED + TRACK_SPACING +
                LAYER_SPACING) * 2
        # add some padding for the horizontal scrollbar
        self.height += 21
        self.set_size_request(-1, self.height)

    def from_event(self, event):
        x, y = event.x, event.y
        x += self.app.gui.timeline.hadj.get_value()
        return Point(*self.convert_from_pixels(x, y))

    def setExpanded(self, track_object, expanded):
        track_ui = None
        for track in self._tracks:
            if track.track == track_object:
                track_ui = track
                break

        track_ui.setExpanded(expanded)

## sets the cursor as appropriate

    def _mouseEnterCb(self, unused_item, unused_target, event):
        event.window.set_cursor(self._cursor)
        return True

    def do_expose_event(self, event):
        allocation = self.get_allocation()
        width = allocation.width
        height = allocation.height
        # draw the canvas background
        # we must have props.clear_background set to False

        self.style.apply_default_background(event.window,
            True,
            gtk.STATE_ACTIVE,
            event.area,
            event.area.x, event.area.y,
            event.area.width, event.area.height)

        goocanvas.Canvas.do_expose_event(self, event)

## implements selection marquee

    _selecting = False
    _mousedown = None
    _marquee = None
    _got_motion_notify = False

    def getItemsInArea(self, x1, y1, x2, y2):
        '''
        Permits to get the Non UI L{Track}/L{TrackObject} in a list of set
        corresponding to the L{Track}/L{TrackObject} which are in the are

        @param x1: The horizontal coordinate of the up left corner of the area
        @type x1: An C{int}
        @param y1: The vertical coordinate of the up left corner of the area
        @type y1: An C{int}
        @param x2: The horizontal coordinate of the down right corner of the
                   area
        @type x2: An C{int}
        @param x2: The vertical coordinate of the down right corner of the area
        @type x2: An C{int}

        @returns: A list of L{Track}, L{TrackObject} tuples
        '''
        items = self.get_items_in_area(goocanvas.Bounds(x1, y1, x2, y2), True,
            True, True)
        if not items:
            return [], []

        tracks = set()
        track_objects = set()

        for item in items:
            if isinstance(item, Track):
                tracks.add(item.track)
            elif isinstance(item, TrackObject):
                track_objects.add(item.element)

        return tracks, track_objects

    def _normalize(self, p1, p2, adjust=0):
        w, h = p2 - p1
        x, y = p1
        if w - adjust < 0:
            w = abs(w - adjust)
            x -= w
        else:
            w -= adjust
        if h < 0:
            h = abs(h)
            y -= h
        return (x, y), (w, h)

    def _selectionDrag(self, item, target, event):
        if self._selecting:
            self._got_motion_notify = True
            cur = self.from_event(event)
            pos, size = self._normalize(self._mousedown, cur,
                self.app.gui.timeline.hadj.get_value())
            self._marquee.props.x, self._marquee.props.y = pos
            self._marquee.props.width, self._marquee.props.height = size
            return True
        return False

    def _selectionStart(self, item, target, event):
        self._selecting = True
        self._marquee.props.visibility = goocanvas.ITEM_VISIBLE
        self._mousedown = self.from_event(event)
        self._marquee.props.width = 0
        self._marquee.props.height = 0
        self.pointer_grab(self.get_root_item(), gtk.gdk.POINTER_MOTION_MASK |
            gtk.gdk.BUTTON_RELEASE_MASK, self._cursor, event.time)
        return True

    def _selectionEnd(self, item, target, event):
        seeker = self.app.current.seeker
        self.pointer_ungrab(self.get_root_item(), event.time)
        self._selecting = False
        self._marquee.props.visibility = goocanvas.ITEM_INVISIBLE
        if not self._got_motion_notify:
            self._timeline.selection.setSelection([], 0)
            seeker.seek(Zoomable.pixelToNs(event.x))
        else:
            self._got_motion_notify = False
            mode = 0
            if event.get_state() & gtk.gdk.SHIFT_MASK:
                mode = 1
            if event.get_state() & gtk.gdk.CONTROL_MASK:
                mode = 2
            selected = self._objectsUnderMarquee()
            self.app.projectManager.current.emit("selected-changed", selected)
            self._timeline.selection.setSelection(self._objectsUnderMarquee(), mode)
        return True

    def _objectsUnderMarquee(self):
        items = self.get_items_in_area(self._marquee.get_bounds(), True, True,
            True)
        if items:
            return set((item.element for item in items if isinstance(item,
                TrackObject) and item.bg in items))
        return set()

## playhead implementation

    position = 0

    def timelinePositionChanged(self, position):
        self.position = position
        self._playhead.props.x = self.nsToPixel(position)

    max_duration = 0

    def setMaxDuration(self, duration):
        self.max_duration = duration
        self._request_size()

    def _request_size(self):
        alloc = self.get_allocation()
        self.set_bounds(0, 0, alloc.width, alloc.height)
        self._playhead.props.height = (self.height + SPACING)

    def _size_allocate_cb(self, widget, allocation):
        self._request_size()

    def zoomChanged(self):
        self.queue_draw()
        if self._timeline:
            self._timeline.dead_band = self.pixelToNs(
                self.settings.edgeSnapDeadband)
            #self._timelinePositionChanged(self.position)

## settings callbacks

    def _setSettings(self):
        self.zoomChanged()

    settings = receiver(_setSettings)

    @handler(settings, "edgeSnapDeadbandChanged")
    def _edgeSnapDeadbandChangedCb(self, settings):
        self.zoomChanged()

## Timeline callbacks

    def setTimeline(self, timeline):
        while self._tracks:
            self._trackRemoved(None, 0)

        self._timeline = timeline
        if self._timeline:
            for track in self._timeline.get_tracks():
                self._trackAdded(None, track)
            self._timeline.connect("track-added", self._trackAdded)
            self._timeline.connect("track-removed", self._trackRemoved)
        self.zoomChanged()

    def getTimeline(self):
        return self._timeline

    timeline = property(getTimeline, setTimeline, None, "The timeline property")

    def _trackAdded(self, timeline, track):
        track = Track(self.app, track, self._timeline)
        self._tracks.append(track)
        track.set_canvas(self)
        self.tracks.add_child(track)
        self.regroupTracks()

    def _trackRemoved(self, unused_timeline, position):
        track = self._tracks[position]
        del self._tracks[position]
        track.remove()
        self.regroupTracks()

    def regroupTracks(self):
        height = 0
        for i, track in enumerate(self._tracks):
            track.set_simple_transform(0, height, 1, 0)
            height += track.height + TRACK_SPACING
        self.height = height
        self._request_size()


class TimelineControls(gtk.VBox, Loggable):
    """Contains the timeline track names."""

    def __init__(self):
        gtk.VBox.__init__(self)
        Loggable.__init__(self)
        self._tracks = []
        self._timeline = None
        self.set_spacing(LAYER_SPACING)
        self.set_size_request(TRACK_CONTROL_WIDTH, -1)

## Timeline callbacks

    def getTimeline(self):
        return self._timeline

    def setTimeline(self, timeline):
        self.debug("Setting timeline %s", timeline)

        while self._tracks:
            self._trackRemovedCb(None, 0)

        if self._timeline:
            for track in self._timeline.get_tracks():
                self._trackAddedCb(None, track)

            self._timeline.connect("track-added", self._trackAddedCb)
            self._timeline.connect("track-removed", self._trackRemovedCb)

    timeline = property(getTimeline, setTimeline, None, "The timeline property")

    def _trackAddedCb(self, timeline, track):
        track = TrackControls(track)
        self._tracks.append(track)
        self.pack_start(track, False, False)
        track.show()

    def _trackRemovedCb(self, unused_timeline, position):
        self.timeline.disconnect_by_function(self._trackAddedCb)
        self.timeline.disconnect_by_function(self._trackRemovedCb)
        track = self._tracks[position]
        del self._tracks[position]
        self.remove(track)


class InfoStub(gtk.HBox, Loggable):
    """
    Box used to display information on the current state of the timeline
    """

    def __init__(self):
        gtk.HBox.__init__(self)
        Loggable.__init__(self)
        self.errors = []
        self._scroll_pos_ns = 0
        self._errorsmessage = _("One or more GStreamer errors occured!")
        self._makeUI()

    def _makeUI(self):
        self.set_spacing(SPACING)
        self.erroricon = gtk.image_new_from_stock(gtk.STOCK_DIALOG_WARNING,
                                                  gtk.ICON_SIZE_SMALL_TOOLBAR)

        self.pack_start(self.erroricon, expand=False)

        self.infolabel = gtk.Label(self._errorsmessage)
        self.infolabel.set_alignment(0, 0.5)

        self.questionbutton = gtk.Button()
        self.infoicon = gtk.Image()
        self.infoicon.set_from_stock(gtk.STOCK_INFO, gtk.ICON_SIZE_SMALL_TOOLBAR)
        self.questionbutton.add(self.infoicon)
        self.questionbutton.connect("clicked", self._questionButtonClickedCb)

        self.pack_start(self.infolabel, expand=True, fill=True)
        self.pack_start(self.questionbutton, expand=False)

    def addErrors(self, *args):
        self.errors.append(args)
        self.show()

    def _errorDialogBoxCloseCb(self, dialog):
        dialog.destroy()

    def _errorDialogBoxResponseCb(self, dialog, unused_response):
        dialog.destroy()

    def _questionButtonClickedCb(self, unused_button):
        msgs = (_("Error List"),
            _("The following errors have been reported:"))
        # show error dialog
        dbox = FileListErrorDialog(*msgs)
        dbox.connect("close", self._errorDialogBoxCloseCb)
        dbox.connect("response", self._errorDialogBoxResponseCb)
        for reason, extra in self.errors:
            dbox.addFailedFile(None, reason, extra)
        dbox.show()
        # reset error list
        self.errors = []
        self.hide()

    def show(self):
        self.log("showing")
        self.show_all()


class Timeline(gtk.Table, Loggable, Zoomable):

    __gtype_name__ = 'Timeline'
    __gsignals__ = {
        "duration-changed": (gobject.SIGNAL_RUN_LAST,
            gobject.TYPE_NONE, (gobject.TYPE_INT,)),
    }

    def __init__(self, instance, ui_manager):
        gtk.Table.__init__(self, rows=2, columns=1, homogeneous=False)
        Loggable.__init__(self)
        Zoomable.__init__(self)
        self.log("Creating Timeline")

        self._updateZoom = True
        self.ui_manager = ui_manager
        self.app = instance
        self._temp_objects = []
        self._factories = None
        self._finish_drag = False
        self._position = 0
        self._state = gst.STATE_NULL
        self._createUI()
        self._prev_duration = 0
        self.rate = gst.Fraction(1, 1)
        self._project = None
        self._timeline = None
        self._duration = 0
        self._creating_tckobjs_sigid = {}

        #Ids of the tracks notify::duration signals
        self._tcks_sig_ids = {}
        #Ids of the layer-added and layer-removed signals
        self._layer_sig_ids = []

    def _createUI(self):
        self.leftSizeGroup = gtk.SizeGroup(gtk.SIZE_GROUP_HORIZONTAL)
        self.props.row_spacing = 2
        self.props.column_spacing = 2
        self.hadj = gtk.Adjustment()
        self.vadj = gtk.Adjustment()

        # zooming slider's "zoom fit" button
        zoom_controls_hbox = gtk.HBox()
        zoom_fit_btn = gtk.Button()
        zoom_fit_btn.set_relief(gtk.RELIEF_NONE)
        zoom_fit_btn.set_tooltip_text(ZOOM_FIT)
        zoom_fit_icon = gtk.Image()
        zoom_fit_icon.set_from_stock(gtk.STOCK_ZOOM_FIT, gtk.ICON_SIZE_BUTTON)
        zoom_fit_btn_hbox = gtk.HBox()
        zoom_fit_btn_hbox.pack_start(zoom_fit_icon)
        zoom_fit_btn_hbox.pack_start(gtk.Label(_("Zoom")))
        zoom_fit_btn.add(zoom_fit_btn_hbox)
        zoom_fit_btn.connect("clicked", self._zoomFitCb)
        zoom_controls_hbox.pack_start(zoom_fit_btn)
        # zooming slider
        self._zoomAdjustment = gtk.Adjustment()
        self._zoomAdjustment.set_value(Zoomable.getCurrentZoomLevel())
        self._zoomAdjustment.connect("value-changed",
            self._zoomAdjustmentChangedCb)
        self._zoomAdjustment.props.lower = 0
        self._zoomAdjustment.props.upper = Zoomable.zoom_steps
        zoomslider = gtk.HScale(self._zoomAdjustment)
        zoomslider.props.draw_value = False
        zoomslider.set_tooltip_text(_("Zoom Timeline"))
        zoomslider.connect("scroll-event", self._zoomSliderScrollCb)
        zoomslider.set_size_request(100, 0)  # At least 100px wide for precision
        zoom_controls_hbox.pack_start(zoomslider)
        self.attach(zoom_controls_hbox, 0, 1, 0, 1, yoptions=0, xoptions=gtk.FILL)

        # controls for tracks and layers
        self._controls = TimelineControls()
        controlwindow = gtk.Viewport(None, self.vadj)
        controlwindow.add(self._controls)
        controlwindow.set_size_request(-1, 1)
        controlwindow.set_shadow_type(gtk.SHADOW_OUT)
        self.attach(controlwindow, 0, 1, 1, 2, xoptions=gtk.FILL)

        # timeline ruler
        self.ruler = ruler.ScaleRuler(self.app, self.hadj)
        self.ruler.set_size_request(0, 25)
        #self.ruler.set_border_width(2)
        self.ruler.connect("key-press-event", self._keyPressEventCb)
        self.ruler.connect("size-allocate", self._rulerSizeAllocateCb)
        rulerframe = gtk.Frame()
        rulerframe.set_shadow_type(gtk.SHADOW_OUT)
        rulerframe.add(self.ruler)
        self.attach(rulerframe, 1, 2, 0, 1, yoptions=0)

        # proportional timeline
        self._canvas = TimelineCanvas(self.app)
        self._root_item = self._canvas.get_root_item()
        self.attach(self._canvas, 1, 2, 1, 2)

        # scrollbar
        self._hscrollbar = gtk.HScrollbar(self.hadj)
        self._vscrollbar = gtk.VScrollbar(self.vadj)
        self.attach(self._hscrollbar, 1, 2, 2, 3, yoptions=0)
        self.attach(self._vscrollbar, 2, 3, 1, 2, xoptions=0)
        self.hadj.connect("value-changed", self._updateScrollPosition)
        self.vadj.connect("value-changed", self._updateScrollPosition)

        # error infostub
        self.infostub = InfoStub()
        self.attach(self.infostub, 1, 2, 4, 5, yoptions=0)

        self.show_all()
        self.infostub.hide()

        # toolbar actions
        actions = (
            ("ZoomIn", gtk.STOCK_ZOOM_IN, None, "<Control>plus", ZOOM_IN,
                self._zoomInCb),
            ("ZoomOut", gtk.STOCK_ZOOM_OUT, None, "<Control>minus", ZOOM_OUT,
                self._zoomOutCb),
            ("ZoomFit", gtk.STOCK_ZOOM_FIT, None, None, ZOOM_FIT,
                self._zoomFitCb),

            # actions for adding additional accelerators
            ("ControlEqualAccel", gtk.STOCK_ZOOM_IN, None, "<Control>equal", ZOOM_IN,
                self._zoomInCb),
            ("ControlKPAddAccel", gtk.STOCK_ZOOM_IN, None, "<Control>KP_Add", ZOOM_IN,
                self._zoomInCb),
            ("ControlKPSubtractAccel", gtk.STOCK_ZOOM_OUT, None, "<Control>KP_Subtract", ZOOM_OUT,
                self._zoomOutCb),
        )

        selection_actions = (
            ("DeleteObj", gtk.STOCK_DELETE, None, "Delete", DELETE,
                self.deleteSelected),
            ("UnlinkObj", "pitivi-unlink", None, "<Shift><Control>L", UNLINK,
                self.unlinkSelected),
            ("LinkObj", "pitivi-link", None, "<Control>L", LINK,
                self.linkSelected),
            ("UngroupObj", "pitivi-ungroup", None, "<Shift><Control>G", UNGROUP,
                self.ungroupSelected),
            ("GroupObj", "pitivi-group", None, "<Control>G", GROUP,
                self.groupSelected),
            ("AlignObj", "pitivi-align", None, "<Shift><Control>A", ALIGN,
                self.alignSelected),
        )

        self.playhead_actions = (
            ("Split", "pitivi-split", _("Split"), "S", SPLIT,
                self.split),
            ("Keyframe", "pitivi-keyframe", _("Add a Keyframe"), "K", KEYFRAME,
                self.keyframe),
            ("Prevframe", "pitivi-prevframe", _("_Previous Keyframe"), "E", PREVFRAME,
                self.prevframe),
            ("Nextframe", "pitivi-nextframe", _("_Next Keyframe"), "R", NEXTFRAME,
                self.nextframe),
        )

        actiongroup = gtk.ActionGroup("timelinepermanent")
        actiongroup.add_actions(actions)
        self.ui_manager.insert_action_group(actiongroup, 0)

        actiongroup = gtk.ActionGroup("timelineselection")
        actiongroup.add_actions(selection_actions)
        actiongroup.add_actions(self.playhead_actions)
        self.link_action = actiongroup.get_action("LinkObj")
        self.unlink_action = actiongroup.get_action("UnlinkObj")
        self.group_action = actiongroup.get_action("GroupObj")
        self.ungroup_action = actiongroup.get_action("UngroupObj")
        self.align_action = actiongroup.get_action("AlignObj")
        self.delete_action = actiongroup.get_action("DeleteObj")
        self.split_action = actiongroup.get_action("Split")
        self.keyframe_action = actiongroup.get_action("Keyframe")
        self.prevframe_action = actiongroup.get_action("Prevframe")
        self.nextframe_action = actiongroup.get_action("Nextframe")

        self.ui_manager.insert_action_group(actiongroup, -1)

        self.ui_manager.add_ui_from_string(ui)

        # drag and drop
        self.drag_dest_set(gtk.DEST_DEFAULT_MOTION,
            [FILESOURCE_TUPLE, EFFECT_TUPLE],
            gtk.gdk.ACTION_COPY)

        self.connect("drag-data-received", self._dragDataReceivedCb)
        self.connect("drag-leave", self._dragLeaveCb)
        self.connect("drag-drop", self._dragDropCb)
        self.connect("drag-motion", self._dragMotionCb)
        self._canvas.connect("key-press-event", self._keyPressEventCb)
        self._canvas.connect("scroll-event", self._scrollEventCb)

## Event callbacks
    def _keyPressEventCb(self, unused_widget, event):
        kv = event.keyval
        self.debug("kv:%r", kv)
        if kv not in [gtk.keysyms.Left, gtk.keysyms.Right]:
            return False
        mod = event.get_state()
        try:
            if mod & gtk.gdk.CONTROL_MASK:
                now = self._project.pipeline.getPosition()
                ltime, rtime = self._project.timeline.edges.closest(now)

            if kv == gtk.keysyms.Left:
                if mod & gtk.gdk.SHIFT_MASK:
                    self._seeker.seekRelative(0 - gst.SECOND)
                elif mod & gtk.gdk.CONTROL_MASK:
                    self._seeker.seek(ltime + 1)
                else:
                    self._seeker.seekRelative(0 - long(self.rate * gst.SECOND))
            elif kv == gtk.keysyms.Right:
                if mod & gtk.gdk.SHIFT_MASK:
                    self._seeker.seekRelative(gst.SECOND)
                elif mod & gtk.gdk.CONTROL_MASK:
                    self._seeker.seek(rtime + 1)
                else:
                    self.seeker.seekRelative(long(self.rate * gst.SECOND))
        finally:
            return True

## Drag and Drop callbacks

    def _dragMotionCb(self, unused, context, x, y, timestamp):

        if not self._factories:
            if  context.targets in DND_EFFECT_LIST:
                atom = gtk.gdk.atom_intern(EFFECT_TUPLE[0])
            else:
                atom = gtk.gdk.atom_intern(FILESOURCE_TUPLE[0])

            self.drag_get_data(context, atom, timestamp)
            self.drag_highlight()
        else:
            if  context.targets not in DND_EFFECT_LIST:
                if not self._temp_objects and not self._creating_tckobjs_sigid:
                    self.timeline.enable_update(False)
                    self._create_temp_source()

                # Let some time for TrackObject-s to be created
                if self._temp_objects and not self._creating_tckobjs_sigid:
                    focus = self._temp_objects[0]
                    self._move_context = MoveContext(self.timeline,
                            focus, set(self._temp_objects[1:]))
                    self._move_temp_source(self.hadj.props.value + x, y)
        return True

    def _dragLeaveCb(self, unused_layout, context, unused_tstamp):
        self._temp_objects = []
        self.drag_unhighlight()
        self.timeline.enable_update(True)

    def _dragDropCb(self, widget, context, x, y, timestamp):
        if  context.targets not in DND_EFFECT_LIST:
            self.app.action_log.begin("add clip")
            self.selected = self._temp_objects
            self._project.emit("selected-changed", set(self.selected))

            self._move_context.finish()
            self.app.action_log.commit()
            context.drop_finish(True, timestamp)
            self._factories = []

            return True

        elif context.targets in DND_EFFECT_LIST:
            if self._duration == 0:
                return False

            factory = self._factories[0]
            timeline_objs = self._getTimelineObjectUnderMouse(x, y)
            if timeline_objs:
                # FIXME make a util function to add effects instead of copy/pasting it
                # from cliproperties
                bin_desc = factory.effectname
                media_type = self.app.effects.getFactoryFromName(bin_desc).media_type

                # Trying to apply effect only on the first object of the selection
                tlobj = timeline_objs[0]

                # Checking that this effect can be applied on this track object
                # Which means, it has the corresponding media_type
                for tckobj in tlobj.get_track_objects():
                    track = tckobj.get_track()
                    if track.props.track_type == ges.TRACK_TYPE_AUDIO and \
                            media_type == AUDIO_EFFECT or \
                            track.props.track_objects == ges.TRACK_TYPE_VIDEO and \
                            media_type == VIDEO_EFFECT:
                        #Actually add the effect
                        self.app.action_log.begin("add effect")
                        effect = ges.TrackParseLaunchEffect(bin_desc)
                        tlobj.add_track_object(effect)
                        track.add_object(effect)
                        self.app.action_log.commit()
                        self._factories = None
                        self.seeker.seek(self._position)
                        context.drop_finish(True, timestamp)

                        self.timeline.selection.setSelection(timeline_objs, SELECT)
                        break

            return True

        return False

    def getDuration(self):
        return self.timeline.props.duration

    duration = property(getDuration, None, None, "The duration property")

    def _dragDataReceivedCb(self, unused_layout, context, x, y,
        selection, targetType, timestamp):
        self.app.projectManager.current.timeline.enable_update(False)
        self.log("targetType:%d, selection.data:%s" % (targetType, selection.data))
        self.selection_data = selection.data

        if targetType not in [TYPE_PITIVI_FILESOURCE,
                TYPE_PITIVI_EFFECT]:
            context.finish(False, False, timestamp)
            return

        if targetType == TYPE_PITIVI_FILESOURCE:
            uris = selection.data.split("\n")
            self._factories = \
                [self._project.sources.getInfoFromUri(uri) for uri in uris]
        else:
            if not self._duration:
                return False
            self._factories = [self.app.effects.getFactoryFromName(selection.data)]

        context.drag_status(gtk.gdk.ACTION_COPY, timestamp)
        return True

    def _getTimelineObjectUnderMouse(self, x, y):
        timeline_objs = []
        items_in_area = self._canvas.getItemsInArea(x, y - 15, x + 1, y - 30)

        track_objects = [obj for obj in items_in_area[1]]
        for track_object in track_objects:
            timeline_objs.append(track_object.get_timeline_object())

        return timeline_objs

    def _ensureLayer(self):
        """
        Make sure we have a layer in our timeline

        Returns: The number of layer present in self.timeline
        """
        layers = self.timeline.get_layers()

        if (len(layers) == 0):
            layer = ges.TimelineLayer()
            layer.props.auto_transition = True
            self.timeline.add_layer(layer)
            layers = [layer]

        return layers

    def _create_temp_source(self):
        infos = self._factories
        layer = self._ensureLayer()[0]
        duration = 0

        for info in infos:
            src = ges.TimelineFileSource(info.get_uri())
            src.props.start = duration
            duration += info.get_duration()
            layer.add_object(src)
            id = src.connect("track-object-added", self._trackObjectsCreatedCb, src)
            self._creating_tckobjs_sigid[src] = id

    def _trackObjectsCreatedCb(self, unused_tl, track_object, tlobj):
        # Make sure not to start the moving process before the TrackObject-s
        # are created. We concider that the time between the different
        # TrackObject-s creation is short enough so we are all good when the
        # first TrackObject is added to the TimelineObject
        self._temp_objects.insert(0, tlobj)
        tlobj.disconnect(self._creating_tckobjs_sigid[tlobj])
        del self._creating_tckobjs_sigid[tlobj]

    def _move_temp_source(self, x, y):
        x1, y1, x2, y2 = self._controls.get_allocation()
        offset = 10 + (x2 - x1)
        x, y = self._canvas.convert_from_pixels(x - offset, y)
        priority = int((y // (LAYER_HEIGHT_EXPANDED + LAYER_SPACING)))
        delta = Zoomable.pixelToNs(x)
        obj = self._temp_objects[0]
        obj.starting_start = obj.props.start
        self._move_context.editTo(delta, priority)

## Zooming and Scrolling

    def _scrollEventCb(self, canvas, event):
        if event.state & gtk.gdk.SHIFT_MASK:
            # shift + scroll => vertical (up/down) scroll
            if event.direction == gtk.gdk.SCROLL_UP:
                self.scroll_up()
            elif event.direction == gtk.gdk.SCROLL_DOWN:
                self.scroll_down()
            event.state &= ~gtk.gdk.SHIFT_MASK
        elif event.state & gtk.gdk.CONTROL_MASK:
            # zoom + scroll => zooming (up: zoom in)
            if event.direction == gtk.gdk.SCROLL_UP:
                Zoomable.zoomIn()
                return True
            elif event.direction == gtk.gdk.SCROLL_DOWN:
                Zoomable.zoomOut()
                return True
            return False
        else:
            if event.direction == gtk.gdk.SCROLL_UP:
                self.scroll_left()
            elif event.direction == gtk.gdk.SCROLL_DOWN:
                self.scroll_right()
        return True

    def scroll_left(self):
        self._hscrollbar.set_value(self._hscrollbar.get_value() -
            self.hadj.props.page_size ** (2.0 / 3.0))

    def scroll_right(self):
        self._hscrollbar.set_value(self._hscrollbar.get_value() +
            self.hadj.props.page_size ** (2.0 / 3.0))

    def scroll_up(self):
        self._vscrollbar.set_value(self._vscrollbar.get_value() -
            self.vadj.props.page_size ** (2.0 / 3.0))

    def scroll_down(self):
        self._vscrollbar.set_value(self._vscrollbar.get_value() +
            self.vadj.props.page_size ** (2.0 / 3.0))

    def unsureVadjHeight(self):
        self._scroll_pos_ns = Zoomable.pixelToNs(self.hadj.get_value())
        self._root_item.set_simple_transform(0 - self.hadj.get_value(),
            0 - self.vadj.get_value(), 1.0, 0)

    def _updateScrollPosition(self, adjustment):
        self.unsureVadjHeight()

    def _zoomAdjustmentChangedCb(self, adjustment):
        # GTK crack
        self._updateZoom = False
        Zoomable.setZoomLevel(int(adjustment.get_value()))
        self._updateZoom = True

    _scroll_pos_ns = 0

    def _zoomSliderScrollCb(self, unused_widget, event):
        value = self._zoomAdjustment.get_value()
        if event.direction in [gtk.gdk.SCROLL_UP, gtk.gdk.SCROLL_RIGHT]:
            self._zoomAdjustment.set_value(value + 1)
        elif event.direction in [gtk.gdk.SCROLL_DOWN, gtk.gdk.SCROLL_LEFT]:
            self._zoomAdjustment.set_value(value - 1)

    def zoomChanged(self):
        if self._updateZoom:
            self._zoomAdjustment.set_value(self.getCurrentZoomLevel())

        # the new scroll position should preserve the current horizontal
        # position of the playhead in the window
        cur_playhead_offset = self._canvas._playhead.props.x -\
            self.hadj.props.value
        new_pos = Zoomable.nsToPixel(self._position) - cur_playhead_offset

        self.updateScrollAdjustments()
        self._scrollToPosition(new_pos)
        self.ruler.queue_resize()
        self.ruler.queue_draw()

    def positionChangedCb(self, seeker, position):
        self._position = position
        self.ruler.timelinePositionChanged(position)
        self._canvas.timelinePositionChanged(position)
        if self._state == gst.STATE_PLAYING:
            self.scrollToPlayhead()

    def stateChanged(self, state):
        self._state = state

    def scrollToPlayhead(self):
        """
        If the current position is out of the view bouds, then scroll
        as close to the center of the view as possible or as close as the
        timeline canvas allows.
        """
        page_size = self.hadj.get_page_size()

        new_pos = Zoomable.nsToPixel(self._position)
        scroll_pos = self.hadj.get_value()
        if (new_pos > scroll_pos + page_size) or (new_pos < scroll_pos):
            self.scrollToPosition(min(new_pos - page_size / 2, self.hadj.upper - page_size - 1))
        return False

    def scrollToPosition(self, position):
        if position > self.hadj.upper:
            # we can't perform the scroll because the canvas needs to be
            # updated
            gobject.idle_add(self._scrollToPosition, position)
        else:
            self._scrollToPosition(position)

    def _scrollToPosition(self, position):
        self._hscrollbar.set_value(position)
        return False

    def _rulerSizeAllocateCb(self, ruler, allocation):
        self._canvas.props.redraw_when_scrolled = False

## Project callbacks

    def setProject(self, project):
        self.debug("Setting project %s", project)
        if self._project:
            self._project.disconnect_by_function(self._settingsChangedCb)
            self.seeker.disconnect_by_function(self.positionChangedCb)

        self._project = project
        if self._project:
            self.setTimeline(project.timeline)
            self._canvas.setTimeline(project.timeline)
            self._canvas.zoomChanged()
            self.ruler.setProjectFrameRate(self._project.getSettings().videorate)
            self.ruler.zoomChanged()
            self._settingsChangedCb(self._project, None, self._project.getSettings())
            self.seeker = self._project.seeker
            self.seeker.connect("position-changed", self.positionChangedCb)
            self._project.connect("settings-changed", self._settingsChangedCb)

    def _settingsChangedCb(self, project, old, new):
        rate = new.videorate
        self.rate = float(1 / rate)
        self.ruler.setProjectFrameRate(rate)

## Timeline callbacks

    def setTimeline(self, timeline):
        self.debug("Setting timeline %s", timeline)
        self._controls.timeline = self._timeline

        self.delTimeline()
        self._timeline = timeline

        # Connecting to timeline signals
        self._layer_sig_ids.append(self._timeline.connect("layer-added",
                self._layerAddedCb))
        self._layer_sig_ids.append(self._timeline.connect("layer-removed",
                self._layerRemovedCb))

        # Make sure to set the current layer in use
        self._layerAddedCb(None, None)

    def getTimeline(self):
        return self._timeline

    def delTimeline(self):
        # Disconnect signal
        for track, sigid in self._tcks_sig_ids.iteritems():
            track.disconnect(sigid)

        for sigid in self._layer_sig_ids:
            self._timeline.disconnect(sigid)

        # clear dictionaries
        self._tcks_sig_ids = {}
        self._layer_sig_ids = []
        self._timeline = None

    timeline = property(getTimeline, setTimeline, delTimeline,
            "The GESTimeline")

    def _layerAddedCb(self, unused_layer, unused_user_data):
        self.updateVScrollAdjustments()

    def _layerRemovedCb(self, unused_layer, unused_user_data):
        self.updateVScrollAdjustments()

    def updateVScrollAdjustments(self):
        layers = self._timeline.get_layers()
        num_layers = len(layers)

        # Ensure height of the scrollbar
        self.vadj.props.upper = (LAYER_HEIGHT_EXPANDED + LAYER_SPACING
                + TRACK_SPACING) * 2 * num_layers

    def updateScrollAdjustments(self):
        a = self.get_allocation()
        size = Zoomable.nsToPixel(self.duration)
        self.hadj.props.lower = 0
        self.hadj.props.upper = size + 200  # why is this necessary???
        self.hadj.props.page_size = a.width
        self.hadj.props.page_increment = size * 0.9
        self.hadj.props.step_increment = size * 0.1

## ToolBar callbacks
    def _zoomFitCb(self, unused_action):
        self.app.gui.setBestZoomRatio()

    def _zoomInCb(self, unused_action):
        Zoomable.zoomIn()

    def _zoomOutCb(self, unused_action):
        Zoomable.zoomOut()

    def deleteSelected(self, unused_action):
        if self.timeline:
            self.app.action_log.begin("delete clip")
            #FIXME GES port: Handle unlocked TrackObject-s
            for obj in self.timeline.selection:
                layer = obj.get_layer()
                layer.remove_object(obj)

            self.app.action_log.commit()

    def unlinkSelected(self, unused_action):
        if self.timeline:
            self.timeline.unlinkSelection()

    def linkSelected(self, unused_action):
        if self.timeline:
            self.timeline.linkSelection()

    def ungroupSelected(self, unused_action):
        if self.timeline:
            self.debug("Ungouping selected clips %s" % self.timeline.selection)

            self.timeline.enable_update(False)
            self.app.action_log.begin("ungroup")
            for tlobj in self.timeline.selection:
                tlobj.objects_set_locked(False)
            self.timeline.enable_update(True)
            self.app.action_log.commit()

    def groupSelected(self, unused_action):
        if self.timeline:
            self.debug("Gouping selected clips %s" % self.timeline.selection)

            self.timeline.enable_update(False)
            self.app.action_log.begin("group")
            for tlobj in self.timeline.selection:
                tlobj.objects_set_locked(True)
            self.app.action_log.commit()
            self.timeline.enable_update(True)

    def alignSelected(self, unused_action):
        if "NumPy" in soft_deps:
            DepsManager(self.app)

        elif self.timeline:
            progress_dialog = AlignmentProgressDialog(self.app)
            progress_dialog.window.show()
            self.app.action_log.begin("align")
            self.timeline.enable_update(False)

            def alignedCb():  # Called when alignment is complete
                self.timeline.enable_update(True)
                self.app.action_log.commit()
                progress_dialog.window.destroy()

            pmeter = self.timeline.alignSelection(alignedCb)
            pmeter.addWatcher(progress_dialog.updatePosition)

    def split(self, action):
        self.timeline.enable_update(False)

        #Splitting the objects at the current position
        for track in self.timeline.get_tracks():
            for tck_obj in track.get_objects():
                start = tck_obj.props.start
                end = start + tck_obj.props.duration
                if start < self._position and end > self._position:
                    obj = tck_obj.get_timeline_object()
                    obj.split(self._position)

        self.timeline.enable_update(True)

    def keyframe(self, action):
        timeline_position = self._position
        selected = self.timeline.selection.getSelectedTrackObjs()

        for obj in selected:
            keyframe_exists = False

            position_in_obj = (timeline_position - obj.start) + obj.in_point
            interpolators = obj.getInterpolators()
            for value in interpolators:
                interpolator = obj.getInterpolator(value)
                keyframes = interpolator.getInteriorKeyframes()
                for kf in keyframes:
                    if kf.getTime() == position_in_obj:
                        keyframe_exists = True
                        self.app.action_log.begin("remove volume point")
                        interpolator.removeKeyframe(kf)
                        self.app.action_log.commit()
                if keyframe_exists == False:
                    self.app.action_log.begin("add volume point")
                    interpolator.newKeyframe(position_in_obj)
                    self.app.action_log.commit()

    def prevframe(self, action):
        timeline_position = self._position

        prev_kf = self.timeline.getPrevKeyframe(timeline_position)
        if prev_kf != None:
            self._seeker.seek(prev_kf)
            self.scrollToPlayhead()

    def nextframe(self, action):
        timeline_position = self._position

        next_kf = self.timeline.getNextKeyframe(timeline_position)
        if next_kf:
            self._seeker.seek(next_kf)
            self.scrollToPlayhead()
