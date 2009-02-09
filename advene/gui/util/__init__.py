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
"""GUI helper methods.
"""

from gettext import gettext as _

import gtk
import gobject
import cgi
import StringIO

import advene.core.config as config
from advene.core.imagecache import ImageCache
from advene.model.cam.annotation import Annotation
from advene.model.cam.relation import Relation
from advene.model.cam.view import View
from advene.model.cam.list import Schema
from advene.model.cam.tag import AnnotationType, RelationType
from advene.model.cam.query import Query
import advene.util.helper as helper

def png_to_pixbuf (png_data, width=None, height=None):
    """Load PNG data into a pixbuf
    """
    loader = gtk.gdk.PixbufLoader ('png')
    if not isinstance(png_data, str):
        png_data=str(png_data)
    try:
        loader.write (png_data, len (png_data))
        pixbuf = loader.get_pixbuf ()
        loader.close ()
    except gobject.GError:
        # The PNG data was invalid.
        pixbuf=gtk.gdk.pixbuf_new_from_file(config.data.advenefile( ( 'pixmaps', 'notavailable.png' ) ))

    if width and not height:
        height = width * pixbuf.get_height() / pixbuf.get_width()
    if height and not width:
        width = height * pixbuf.get_width() / pixbuf.get_height()
    if width and height:
        p=pixbuf.scale_simple(width, height, gtk.gdk.INTERP_BILINEAR)
        return p
    else:
        return pixbuf

def image_from_position(controller, position=None, width=None, height=None):
    # FIXME: should use media id
    i=gtk.Image()
    if position is None:
        position=controller.player.current_position_value
    ic=controller.gui.imagecache
    if ic is None:
        png=ImageCache.not_yet_available_image
    else:
        png=ic[position]
    i.set_from_pixbuf(png_to_pixbuf(png, width=width, height=height))
    return i

def overlay_svg_as_pixbuf(png_data, svg_data, width=None, height=None):

    """Overlay svg graphics over a png image.

    @return: a PNG image
    """
    if not '<svg' in svg_data:
        # Generate pseudo-svg with data
        svg_data="""<svg version='1' preserveAspectRatio="xMinYMin meet" viewBox='0 0 320 200'>
  <text x='10' y='190' fill="white" font-size="24" stroke="black" font-family="sans-serif">
%s
  </text>
</svg>
""" % svg_data

    try:
        loader = gtk.gdk.PixbufLoader('svg')
    except Exception, e:
        print "Unable to load the SVG pixbuf loader: ", str(e)
        loader=None
    if loader is not None:
        try:
            loader.write(svg_data)
            loader.close ()
            p = loader.get_pixbuf ()
            w = p.get_width()
            h = p.get_height()
            pixbuf=png_to_pixbuf (png_data).scale_simple(w, h, gtk.gdk.INTERP_BILINEAR)
            p.composite(pixbuf, 0, 0, w, h, 0, 0, 1.0, 1.0, gtk.gdk.INTERP_BILINEAR, 255)
        except gobject.GError, e:
            # The PNG data was invalid.
            print "Invalid image data", e
            pixbuf=gtk.gdk.pixbuf_new_from_file(config.data.advenefile( ( 'pixmaps', 'notavailable.png' ) ))
    else:
        pixbuf=gtk.gdk.pixbuf_new_from_file(config.data.advenefile( ( 'pixmaps', 'notavailable.png' ) ))

    if width and not height:
        height = 1.0 * width * pixbuf.get_height() / pixbuf.get_width()
    if height and not width:
        width = 1.0 * height * pixbuf.get_width() / pixbuf.get_height()
    if width and height:
        p=pixbuf.scale_simple(int(width), int(height), gtk.gdk.INTERP_BILINEAR)
        return p
    return pixbuf

def overlay_svg_as_png(png_data, svg_data):
    pixbuf=overlay_svg_as_pixbuf(png_data, svg_data)
    s=StringIO.StringIO()
    def pixbuf_save_func(buf):
        s.write(buf)
        return True
    pixbuf.save_to_callback(pixbuf_save_func, "png", {"tEXt::key":"Overlayed SVG"})
    return s.getvalue()

def get_small_stock_button(sid, callback=None, *p):
    b=gtk.Button()
    b.add(gtk.image_new_from_stock(sid, gtk.ICON_SIZE_SMALL_TOOLBAR))
    if callback:
        b.connect('clicked', callback, *p)
    return b

def get_pixmap_button(pixmap, callback=None, *p):
    b=gtk.Button()
    i=gtk.Image()
    i.set_from_file(config.data.advenefile( ( 'pixmaps', pixmap) ))
    b.add(i)
    i.show()
    if callback:
        b.connect('clicked', callback, *p)
    return b

def get_pixmap_toolbutton(pixmap, callback=None, *p):
    if pixmap.startswith('gtk-'):
        # Stock-id
        b=gtk.ToolButton(pixmap)
    else:
        i=gtk.Image()
        i.set_from_file(config.data.advenefile( ( 'pixmaps', pixmap) ))
        b=gtk.ToolButton(icon_widget=i)
        i.show()
    if callback:
        b.connect('clicked', callback, *p)
    return b

color_cache={}

def name2color(color):
    """Return the gtk color for the given color name or code.
    """
    if color:
        # Found a color. Cache it.
        try:
            gtk_color=color_cache[color]
        except KeyError:
            try:
                color_cache[color]=gtk.gdk.color_parse(color)
            except (TypeError, ValueError):
                print "Unable to parse ", color
                color_cache[color]=None
            gtk_color=color_cache[color]
    else:
        gtk_color=None
    return gtk_color

def get_color_style(w, background=None, foreground=None):
    """Return a style for a widget with given colors.
    """
    if background is None:
        background='white'
    if foreground is None:
        foreground='black'
    b=name2color(background)
    f=name2color(foreground)

    style=w.get_style().copy()
    for state in (gtk.STATE_ACTIVE, gtk.STATE_NORMAL,
                  gtk.STATE_SELECTED, gtk.STATE_INSENSITIVE,
                  gtk.STATE_PRELIGHT):
        style.bg[state]=b
        style.fg[state]=f
        style.text[state]=f
        #style.base[state]=white
    return style
    
arrow_up_xpm="""13 16 2 1
       c None
.      c #FF0000
      .
     ...
    .....
   .......
  .........
 ...........
.............
     ...
     ...
     ...
     ...
     ...
     ...
     ...
     ...
     ...
""".splitlines()

arrow_right_xpm="""16 13 2 1
. c None
# c #ff0000
................
..........#.....
..........##....
..........###...
..........####..
###############.
################
###############.
..........####..
..........###...
..........##....
..........#.....
................""".splitlines()


def shaped_window_from_xpm(xpm):
    # Code adapted from evolution/widgets/table/e-table-header-item.c
    pixbuf = gtk.gdk.pixbuf_new_from_xpm_data(xpm)
    pixmap, bitmap = pixbuf.render_pixmap_and_mask()

    gtk.widget_push_colormap(gtk.gdk.rgb_get_colormap())
    win = gtk.Window(gtk.WINDOW_POPUP)
    pix = gtk.Image()
    pix.set_from_pixmap(pixmap, bitmap)
    win.realize()
    win.add(pix)
    win.shape_combine_mask(bitmap, 0, 0)
    gtk.widget_pop_colormap()
    return win

def encode_drop_parameters(**kw):
    """Encode the given parameters as drop parameters.

    @return: a string
    """
    for k in kw:
        if isinstance(kw[k], unicode):
            kw[k]=kw[k].encode('utf8')
        if not isinstance(kw[k], basestring):
            kw[k]=str(kw[k])
    return cgi.urllib.urlencode(kw).encode('utf8')

def decode_drop_parameters(data):
    """Decode the drop parameters.

    @return: a dict.
    """
    return dict( (k, unicode(v, 'utf8'))
                 for (k, v) in cgi.parse_qsl(unicode(data, 'utf8').encode('utf8')) )

def get_target_types(el):
    """Return DND target types for element.
    """
    if isinstance(el, Annotation):
        targets= (config.data.drag_type['annotation']
                  + config.data.drag_type['timestamp']
                  + config.data.drag_type['tag'])
    elif isinstance(el, Relation):
        targets= config.data.drag_type['relation']
    elif isinstance(el, View):
        if helper.get_view_type(el) == 'adhoc':
            targets=config.data.drag_type['adhoc-view']
        else:
            targets=config.data.drag_type['view']
    elif isinstance(el, AnnotationType):
        targets=config.data.drag_type['annotation-type']
    elif isinstance(el, RelationType):
        targets=config.data.drag_type['relation-type']
    elif isinstance(el, Query):
        targets=config.data.drag_type['query']
    elif isinstance(el, Schema):
        targets=config.data.drag_type['schema']
    elif isinstance(el, (int, long)):
        targets=config.data.drag_type['timestamp']
    # FIXME: Resource
    else:
        targets=[]
    targets.extend(config.data.drag_type['uri-list']
                   + config.data.drag_type['text-plain']
                   + config.data.drag_type['TEXT']
                   + config.data.drag_type['STRING'])
    return targets

def drag_data_get_cb(widget, context, selection, targetType, timestamp, controller):
    """Generic drag-data-get handler.

    Usage information:
    this method must be connected passing the controller as user data:
      widget.connect('drag-data-get', drag_data_get_cb, controller)

    and the context must has a _element attribute (defined in a
    'drag-begin' handler for instance).
    """
    typ=config.data.target_type
    el = context._element

    d={ typ['annotation']: Annotation,
        typ['annotation-type']: AnnotationType,
        typ['relation']: Relation,
        typ['relation-type']: RelationType,
        typ['view']: View,
        typ['query']: Query,
        typ['schema']: Schema }
    if targetType in d:
        # Directly pass URIs for Annotation, types and views
        if not isinstance(el, d[targetType]):
            return False
        selection.set(selection.target, 8, el.uri.encode('utf8'))
        return True
    elif targetType == typ['adhoc-view']:
        if helper.get_view_type(el) != 'adhoc':
            return False
        selection.set(selection.target, 8, encode_drop_parameters(id=el.id))
        return True
    elif targetType == typ['uri-list']:
        try:
            ctx=controller.build_context(here=el)
            uri=ctx.evaluate('here/absolute_url')
        except:
            uri="No URI for " + unicode(el)
        selection.set(selection.target, 8, uri.encode('utf8'))
    elif targetType == typ['timestamp']:
        if isinstance(el, (int, long)):
            selection.set(selection.target, 8, encode_drop_parameters(timestamp=el))
        elif isinstance(el, Annotation):
            selection.set(selection.target, 8, encode_drop_parameters(timestamp=el.begin,
                                                                      comment=controller.get_title(el)))
        else:
            print "Inconsistent DND target"
        return True
    elif targetType in (typ['text-plain'], typ['STRING']):
        selection.set(selection.target, 8, controller.get_title(el).encode('utf8'))
    else:
        print "Unknown target type for drag: %d" % targetType
    return True

def contextual_drag_begin(widget, context, element, controller):
    if callable(element):
        element=element()
    context._element=element

    w=gtk.Window(gtk.WINDOW_POPUP)
    w.set_decorated(False)

    bw_style=get_color_style(w, 'black', 'white')
    w.set_style(bw_style)

    v=gtk.VBox()
    v.set_style(bw_style)

    def get_coloured_label(t, color=None):
        l=gtk.Label()
        #l.set_ellipsize(pango.ELLIPSIZE_END)
        if color is None:
            color='white'
        l.set_markup("""<span background="%s" foreground="black">%s</span>""" % (color, t.replace('<', '&lt;')))
        return l
    
    # FIXME: not multi-media compatible
    cache=controller.package.gui.imagecache

    if isinstance(element, (long, int)):
        begin=gtk.image_new_from_pixbuf(png_to_pixbuf (cache.get(element, epsilon=config.data.preferences['bookmark-snapshot-precision']), width=config.data.preferences['drag-snapshot-width']))
        begin.set_style(bw_style)

        l=gtk.Label()
        l.set_style(bw_style)
        l.set_text(helper.format_time(element))
        l.set_style(bw_style)

        v.pack_start(begin, expand=False)
        v.pack_start(l, expand=False)
        w.set_style(bw_style)
        w.set_size_request(long(1.5 * config.data.preferences['drag-snapshot-width']), -1)
    elif isinstance(element, Annotation):
        # Pictures HBox
        h=gtk.HBox()
        h.set_style(bw_style)
        begin=gtk.image_new_from_pixbuf(png_to_pixbuf (cache.get(element.begin), width=config.data.preferences['drag-snapshot-width']))
        begin.set_style(bw_style)
        h.pack_start(begin, expand=False)
        # Padding
        h.pack_start(gtk.HBox(), expand=True)
        end=gtk.image_new_from_pixbuf(png_to_pixbuf (cache.get(element.end), width=config.data.preferences['drag-snapshot-width']))
        end.set_style(bw_style)
        h.pack_start(end, expand=False)
        v.pack_start(h, expand=False)

        l=get_coloured_label(controller.get_title(element), controller.get_element_color(element))
        l.set_style(bw_style)
        v.pack_start(l, expand=False)
        w.set_style(bw_style)
        w.set_size_request(long(2.5 * config.data.preferences['drag-snapshot-width']), -1)
    elif isinstance(element, AnnotationType):
        l=get_coloured_label(_("Annotation Type %(title)s:\n%(count)s") % {
                'title': controller.get_title(element),
                'count': helper.format_element_name('annotation', len(element.annotations)),
                }, controller.get_element_color(element))
        v.pack_start(l, expand=False)
    elif isinstance(element, RelationType):
        l=get_coloured_label(_("Relation Type %(title)s:\n%(count)s") % {
                'title': controller.get_title(element),
                'count': helper.format_element_name('relation', len(element.relations)),
                }, controller.get_element_color(element))
        v.pack_start(l, expand=False)
    else:
        l=get_coloured_label("%s %s" % (helper.get_type(element),
                                        controller.get_title(element)),
                             controller.get_element_color(element))
        v.pack_start(l, expand=False)

    w.add(v)
    w.show_all()
    widget._icon=w
    context.set_icon_widget(w, 0, 0)
    return True

def contextual_drag_end(widget, context):
    if hasattr(widget, '_icon'):
        widget._icon.destroy()
        widget._icon=None
    return True

def enable_drag_source(widget, element, controller):
    """Initialize support for DND from widget.

    element can be either an Advene object instance, or a method which
    returns such an instance. This allows to use this generic method
    with dynamic widgets (which can hold reference to multiple
    elements), such as treeviews or reusable components.
    """
    if callable(element):
        el=element()
    else:
        el=element
    # Generic support
    widget.drag_source_set(gtk.gdk.BUTTON1_MASK,
                           get_target_types(el),
                           gtk.gdk.ACTION_LINK | gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE )
    widget.connect('drag-begin', contextual_drag_begin, element, controller)
    widget.connect('drag-end', contextual_drag_end)
    widget.connect('drag-data-get', drag_data_get_cb, controller)
