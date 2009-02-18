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
"""Module displaying the contents of an annotation.
"""

import gtk
from gettext import gettext as _

import advene.core.config as config
from advene.core.imagecache import ImageCache
from advene.gui.views import AdhocView
import advene.util.helper as helper
from advene.gui.util import png_to_pixbuf, overlay_svg_as_pixbuf
from advene.model.cam.annotation import Annotation
from advene.model.cam.tag import AnnotationType

name="Annotation display plugin"

def register(controller):
    controller.register_viewclass(AnnotationDisplay)

class AnnotationDisplay(AdhocView):
    view_name = _("AnnotationDisplay")
    view_id = 'annotationdisplay'
    tooltip = _("Display the contents of an annotation")

    def __init__(self, controller=None, parameters=None, annotation=None):
        super(AnnotationDisplay, self).__init__(controller=controller)
        self.close_on_package_load = True
        self.contextual_actions = ()
        self.controller=controller
        self.annotation=annotation
        self.no_image_pixbuf=png_to_pixbuf(ImageCache.not_yet_available_image, width=50)
        self.widget=self.build_widget()
        self.refresh()

    def set_annotation(self, a=None):
        """This method takes either an annotation, a time value or None as parameter.
        """
        self.annotation=a
        self.refresh()
        return True

    def set_master_view(self, v):
        v.register_slave_view(self)
        self.close_on_package_load = False

    def update_annotation(self, annotation=None, event=None):
        if annotation != self.annotation:
            return True
        if event == 'AnnotationEditEnd':
            self.refresh()
        elif event == 'AnnotationDelete':
            if self.master_view is None:
                # Autonomous view. We should close it.
                self.close()
            else:
                # There is a master view, just empty the representation
                self.set_annotation(None)
        return True

    def refresh(self, *p):
        if self.annotation is None:
            d={ 'title': _("No annotation"),
                'begin': '--:--:--:--',
                'end': '--:--:--:--',
                'contents': '',
                'imagecontents': None}
        elif isinstance(self.annotation, int) or isinstance(self.annotation, long):
            d={ 'title': _("Current time"),
                'begin': helper.format_time(self.annotation),
                'end': '--:--:--:--',
                'contents': '',
                'imagecontents': None}
        elif isinstance(self.annotation, AnnotationType):
            col=self.controller.get_element_color(self.annotation)
            if col:
                title='<span background="%s">Annotation Type <b>%s</b></span>' % (col, self.controller.get_title(self.annotation))
            else:
                title='Annotation Type <b>%s</b>' % self.controller.get_title(self.annotation)
            if len(self.annotation.annotations):
                b=min(a.begin for a in self.annotation.annotations)
                e=max(a.end for a in self.annotation.annotations)
            else:
                b=None
                e=None
            d={ 'title': title,
                'begin': helper.format_time(b),
                'end': helper.format_time(e),
                'contents': _("%(total)s\nId: %(id)s\n\n%(description)s") % {
                    'total': helper.format_element_name('annotation', len(self.annotation.annotations)),
                    'id': self.annotation.id,
                    'description': self.annotation.description,
                    },
                'imagecontents': None,
                }
        else:
            # FIXME: there should be a generic content handler
            # mechanism for basic display of various contents
            col=self.controller.get_element_color(self.annotation)
            if col:
                title='<span background="%s">Annotation <b>%s</b></span>' % (col, self.annotation.id)
            else:
                title='Annotation <b>%s</b>' % self.annotation.id
            d={ 'title': title,
                'begin': helper.format_time(self.annotation.begin),
                'end': helper.format_time(self.annotation.end) }
            svg_data=None
            if self.annotation.content.mimetype.startswith('image/'):
                svg_data=self.annotation.content.data
            elif self.annotation.content.mimetype == 'application/x-advene-zone':
                # Build svg
                data=self.annotation.content.parsed()
                svg_data='''<svg xmlns='http://www.w3.org/2000/svg' version='1' viewBox="0 0 320 300" x='0' y='0' width='320' height='200'><%(shape)s style="fill:none;stroke:green;stroke-width:2;" width="%(width)s%%" height="%(height)s%%" x="%(x)s%%" y="%(y)s%%"></rect></svg>''' % data
            if svg_data:
                pixbuf=overlay_svg_as_pixbuf(self.controller.imagecache[self.annotation.media.url][self.annotation.begin],
                                             self.annotation.content.data)
                d['contents']=''
                d['imagecontents']=pixbuf
            else:
                d['contents']=self.annotation.content.data
                d['imagecontents']=None

        for k, v in d.iteritems():
            if k == 'title':
                self.label[k].set_markup(v)
            elif k == 'imagecontents':
                if v is None:
                    self.sw['imagecontents'].hide()
                    self.sw['contents'].show()
                else:
                    self.sw['imagecontents'].show_all()
                    self.sw['contents'].hide()

                    pixbuf=d['imagecontents']
                    w=self.widget.get_allocation().width - 6
                    width=pixbuf.get_width()
                    height=pixbuf.get_height()
                    if width > w and w > 0:
                        height = 1.0 * w * height / width
                        pixbuf=pixbuf.scale_simple(int(w), int(height), gtk.gdk.INTERP_BILINEAR)
                    self.label['imagecontents'].set_from_pixbuf(pixbuf)
            else:
                self.label[k].set_text(v)
        if self.annotation is None or isinstance(self.annotation, AnnotationType):
            self.label['image'].hide()
        else:
            if isinstance(self.annotation, int) or isinstance(self.annotation, long):
                b=self.annotation
                cache=self.controller.gui.imagecache
            elif isinstance(self.annotation, Annotation):
                b=self.annotation.begin
                cache=self.controller.imagecache[self.annotation.media.url]

            if cache.is_initialized(b, epsilon=config.data.preferences['bookmark-snapshot-precision']):
                self.label['image'].set_from_pixbuf(png_to_pixbuf (cache.get(b, epsilon=config.data.preferences['bookmark-snapshot-precision']), width=config.data.preferences['drag-snapshot-width']))
            elif self.label['image'].get_pixbuf() != self.no_image_pixbuf:
                self.label['image'].set_from_pixbuf(self.no_image_pixbuf)
            self.label['image'].show()
        return False

    def build_widget(self):
        v=gtk.VBox()

        self.label={}
        self.sw={}

        h=gtk.HBox()
        self.label['title']=gtk.Label()
        h.pack_start(self.label['title'], expand=False)
        v.pack_start(h, expand=False)

        h=gtk.HBox()
        self.label['begin']=gtk.Label()
        h.pack_start(self.label['begin'], expand=False)
        l=gtk.Label(' - ')
        h.pack_start(l, expand=False)
        self.label['end']=gtk.Label()
        h.pack_start(self.label['end'], expand=False)
        v.pack_start(h, expand=False)

        fr = gtk.Expander ()
        fr.set_label(_("Screenshot"))
        self.label['image'] = gtk.Image()
        fr.add(self.label['image'])
        fr.set_expanded(True)
        v.pack_start(fr, expand=False)

        f=gtk.Frame(label=_("Contents"))
        c=self.label['contents']=gtk.Label()
        c.set_line_wrap(True)
        c.set_selectable(True)
        c.set_single_line_mode(False)
        c.set_alignment(0.0, 0.0)
        sw=gtk.ScrolledWindow()
        sw.set_policy(gtk.POLICY_NEVER, gtk.POLICY_AUTOMATIC)
        sw.add_with_viewport(c)
        self.sw['contents']=sw

        image=self.label['imagecontents']=gtk.Image()

        swi=gtk.ScrolledWindow()
        swi.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        swi.add_with_viewport(image)
        self.sw['imagecontents']=swi

        vb=gtk.VBox()
        vb.add(sw)
        vb.add(swi)

        f.add(vb)
        v.add(f)

        v.show_all()
        image.hide()
        v.set_no_show_all(True)
        return v
