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

import gtk
import re

import advene.core.config as config
from advene.gui.edit.elements import ContentHandler, TextContentHandler
from advene.gui.util import png_to_pixbuf, decode_drop_parameters, get_pixmap_toolbutton, overlay_svg_as_pixbuf

from advene.gui.edit.htmleditor import HTMLEditor, ContextDisplay
import advene.util.helper as helper

name="HTML content handler"

def register(controller=None):
    controller.register_content_handler(HTMLContentHandler)

class AnnotationPlaceholder:
    def __init__(self, annotation=None, controller=None, presentation=None, update_pixbuf=None):
        self.annotation=annotation
        self.controller=controller
        if presentation is None:
            presentation=('snapshot', 'link')
        self.presentation=presentation
        self.update_pixbuf=update_pixbuf
        self.width=160
        # FIXME: how to pass/parse width, height, alt, link ?
        self.rules=[]
        self.pixbuf=self.build_pixbuf()
        self.refresh()

    def cleanup(self):
        for r in self.rules:
            self.controller.event_handler.remove_rule(r, 'internal')
        self.rules=[]

    def process_enclosed_tags(self, typ, tag, attr=None):
        """Process enclosed data.

        typ is in ('start', 'end', 'data').
        if typ == 'data': tag is in fact the data itself.
        if typ == 'start': attr is a dictionary with the attributes
        """
        if typ == 'end' and tag == 'span':
            return False
        return True

    def parse_html(self, tag, attr):
        if attr['class'] == 'advene:annotation':
            self.presentation=attr['advene:presentation'].split(':')
            aid=attr['advene:annotation']
            self.annotation=self.controller.package.get(aid)
            if self.annotation is None:
                print "Problem: non-existent annotation"
            self.refresh()
            return self.pixbuf, self.process_enclosed_tags
        return None, None

    def as_html(self):
        if self.annotation is None:
            return """<span advene:error="Non-existent annotation"></span>"""

        ctx=self.controller.build_context(self.annotation)
        try:
            urlbase=self.controller.server.urlbase.rstrip('/')
        except AttributeError:
            urlbase='http://localhost:1234'
        d={
            'id': self.annotation.id,
            'href': urlbase + ctx.evaluateValue('here/player_url'),
            'imgurl': urlbase + ctx.evaluateValue('here/snapshot_url'),
            'timestamp': helper.format_time(self.annotation.begin),
            'content': self.controller.get_title(self.annotation),
            'urlbase': urlbase,
            }
        data=[ """<span class="advene:annotation" advene:annotation="%s" advene:presentation="%s">""" % (self.annotation.id, ':'.join(self.presentation)) ]

        if 'link' in self.presentation:
            data.append("""<a title="Click to play the movie in Advene" tal:attributes="href package/annotations/%(id)s/player_url" href="%(href)s">""" % d)

        if 'overlay' in self.presentation:
            data.append("""<img title="Click here to play"  width="160" height="100" src="%(urlbase)s/media/overlay/advene/%(id)s"></img>""" % d)
        elif 'snapshot' in self.presentation:
            if 'timestamp' in self.presentation:
                data.append("""<img title="Click here to play"  width="160" height="100" src="%(urlbase)s/media/overlay/advene/%(id)s/fragment/formatted/begin"></img>""" % d)
            else:
                data.append("""<img title="Click here to play" width="160" height="100" tal:attributes="src package/annotations/%(id)s/snapshot_url" src="%(imgurl)s" ></img>""" % d)
        elif 'timestamp' in self.presentation:
            # timestamp without snapshot or overlay
            data.append("""<em tal:content="package/annotations/%(id)s/begin/formatted">%(timestamp)s</em><br>""" % d)

        if 'link' in self.presentation:
            data.append('</a>')

        data.append('</span>')

        return "".join(data)

    def snapshot_updated(self, context, target):
        if self.annotation is not None and abs(context.globals['position'] - self.annotation.begin) <= 20:
            # Update the representation
            self.refresh()
        return True

    def annotation_updated(self, context, target):
        if context.globals['annotation'] == self.annotation:
            self.refresh()
        return True

    def annotation_deleted(self, context, target):
        if context.globals['annotation'] == self.annotation:
            self.annotation=None
            self.cleanup()
            self.refresh()
        return True

    def refresh(self):
        if not self.rules and self.annotation:
            # Now that an annotation is defined, we can connect the notifications
            self.rules.append(self.controller.event_handler.internal_rule (event='AnnotationEditEnd',
                                                                           method=self.annotation_updated))
            self.rules.append(self.controller.event_handler.internal_rule (event='AnnotationDelete',
                                                                           method=self.annotation_deleted))
            self.rules.append(self.controller.event_handler.internal_rule (event='SnapshotUpdate',
                                                                           method=self.snapshot_updated))

        old=self.pixbuf
        new=self.build_pixbuf()
        if not self.update_pixbuf:
            new.composite(old, 0, 0, old.get_width(), old.get_height(),
                          0, 0, 1.0, 1.0, gtk.gdk.INTERP_BILINEAR, 255)
        else:
            self.update_pixbuf(old, new)
        self.pixbuf=new
        return True

    def build_pixbuf(self):
        if self.annotation is None:
            pixbuf=png_to_pixbuf(self.controller.gui.imagecache.not_yet_available_image,
                                 width=self.width)
        elif 'overlay' in self.presentation:
            pixbuf=overlay_svg_as_pixbuf(self.controller.imagecache[self.annotation.media.url][self.annotation.begin],
                                         self.annotation.content.data,
                                         width=self.width)
        elif 'snapshot' in self.presentation:
            if 'timestamp' in self.presentation:
                pixbuf=overlay_svg_as_pixbuf(self.controller.imagecache[self.annotation.media.url][self.annotation.begin],
                                             helper.format_time(self.annotation.begin),
                                             width=self.width)
            else:
                pixbuf=png_to_pixbuf(self.controller.imagecache[self.annotation.media.url][self.annotation.begin],
                                     width=self.width)
        elif 'timestamp' in self.presentation:
            # Generate only a timestamp 
            # FIXME: hardcoded value in viewBox is bad... We should find out the appropriate size.
            loader = gtk.gdk.PixbufLoader('svg')
            loader.write("""<svg version='1'> preserveAspectRatio="xMinYMin meet" viewBox="0 0 220 20">
<text x='0' y='10' fill="black" font-size="12" stroke="black" font-family="sans-serif">
%s
  </text>
</svg>
""" % helper.format_time(self.annotation.begin))
            loader.close ()
            pixbuf = loader.get_pixbuf ()
        else:
            pixbuf=png_to_pixbuf(self.controller.gui.imagecache.not_yet_available_image,
                                 width=self.width)
        pixbuf.as_html=self.as_html
        pixbuf._placeholder=self
        pixbuf._tag='span'
        pixbuf._attr=[]
        return pixbuf

class HTMLContentHandler (ContentHandler):
    """Create a HTML edit form for the given element."""
    def can_handle(mimetype):
        res=0
        if mimetype == 'text/html':
            res=90
        return res
    can_handle=staticmethod(can_handle)

    def __init__ (self, element, controller=None, parent=None, **kw):
        self.element = element
        self.controller=controller
        self.parent=parent
        self.editable = True
        self.fname=None
        self.last_dndtime=None
        self.last_x = None
        self.last_y = None
        # HTMLEditor component (gtk.Textview subclass)
        self.editor = None

        # Widgets holding editors (basic and html)
        self.view = None
        self.sourceview=None

        self.placeholders=[]

        self.editing_source=False

    def close(self):
        for p in self.placeholders:
            p.cleanup()

    def set_editable (self, boolean):
        self.editable = boolean
        if self.sourceview:
            self.sourceview.set_editable(boolean)

    def update_element (self):
        """Update the element fields according to the values in the view."""
        if not self.editable:
            return False

        if self.editing_source:
            self.sourceview.update_element()
            # We applied our modifications to the HTML source, so
            # parse the source again in the HTML editor
            if self.editor is not None:
                self.editor.set_text(self.element.data)
            return True

        if self.editor is None:
            return True

        self.element.data = self.editor.get_html()
        # Update the HTML source representation
        if self.sourceview is not None:
            self.sourceview.content_set(self.element.data)
        return True

    def open_link(self, link=None):
        if link:
            pos=re.findall('/media/play/(\d+)', link)
            if pos:
                # A position was specified. Directly use it.
                self.controller.update_status('set', long(pos[0]))
            else:
                self.controller.open_url(link)
        return True

    def insert_annotation_content(self, choice, annotation, focus=False):
        """
        choice: list of one or more strings: 'snapshot', 'timestamp', 'content', 'overlay'
        """
        a=AnnotationPlaceholder(annotation, self.controller, choice, self.editor.update_pixbuf)
        self.placeholders.append(a)
        self.editor.insert_pixbuf(a.pixbuf)
        if focus:
            self.grab_focus()
        return True

    def grab_focus(self, *p):
        self.editor.grab_focus()
        return True

    def editor_drag_received(self, widget, context, x, y, selection, targetType, time):
        """Handle the drop from an annotation to the editor.
        """
        # FIXME: Upon DND, TextView receives the event twice. Some
        # posts from 2004 signal the same problem, some hacks can be
        # found in existing code :
        #   widget.emit_stop_by_name ("drag-data-received")
        #   context.finish(False, False, time)
        #   widget.stop_emission("drag-data-received")
        # but none of them seems to work here. Just use a basic approach,
        # imagining that nobody is fast enough to really do two DNDs
        # at the same time.
        # But on win32, timestamp is always 0. So we must use x and y information as well.
        if time == self.last_dndtime and x == self.last_x and y == self.last_y:
            return True
        self.last_dndtime=time
        self.last_x=x
        self.last_y=y

        x, y = self.editor.window_to_buffer_coords(gtk.TEXT_WINDOW_TEXT,
                                                   *widget.get_pointer())
        it = self.editor.get_iter_at_location(x, y)
        self.editor.get_buffer().place_cursor(it)

        if targetType == config.data.target_type['annotation']:
            for uri in unicode(selection.data, 'utf8').split('\n'):
                source=self.controller.package.annotations.get(uri)
                if source is None:
                    return True
                m=gtk.Menu()
                for (title, choice) in (
                    (_("Snapshot only"), ['link', 'snapshot', ]),
                    (_("Overlayed snapshot only"), ['link', 'overlay', ]),
                    (_("Timestamp only"), ['link', 'timestamp', ]),
                    (_("Snapshot+timestamp"), ['link', 'snapshot', 'timestamp']),
                    ):
                    i=gtk.MenuItem(title)
                    i.connect('activate', (lambda it, ann, data: self.insert_annotation_content(data, ann, focus=True)), source, choice)
                    m.append(i)
                m.show_all()
                m.popup(None, None, None, 0, gtk.get_current_event_time())
            return True
        elif targetType == config.data.target_type['annotation-type']:
            # FIXME: use splitlines()
            source=self.controller.package.get(unicode(selection.data, 'utf8'))
            # FIXME: propose various choices (insert all annotations, insert title, etc)
            self.editor.get_buffer().insert_at_cursor(source.title)
            return True
        elif targetType == config.data.target_type['timestamp']:
            data=decode_drop_parameters(selection.data)
            t=long(data['timestamp'])
            # FIXME: propose various choices (insert timestamp, insert snapshot, etc)
            self.editor.get_buffer().insert_at_cursor(helper.format_time(t))
            return True
        else:
            print "Unknown target type for drop: %d" % targetType
        return False

    def class_parser(self, tag, attr):
        if attr['class'] == 'advene:annotation':
            a=AnnotationPlaceholder(annotation=None, 
                                    controller=self.controller, 
                                    update_pixbuf=self.editor.update_pixbuf)
            self.placeholders.append(a)
            return a.parse_html(tag, attr)
        return None, None

    def custom_url_loader(self, url):
        """Custom URL loader.

        This method processes URLs internally when possible, instead
        of going through the webserver. This is at the cost of some
        code, and possible discrepancies with the original webcherry
        code. It is absolutely unnecessary on linux/macosx. However,
        win32 (svg?) pixbuf loader is broken wrt. threads, and this is
        the solution to have the overlay() code (and thus the pixbuf
        loader) execute in the main thread.
        """
        m=re.search('/media/overlay/(.+?)/(.+)', url)
        if m:
            (alias, element)=m.groups()
            if '/' in element:
                # There is a TALES expression specifying the overlayed
                # content
                aid, path = element.split('/', 1)
            else:
                aid, path = element, None
            p=self.controller.packages.get(alias)
            if not p:
                return None
            a=p.get(aid)
            if a is None:
                return None
            if path:
                # There is a TALES expression
                path='here/'+path
                ctx=self.controller.build_context(here=a)
                svg_data=unicode( ctx.evaluate(path) )
            elif 'svg' in a.content.mimetype:
                # Overlay svg
                svg_data=a.content.data
            else:
                # Overlay annotation title
                svg_data=self.controller.get_title(a)

            png_data=str(p.imagecache[a.media.url][a.begin])
            return self.controller.gui.overlay(png_data, svg_data)

        # FIXME: not multi-media compatible
        m=re.search('/packages/(.+?)/imagecache/(\d+)', url)
        if m:
            alias, timestamp = m.groups()
            p=self.controller.packages.get(alias)
            if p is None:
                return None
            return str(self.controller.gui.imagecache[long(timestamp)])
        return None

    def contextual_popup(self, ctx=None, menu=None):
        """Popup a contextual menu for the given context.        
        """
        if menu is None:
            menu=gtk.Menu()

        def open_link(i, l):
            self.open_link(l)
            return True

        def goto_position(i, pos):
            self.controller.update_status('set', pos)
            return True

        def select_presentation(i, ap, mode):
            if mode == 'timestamp':
                # Timestamp only
                ap.presentation=[ 'link' ]
            else:
                modes=['overlay', 'snapshot']
                modes.remove(mode)
                try:
                    ap.presentation.remove(modes[0])
                except ValueError:
                    pass
            ap.presentation.append(mode)
            ap.refresh()
            return True

        def new_menuitem(label, action, *params):
            item=gtk.MenuItem(label)
            item.connect('activate', action, *params)
            item.show()
            menu.append(item)
            return item

        if ctx is None:
            ctx=self.editor.get_current_context()

        if ctx:
            if hasattr(ctx[-1], '_placeholder'):
                ap=ctx[-1]._placeholder

                if ap.annotation is not None:
                    new_menuitem(_("Play video"), goto_position, ap.annotation.begin)
                    new_menuitem(_("Timestamp only"), select_presentation, ap, 'timestamp')
                    if 'snapshot' in ap.presentation:
                        new_menuitem(_("Display overlay"), select_presentation, ap, 'overlay')
                    elif 'overlay' in ap.presentation:
                        new_menuitem(_("Display snapshot"), select_presentation, ap, 'snapshot')
                    else:
                        # Timestamp only
                        new_menuitem(_("Display snapshot"), select_presentation, ap, 'snapshot')

            l=[ m for m in ctx if m._tag == 'a' ]
            if l:
                link=dict(l[0]._attr).get('href', None)
                if link:
                    if '/media/play' in link:
                        new_menuitem(_("Play video"), open_link, link)
                    else:
                        new_menuitem(_("Open link"), open_link, link)
        return menu

    def button_press_cb(self, textview, event):
        if not (event.button == 3 or (event.button == 1 and event.type == gtk.gdk._2BUTTON_PRESS)):
            return False

        textwin=textview.get_window(gtk.TEXT_WINDOW_TEXT)
        if event.window != textwin:
            return False
        (x, y) = textview.window_to_buffer_coords(gtk.TEXT_WINDOW_TEXT,
                                                  int(event.x),
                                                  int(event.y))
        it=textview.get_iter_at_location(x, y)
        if it is None:
            print "Error in get_iter_at_location"
            return False
        ctx=self.editor.get_current_context(it)
        if not ctx:
            return False

        if event.button == 3:
            # Right button
            if hasattr(ctx[-1], '_placeholder'):
                # An annotation placeholder is here. Display popup menu.
                menu=self.contextual_popup(ctx)
                menu.popup(None, None, None, 0, event.time)
            return True
        else:
            # Double click with left button
            if hasattr(ctx[-1], '_placeholder'):
                # There is an annotation placeholder
                a=ctx[-1]._placeholder.annotation
                if a is not None:
                    self.controller.update_status('set', a.begin)
                return False

            l=[ m for m in ctx if m._tag == 'a' ]
            if l:
                link=dict(l[0]._attr).get('href', None)
                self.open_link(link)
                return False
        return False

    def get_view (self, compact=False):
        """Generate a view widget for editing HTML."""
        vbox=gtk.VBox()

        self.editor=HTMLEditor()
        self.editor.custom_url_loader=self.custom_url_loader
        self.editor.register_class_parser(self.class_parser)
        try:
            self.editor.set_text(self.element.data)
        except Exception, e:
            self.controller.log(_("HTML editor: cannot parse content (%s)") % unicode(e))

        self.editor.connect('drag-data-received', self.editor_drag_received)
        self.editor.drag_dest_set(gtk.DEST_DEFAULT_MOTION |
                                  gtk.DEST_DEFAULT_HIGHLIGHT |
                                  gtk.DEST_DEFAULT_ALL,
                                  config.data.drag_type['annotation']
                                  + config.data.drag_type['annotation-type']
                                  + config.data.drag_type['timestamp'],
                                  gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_LINK | gtk.gdk.ACTION_ASK )
        self.editor.connect('button-press-event', self.button_press_cb)

        self.view = gtk.VBox()

        def sel_copy(i):
            self.editor.get_buffer().copy_clipboard(gtk.clipboard_get())
            return True

        def sel_cut(i):
            self.editor.get_buffer().cut_clipboard(gtk.clipboard_get())
            return True

        def sel_paste(i):
            self.editor.get_buffer().paste_clipboard(gtk.clipboard_get())
            return True

        def refresh(i):
            self.editor.refresh()
            return True

        def display_header_menu(i):
            m=gtk.Menu()
            for h in (1, 2, 3):
                i=gtk.MenuItem(_("Heading %d") % h)
                i.connect('activate', lambda w, level: self.editor.apply_html_tag('h%d' % level), h)
                m.append(i)
            m.show_all()
            m.popup(None, i, None, 1, gtk.get_current_event_time())
            return True

        tb=gtk.Toolbar()
        vbox.toolbar=tb
        tb.set_style(gtk.TOOLBAR_ICONS)
        for (icon, tooltip, action) in (
            (gtk.STOCK_BOLD, _("Bold"), lambda i: self.editor.apply_html_tag('b')),
            (gtk.STOCK_ITALIC, _("Italic"), lambda i: self.editor.apply_html_tag('i')),
            ("title_icon.png", _("Header"), display_header_menu),
            (None, None, None),
            (gtk.STOCK_COPY, _("Copy"), sel_copy),
            (gtk.STOCK_CUT, _("Cut"), sel_cut),
            (gtk.STOCK_PASTE, _("Paste"), sel_paste),
            (None, None, None),
            (gtk.STOCK_REFRESH, _("Refresh"), refresh),
            ):
            if not config.data.preferences['expert-mode'] and icon == gtk.STOCK_REFRESH:
                continue
            if not icon:
                b=gtk.SeparatorToolItem()
            else:
                b=get_pixmap_toolbutton(icon, action)
                b.set_tooltip(self.tooltips, tooltip)
            tb.insert(b, -1)
            b.show()

        if self.editor.can_undo():
            b=gtk.ToolButton(gtk.STOCK_UNDO)
            b.connect('clicked', lambda i: self.editor.undo())
            b.set_tooltip(self.tooltips, _("Undo"))
            tb.insert(b, -1)
            b.show()

        self.view.pack_start(tb, expand=False)
        sw=gtk.ScrolledWindow()
        sw.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw.add(self.editor)

        context_data=ContextDisplay()
        def cursor_moved(buf, it, mark):
            if mark.get_name() == 'insert':
                context_data.set_context(self.editor.get_current_context(it))
            return True
        self.editor.get_buffer().connect('mark-set', cursor_moved)
        sw2=gtk.ScrolledWindow()
        sw2.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        sw2.add(context_data)

        p=gtk.HPaned()
        p.add1(sw2)
        p.add2(sw)
        # Hide by default
        p.set_position(0)
        p.show_all()
        self.view.add(p)

        def edit_wysiwyg(*p):
            vbox.foreach(vbox.remove)
            vbox.add(self.view)
            self.editing_source=False
            vbox.show_all()
            return True

        def edit_source(*p):
            if self.sourceview is None:
                self.sourceview=TextContentHandler(element=self.element,
                                                   controller=self.controller,
                                                   parent=self.parent)
                self.sourceview.widget=self.sourceview.get_view()
                b=get_pixmap_toolbutton('xml.png', edit_wysiwyg)
                b.set_tooltip(self.tooltips, _("WYSIWYG editor"))
                self.sourceview.widget.toolbar.insert(b, 0)

            vbox.foreach(vbox.remove)
            vbox.add(self.sourceview.widget)
            self.editing_source=True
            vbox.show_all()
            return True

        b=get_pixmap_toolbutton('xml.png', edit_source)
        b.set_tooltip(self.tooltips, _("Edit HTML source"))
        tb.insert(b, 0)

        # FIXME: this test should be activated for the release
        #if config.data.preferences['expert-mode']:
        #    edit_source()
        #else:
        #    edit_wysiwyg()
        edit_wysiwyg()
        return vbox
