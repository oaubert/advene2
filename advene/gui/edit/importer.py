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
"""GUI to import external file formats.
"""
import os
import gtk

from gettext import gettext as _

import advene.core.config as config
import advene.gui.popup
from advene.gui.util import dialog
from libadvene.model.cam.package import Package
from advene.gui.edit.merge import Merger

from advene.gui.views import AdhocView

dummy_advene_importer = object()

class ExternalImporter(AdhocView):
    view_name = _("Importer")
    view_id = 'importerview'

    def __init__(self, controller=None, parameters=None):
        super(ExternalImporter, self).__init__(controller=controller)
        self.controller=controller
        self.parameters=parameters

        self.close_on_package_load = False
        self.contextual_actions = ()
        self.options={
            }

        self.widget=self.build_widget()

    def update_importers(self):
        n=self.filename_entry.get_text()
        model=self.importers.get_model()
        model.clear()
        if n.lower().endswith('.azp'):
            model.append( ( _("Advene package importer"), dummy_advene_importer, None) )
            self.importers.set_active(0)
            self.convert_button.set_sensitive(True)
            return
        if (os.path.exists(n) and not os.path.isdir(n)) or n.startswith('http:'):
            # Valid filename. Guess importers
            valid, invalid=advene.util.importer.get_valid_importers(n)
            for i in valid:
                model.append( ( i.name, i, None) )
            if n.lower().endswith('.xml'):
                model.append( ( _("Advene package importer"), dummy_advene_importer, None) )
            if valid:
                self.importers.set_active(0)
            if invalid:
                model.append( ( "--- " + _("Not likely") + " ---", None, None) )
                for i in invalid:
                    model.append( (i.name, i, None) )
            self.convert_button.set_sensitive(True)
        else:
            # Invalid filenames. Empty importers and disable convert button
            #model.append( (_("Possible importers"), None, None) )
            for i in advene.util.importer.IMPORTERS:
                model.append( (i.name, i, None) )
            self.importers.set_active(0)
            self.convert_button.set_sensitive(False)

        return True

    def convert_file(self, b, *p):
        b.set_sensitive(False)
        ic=self.importers.get_current_element()
        fname=self.filename_entry.get_text()
        self.widget.get_toplevel().set_title(_('Importing %s') % os.path.basename(fname))

        if ic == dummy_advene_importer:
            # Invoke the package merge functionality.
            try:
                source=Package(uri=fname)
            except Exception, e:
                self.log("Cannot load %s file: %s" % (fname, unicode(e)))
                return True
            m=Merger(self.controller, sourcepackage=source, destpackage=self.controller.package)
            m.popup()
            self.close()
            return True

        if ic is None:
            return True
        i=ic(controller=self.controller, callback=self.progress_callback)
        i.package=self.controller.package
        i.process_file(fname)
        self.progress_callback(1.0)
        self.controller.package._modified = True
        self.controller.notify("PackageActivate", package=self.controller.package)
        self.close()
        mes=_('Completed conversion from file %(filename)s :\n%(statistics)s') % {
            'filename': fname,
            'statistics': i.statistics_formatted() }
        dialog.message_dialog(mes, modal=False)
        self.log(mes)
        return True

    def progress_callback(self, value=None, label=None):
        if value is None:
            self.progressbar.pulse()
        else:
            self.progressbar.set_fraction(value)
        if label is not None:
            self.progressbar.set_text(label)
        while gtk.events_pending():
            gtk.main_iteration()
        return True

    def build_widget(self):
        vbox=gtk.VBox()

        def updated_filename(entry):
            self.update_importers()
            return True

        def select_filename(b):
            if config.data.path['data']:
                d=config.data.path['data']
            else:
                d=None
            filename=dialog.get_filename(title=_("Choose the file to import"),
                                                  action=gtk.FILE_CHOOSER_ACTION_OPEN,
                                                  button=gtk.STOCK_OPEN,
                                                  default_dir=d,
                                                  filter='any')
            if not filename:
                return True
            self.filename_entry.set_text(filename)
            return True

        line=gtk.HBox()
        vbox.pack_start(line, expand=False)

        line.pack_start(gtk.Label(_("Filename")), expand=False)
        self.filename_entry=gtk.Entry()
        self.filename_entry.connect('changed', updated_filename)
        line.pack_start(self.filename_entry)

        self.progressbar=gtk.ProgressBar()
        vbox.pack_start(self.progressbar, expand=False)

        b=gtk.Button(stock=gtk.STOCK_OPEN)
        b.connect('clicked', select_filename)
        line.pack_start(b, expand=False)

        # Importer choice list
        line=gtk.HBox()
        vbox.pack_start(line, expand=False)

        line.pack_start(gtk.Label(_("Import filter")), expand=False)
        self.importers=dialog.list_selector_widget([], None)
        line.pack_start(self.importers, expand=False)

        bb=gtk.HButtonBox()

        b=gtk.Button(stock=gtk.STOCK_CONVERT)
        b.connect('clicked', self.convert_file)
        b.set_sensitive(False)
        bb.pack_start(b, expand=False)
        self.convert_button=b

        vbox.buttonbox=bb
        vbox.pack_start(bb, expand=False)

        self.update_importers()

        vbox.show_all()

        return vbox
