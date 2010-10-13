#! /usr/bin/python

# Script de creation du fichier example.cxp

ns_advene = 'http://www.advene.org/ns/advene/'

import os
import libadvene
import libadvene.model.cam.consts
ns_cinelab = libadvene.model.cam.consts.CAM_NS_PREFIX
from libadvene.model.cam.package import Package

p = Package('', create=True)

p.description = "Example Cinelab package"
p.title = "Nosferatu analysis"
p.meta[ns_advene + 'default_utbv'] = 'start_view'

m = p.create_media('m1', '/data/video/Nosferatu.avi')
m.meta[ns_cinelab + 'uri'] = 'http://liris.cnrs.fr/advene/videos/baz.avi'

todo = p.create_user_tag('todo')
todo.title = 'TODO'
todo.description = 'Things to work on'
todo.color = '#ff4444'

important = p.create_user_tag('important')
important.title = 'Important'
important.description = 'Important things to note'
important.color = '#00ff00'

at = p.create_annotation_type('free-text-annotation')
at.title = "Free text annotation"
at.description = "Generic annotation type"
at.color = "#5555ff"
at.element_color = "${here/tag_color}"
at.element_constraint.content.data = 'mimetype=text/plain'
p.associate_user_tag(at, todo)
p.associate_user_tag(at, important)

at2 = p.create_annotation_type('shots')
at.title = "Shots"
at.description = "Shot layout of the movie"
at.color = "#55ff55"
at.element_color = "${here/tag_color}"
at.element_constraint.content.data = 'mimetype=application/json'

a1 = p.create_annotation('a1', m, 1230, 4560, 'text/plain', type=at)
a1.content.data = "First annotation"

a2 = p.create_annotation('a2', m, 4560, 7890, 'image/png', type=at)
datafile = os.path.join( os.path.dirname(os.path.dirname(os.path.abspath(libadvene.__file__))), 'share', 'pixmaps', 'logo_advene.png')
f = open(datafile, 'r')
a2.content_url = "" # force in-backend storage to test with binary data
#a2.content.data = f.read()
f.close()

a3 = p.create_annotation('a3', m, 1230, 4560, 'application/json', type=at2)
a1.content.data = "{ 'num' : 1, 'title': 'Introduction', 'characters': [ 'john doe', 'jane doe' ] }"

p.save_as('/tmp/example.cxp', erase=True)
p.save_as('/tmp/example.czp', erase=True)
