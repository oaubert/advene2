#
# Advene: Annotate Digital Videos, Exchange on the NEt
# Copyright (C) 2008 Olivier Aubert <olivier.aubert@liris.cnrs.fr>
#
# Advene is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Advene is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Advene; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#

from gettext import gettext as _

import os
import gtk
import xml.parsers.expat
import StringIO

import advene.core.config as config
from advene.gui.edit.elements import ContentHandler, TextContentHandler
from advene.gui.edit.shapewidget import ShapeDrawer, Rectangle, ShapeEditor
from advene.gui.util import image_from_position, dialog, decode_drop_parameters

from advene.gui.edit.rules import EditRuleSet, EditQuery
from advene.rules.elements import RuleSet, SimpleQuery
import xml.etree.ElementTree as ET

name="Default content handlers"

def register(controller=None):
    for c in (ZoneContentHandler, SVGContentHandler,
              RuleSetContentHandler, SimpleQueryContentHandler):
        controller.register_content_handler(c)

class ZoneContentHandler (ContentHandler):
    """Create a zone edit form for the given element."""
    def can_handle(mimetype):
        res=0
        if mimetype == 'application/x-advene-zone':
            res=80
        return res
    can_handle=staticmethod(can_handle)

    def __init__ (self, element, controller=None, parent=None, **kw):
        self.element = element
        self.controller=controller
        self.parent=parent
        self.editable = True
        self.fname=None
        self.view = None
        self.shape = None

    def set_editable (self, boolean):
        self.editable = boolean

    def callback(self, l):
        if l[0][0] is None or l[1][0] is None:
            self.shape = None
            self.view.plot()
            return

        if self.shape is None:
            r = Rectangle()
            r.name = "Selection"
            r.color = "green"
            r.set_bounds(l)
            self.view.add_object(r)
            self.shape=r
        else:
            self.shape.set_bounds(l)
            self.view.plot()
        return

    def update_element (self):
        """Update the element fields according to the values in the view."""
        if not self.editable:
            return False
        if self.shape is None:
            return True

        if not self.shape:
            return True

        shape=self.shape
        shape.name=self.nameentry.get_text()
        text="""shape=rect\nname=%s\nx=%02f\ny=%02f\nwidth=%02f\nheight=%02f""" % (
            shape.name,
            shape.x * 100.0 / self.view.canvaswidth,
            shape.y * 100.0 / self.view.canvasheight,
            shape.width * 100.0 / self.view.canvaswidth,
            shape.height * 100.0 / self.view.canvasheight)

        self.element.data = text
        return True

    def get_view (self, compact=False):
        """Generate a view widget for editing zone attributes."""
        vbox=gtk.VBox()

        if self.parent is not None and hasattr(self.parent, 'begin'):
            # We are editing the content of an annotation. Use its snapshot as background.
            i=image_from_position(self.controller, self.parent.begin, height=160)
            self.view = ShapeDrawer(callback=self.callback, background=i)
        else:
            self.view = ShapeDrawer(callback=self.callback)

        if self.element.data:
            d=self.element.parsed()
            if isinstance(d, dict):
                try:
                    x = int(float(d['x']) * self.view.canvaswidth / 100)
                    y = int(float(d['y']) * self.view.canvasheight / 100)
                    width = int(float(d['width']) * self.view.canvaswidth / 100)
                    height = int(float(d['height']) * self.view.canvasheight / 100)
                    self.callback( ( (x, y),
                                     (x+width, y+height) ) )
                    self.shape.name = d['name']
                except KeyError:
                    self.callback( ( (0.0, 0.0),
                                     (10.0, 10.0) ) )
                    self.shape.name = self.element.data

        # Name edition
        hb=gtk.HBox()
        hb.pack_start(gtk.Label(_("Label")), expand=False)
        self.nameentry=gtk.Entry()
        if self.shape is not None:
            self.nameentry.set_text(self.shape.name)
        hb.pack_start(self.nameentry)

        vbox.pack_start(hb, expand=False)

        vbox.add(self.view.widget)

        return vbox

class SVGContentHandler (ContentHandler):
    """Create a SVG edit form for the given element."""
    def can_handle(mimetype):
        res=0
        if mimetype == 'image/svg+xml':
            res=80
        return res
    can_handle=staticmethod(can_handle)

    def __init__ (self, element, controller=None, parent=None, **kw):
        self.element = element
        self.controller=controller
        self.parent=parent
        self.editable = True
        # Internal rules defined by the plugin
        self.rules=[]
        self.fname=None
        self.view = None
        self.sourceview=None
        self.editing_source=False

    def close(self):
        for r in self.rules:
            self.controller.event_handler.remove_rule(r, 'internal')
        return True

    def set_editable (self, boolean):
        self.editable = boolean
        if self.sourceview:
            self.sourceview.set_editable(boolean)

    def parse_svg(self):
        if self.element.data:
            try:
                f=self.element.as_file
                root=ET.parse(f).getroot()
                f.close()
            except xml.parsers.expat.ExpatError:
                root=None
                dialog.message_dialog(
                    _("Error while parsing SVG content:\n\n%s") % unicode(e),
                    icon=gtk.MESSAGE_ERROR)
            if root:
                self.view.drawer.clear_objects()
                path=''
                if self.parent is not None and hasattr(self.parent, 'file_'):
                    # We are in a resource. Pass its path as current path.
                    path=os.path.dirname(self.parent.file_)
                self.view.drawer.parse_svg(root, current_path=path)
        return True

    def update_element (self):
        """Update the element fields according to the values in the view."""
        if not self.editable:
            return False

        if self.editing_source:
            self.sourceview.update_element()
            # We applied our modifications to the XML source, so
            # parse the source again in the SVG editor
            self.parse_svg()
            return True

        if self.view is None:
            return True

        tree=ET.ElementTree(self.view.drawer.get_svg(relative=False))
        #ET.dump(tree)
        s=StringIO.StringIO()
        tree.write(s, encoding='utf-8')
        self.element.data = s.getvalue()
        s.close()
        # Update the XML source representation
        if self.sourceview is not None:
            self.sourceview.content_set(self.element.data)
        return True

    def drawer_drag_received(self, widget, context, x, y, selection, targetType, time):
        here=None
        url=None
        title=''
        if targetType == config.data.target_type['annotation']:
            here=self.controller.package.get(unicode(selection.data, 'utf8').splitlines()[0])
        elif targetType == config.data.target_type['view']:
            data=decode_drop_parameters(selection.data)
            v=self.controller.package.get(data['id'])
            if v is None:
                print "Cannot find view", data['id']
                return True
            here=v
            title=self.controller.get_title(v)
            ctx=self.controller.build_context()
            root=ctx.evaluate('here/absolute_url')
            url='%s/action/OpenView?id=%s' % (root, v.id)
        elif targetType == config.data.target_type['uri-list']:
            here=None
            url=unicode(selection.data.splitlines()[0], 'utf8')
            title=url
        else:
            # Invalid drop target
            return True

        if url is None and here is not None:
            ctx=self.controller.build_context(here=here)
            title=self.controller.get_title(here)
            url=ctx.evaluate('here/absolute_url')

        if url is None:
            print "Cannot guess url"
            return True

        s=self.view.drawer.clicked_shape( (x, y) )
        if s is None:
            # Drop on no shape. Create one.
            s = self.view.drawer.shape_class()
            s.name = s.SHAPENAME + _(" created from ") + title
            s.color = self.view.defaultcolor
            s.set_bounds( ( (x, y), (x+20, y+20) ) )
            self.view.drawer.add_object(s)
        # Drop on an existing shape. Update its link attribute
        s.link=url
        s.link_label=title
        return False

    def set_begin(self, t):
        i=image_from_position(self.controller, t)
        self.view.set_background(i)
        return True

    def get_view (self, compact=False):
        """Generate a view widget for editing SVG."""
        vbox=gtk.VBox()

        if self.parent is not None and hasattr(self.parent, 'begin'):
            i=image_from_position(self.controller, self.parent.begin)
            self.view = ShapeEditor(background=i, pixmap_dir=config.data.advenefile('pixmaps'))

            def snapshot_update_cb(context, target):
                if context.globals['position'] == self.parent.begin:
                    # Refresh image
                    i=image_from_position(self.controller, self.parent.begin)
                    self.view.set_background(i)
                return True
            self.rules.append(self.controller.event_handler.internal_rule (event='SnapshotUpdate',
                                                                           method=snapshot_update_cb))

            def annotation_update_cb(context, target):
                i=image_from_position(self.controller, self.parent.begin)
                self.view.set_background(i)
                return True
            self.rules.append(self.controller.event_handler.internal_rule (event='AnnotationEditEnd',
                                                                           method=annotation_update_cb))

        else:
            self.view = ShapeEditor(pixmap_dir=config.data.advenefile('pixmaps'))

        self.parse_svg()

        self.view.drawer.widget.connect('drag-data-received', self.drawer_drag_received)
        self.view.drawer.widget.drag_dest_set(gtk.DEST_DEFAULT_MOTION |
                                              gtk.DEST_DEFAULT_HIGHLIGHT |
                                              gtk.DEST_DEFAULT_ALL,
                                              config.data.drag_type['view']
                                              + config.data.drag_type['annotation']
                                              + config.data.drag_type['uri-list'],
                                              gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_LINK)

        def edit_svg(b):
            vbox.foreach(vbox.remove)
            vbox.add(self.view.widget)

            b=gtk.Button(_("Edit XML"))
            b.connect('clicked', edit_xml)
            vbox.pack_start(b, expand=False)
            self.editing_source=False
            vbox.show_all()
            return True

        def edit_xml(b):
            if self.sourceview is None:
                self.sourceview=TextContentHandler(element=self.element,
                                                   controller=self.controller,
                                                   parent=self.parent)
                self.sourceview.widget=self.sourceview.get_view()

            vbox.foreach(vbox.remove)
            vbox.add(self.sourceview.widget)

            b=gtk.Button(_("Graphical editor"))
            b.connect('clicked', edit_svg)
            vbox.pack_start(b, expand=False)
            self.editing_source=True
            vbox.show_all()
            return True

        edit_svg(None)
        return vbox

class RuleSetContentHandler (ContentHandler):
    """Create a RuleSet edit form for the given element (a view, presumably).
    """
    def can_handle(mimetype):
        res=0
        if mimetype == 'application/x-advene-ruleset':
            res=80
        return res
    can_handle=staticmethod(can_handle)

    def __init__ (self, element, controller=None, parent=None, **kw):
        self.element = element
        self.controller=controller
        self.parent=parent
        self.editable = True
        self.view = None

    def set_editable (self, boolean):
        self.editable = boolean

    def check_validity(self):
        iv=self.edit.invalid_items()
        if iv:
            dialog.message_dialog(
                _("The following items seem to be\ninvalid TALES expressions:\n\n%s") %
                "\n".join(iv),
                icon=gtk.MESSAGE_ERROR)
            return False
        else:
            return True


    def update_element (self):
        """Update the element fields according to the values in the view."""
        if not self.editable:
            return False
        if not self.edit.update_value():
            return False
        self.element.data = self.edit.model.xml_repr()
        return True

    def get_view (self, compact=False):
        """Generate a view widget to edit the ruleset."""
        rs=RuleSet()
        f=self.element.as_file
        rs.from_xml(f, catalog=self.controller.event_handler.catalog)
        f.close()
        self.edit=EditRuleSet(rs,
                              catalog=self.controller.event_handler.catalog,
                              editable=self.editable,
                              controller=self.controller)
        self.view = self.edit.get_packed_widget()

        scroll_win = gtk.ScrolledWindow ()
        scroll_win.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scroll_win.add_with_viewport(self.view)

        return scroll_win

class SimpleQueryContentHandler (ContentHandler):
    """Create a SimpleQuery edit form for the given element (a view, presumably).
    """
    def can_handle(mimetype):
        res=0
        if mimetype == 'application/x-advene-simplequery':
            res=80
        return res
    can_handle=staticmethod(can_handle)

    def __init__ (self, element, controller=None, parent=None, editable=True, **kw):
        self.element = element
        self.controller=controller
        self.parent=parent
        self.editable = editable
        self.view = None

    def check_validity(self):
        iv=self.edit.invalid_items()
        if iv:
            dialog.message_dialog(
                _("The following items seem to be\ninvalid TALES expressions:\n\n%s") %
                "\n".join(iv),
                icon=gtk.MESSAGE_ERROR)
            return False
        else:
            return True

    def set_editable (self, boo):
        self.editable = boo

    def update_element (self):
        """Update the element fields according to the values in the view."""
        if not self.editable:
            return False
        if not self.edit.update_value():
            return False
        self.element.data = self.edit.model.xml_repr()
        # Just to be sure:
        self.element.mimetype = 'application/x-advene-simplequery'
        return True

    def get_view (self, compact=False):
        """Generate a view widget to edit the ruleset."""
        q=SimpleQuery()
        f=self.element.as_file
        q.from_xml(self.element.as_file)
        f.close()

        self.edit=EditQuery(q,
                            controller=self.controller,
                            editable=self.editable)
        self.view = self.edit.get_widget()

        scroll_win = gtk.ScrolledWindow ()
        scroll_win.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scroll_win.add_with_viewport(self.view)

        return scroll_win
