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
"""HTML viewer component.

FIXME: add navigation buttons (back, history)
"""

import gtk
import urllib
import urlparse
import re

engine=None
try:
    import webkit
    engine='webkit'
except ImportError:
    try:
        import gtkmozembed
        gtkmozembed.set_comp_path('')
        engine='mozembed'
    except ImportError:
        try:
            import gtkhtml2
            engine='gtkhtml2'
        except ImportError:
            pass

from gettext import gettext as _
from advene.gui.views import AdhocView

class gtkhtml_wrapper:
    def __init__(self, controller=None, notify=None):
        self.controller=controller
        self.notify=notify
        self.history = []
        self.current = ""
        self.widget = self.build_widget()

    def refresh(self, *p):
        self.set_url(self.current)
        return True

    def back(self, *p):
        if len(self.history) <= 1:
            self.log(_("Cannot go back: first item in history"))
        else:
            # Current URL
            u=self.history.pop()
            # Previous one
            self.set_url(self.history[-1])
        return True

    def set_url(self, url):
        self.update_history(url)
        d=self.component.document
        d.clear()

        u=urllib.urlopen(url)

        d.open_stream(u.info().type)
        for l in u:
            d.write_stream (l)

        u.close()
        d.close_stream()

        self.current=url
        if self.notify:
            self.notify(url=url)
        return True

    def get_url(self):
        return self.current

    def update_history(self, url):
        if not self.history:
            self.history.append(url)
        elif self.history[-1] != url:
            self.history.append(url)
        return

    def build_widget(self):
        w=gtk.ScrolledWindow()
        w.set_policy (gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)

        c=gtkhtml2.View()
        c.document=gtkhtml2.Document()

        def request_url(document, url, stream):
            print "request url", url, stream
            pass

        def link_clicked(document, link):
            u=self.get_url()
            if u:
                url=urllib.basejoin(u, link)
            else:
                url=link
            self.set_url(url)
            return True

        c.document.connect('link-clicked', link_clicked)
        c.document.connect('request-url', request_url)

        c.get_vadjustment().set_value(0)
        w.set_hadjustment(c.get_hadjustment())
        w.set_vadjustment(c.get_vadjustment())
        c.document.clear()
        c.set_document(c.document)
        w.add(c)
        self.component=c
        return w

class mozembed_wrapper:
    def __init__(self, controller=None, notify=None):
        self.controller=controller
        self.notify=notify
        self.widget=self.build_widget()

    def refresh(self, *p):
        self.component.reload(0)
        return True

    def back(self, *p):
        self.component.go_back()
        return True

    def set_url(self, url):
        self.component.load_url(url)
        return True

    def get_url(self):
        return self.component.get_location()

    def build_widget(self):
        w=gtkmozembed.MozEmbed()
        # A profile must be initialized, cf
        # http://www.async.com.br/faq/pygtk/index.py?req=show&file=faq19.018.htp
        gtkmozembed.set_profile_path("/tmp", "foobar")

        def update_location(c):
            if self.notify:
                self.notify(url=self.get_url())
            return False

        def update_label(c):
            if self.notify:
                self.notify(label=c.get_link_message())
            return False

        w.connect('location', update_location)
        w.connect('link-message', update_label)
        self.component=w
        return w

class webkit_wrapper:
    def __init__(self, controller=None, notify=None):
        self.controller=controller
        self.notify=notify
        self.no_content_re = re.compile('^(/media/(play|pause|resume|stop)|/action/.+|/application/adhoc/.+)')
        self.widget=self.build_widget()

    def refresh(self, *p):
        self.component.reload()
        return True

    def back(self, *p):
        self.component.go_back()
        return True

    def set_url(self, url):
        self.component.open(url)
        return True

    def build_widget(self):
        w=webkit.WebView()

        def update_location(url):
            l=urlparse.urlparse(url)
            if self.no_content_re.match(l[2]):
                # webkit does not correctly handle 204 return code.
                # Automatically go back.
                # FIXME: to be removed once webkit is fixed.
                self.back()
            if self.notify:
                self.notify(url=url)
            return False

        def update_label(c):
            if self.notify:
                self.notify(label=c.get_link_message())
            return False

        def _loading_start_cb(view, frame):
            self.notify(label="Loading  %s - %s" % (frame.get_title(),
                                                        frame.get_uri()))

        def _loading_stop_cb(view, frame):
            update_location(frame.get_uri())
            pass

        def _loading_progress_cb(view, progress):
            self.notify(label=_("%s%% loaded") % progress)

        def _title_changed_cb(widget, frame, title):
            self.notify(label=_("Title %s") % title)

        def _hover_link_cb(view, title, url):
            
            if not (view and url):
                url=''
            self.notify(label=url)

        def _statusbar_text_changed_cb(view, text):
            #if text:
            self.notify(label=text)

        def _icon_loaded_cb(self):
            print "icon loaded"

        def _selection_changed_cb(self):
            print "selection changed"

        def _navigation_requested_cb(view, frame, networkRequest):
            return 1

        def _javascript_console_message_cb(view, message, line, sourceid):
            pass

        def _javascript_script_alert_cb(view, frame, message):
            pass

        def _javascript_script_confirm_cb(view, frame, message, isConfirmed):
            pass

        def _javascript_script_prompt_cb(view, frame,
                                         message, default, text):
            pass

        w.connect('load-started', _loading_start_cb)
        w.connect('load-progress-changed', _loading_progress_cb)
        w.connect('load-finished', _loading_stop_cb)
        w.connect("title-changed", _title_changed_cb)
        w.connect("hovering-over-link", _hover_link_cb)
        w.connect("status-bar-text-changed",
                              _statusbar_text_changed_cb)
        w.connect("icon-loaded", _icon_loaded_cb)
        w.connect("selection-changed", _selection_changed_cb)
        #w.connect("set-scroll-adjustments",
        #                      _set_scroll_adjustments_cb)
        #w.connect("populate-popup", _populate_popup)

        w.connect("console-message",
                              _javascript_console_message_cb)
        w.connect("script-alert",
                              _javascript_script_alert_cb)
        w.connect("script-confirm",
                              _javascript_script_confirm_cb)
        w.connect("script-prompt",
                              _javascript_script_prompt_cb)

        self.component=w
        s=gtk.ScrolledWindow()
        s.add(w)
        
        return s

class HTMLView(AdhocView):
    _engine = engine
    view_name = _("HTML Viewer")
    view_id = 'htmlview'
    tooltip = _("Embedded HTML widget")
    def __init__ (self, controller=None, url=None):
        super(HTMLView, self).__init__(controller=controller)
        self.close_on_package_load = False
        self.component=None
        self.engine = engine

        self.controller=controller
        self.widget=self.build_widget()
        if url is not None:
            self.open_url(url)

    def notify(self, url=None, label=None):
        if url is not None:
            self.current_url(url)
        if label is not None:
            self.url_label.set_text(label)
        return True

    def open_url(self, url=None):
        self.component.set_url(url)
        return True

    def build_widget(self):
        mapping={ 'webkit': webkit_wrapper,
                  'mozembed': mozembed_wrapper,
                  'gtkhtml2': gtkhtml_wrapper,
                  None: None}
        wrapper=mapping.get(engine)
        if wrapper is None:
            w=gtk.Label(_("No available HTML rendering component"))
            self.component=w
        else:
            self.component = wrapper(controller=self.controller,
                                     notify=self.notify)
            w=self.component.widget

        def utbv_menu(*p):
            if self.controller and self.controller.gui:
                m=self.controller.gui.build_utbv_menu(action=self.open_url)
                m.popup(None, None, None, 0, gtk.get_current_event_time())
            return True

        tb=gtk.Toolbar()
        tb.set_style(gtk.TOOLBAR_ICONS)

        for icon, action in (
            (gtk.STOCK_GO_BACK, self.component.back),
            (gtk.STOCK_REFRESH, self.component.refresh),
            (gtk.STOCK_HOME, utbv_menu),
            ):
            b=gtk.ToolButton(stock_id=icon)
            b.connect('clicked', action)
            tb.insert(b, -1)

        def entry_validated(e):
            self.component.set_url(self.current_url())
            return True

        self.url_entry=gtk.Entry()
        self.url_entry.connect('activate', entry_validated)
        ti=gtk.ToolItem()
        ti.add(self.url_entry)
        ti.set_expand(True)
        tb.insert(ti, -1)

        vbox=gtk.VBox()

        vbox.pack_start(tb, expand=False)

        vbox.add(w)

        self.url_label=gtk.Label('')
        self.url_label.set_alignment(0, 0)
        vbox.pack_start(self.url_label, expand=False)

        return vbox

    def current_url(self, url=None):
        if url is not None:
            self.url_entry.set_text(url)
        return self.url_entry.get_text()
