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
"""
Merge packages
==============
"""

import sys

import advene.core.config as config

from libadvene.model.cam.package import Package
from libadvene.model.cam.annotation import Annotation
from libadvene.model.cam.relation import Relation

class Differ:
    """Returns a structure diff of two packages.
    """
    def __init__(self, source=None, destination=None, controller=None):
        self.source=source
        self.destination=destination
        self.controller=controller
        self.source_ids = {}
        # translated ids for different elements with the same id.  The
        # key is the id in the source package, the value the (new) id
        # in the destination package.
        self.translated_ids = {}

    def diff(self):
        """Iterator returning a changelist.

        Structure of returned elements:
        (action_name, source_element, dest_element, action)
        """
        for m in (self.diff_schemas,
                  self.diff_annotation_types,
                  self.diff_relation_types,
                  self.diff_annotations,
                  self.diff_relations,
                  self.diff_views,
                  self.diff_queries,
                  #self.diff_resources,
                  ):
            for d in m():
                yield d

    def check_meta(self, s, d, namespaceid, name):
        ns=config.data.namespace_prefix[namespaceid]
        if s.meta.get(ns+name) != d.meta.get(ns+name):
            return ('update_meta_%s' % name,
                    s, d,
                    lambda s, d: self.update_meta(s, d, namespaceid, name) )
        else:
            return None

    def update_meta(self, s, d, namespaceid, name):
        """Update the meta attribute name from the given namespace.
        """
        ns=config.data.namespace_prefix[namespaceid]
        d.meta[ns+name]=s.meta[ns+name]

    def check_property(self, s, d, name):
        if getattr(s, name) != getattr(d, name):
            return ('update_property_%s' % name,
                    s, d,
                    lambda s, d: self.update_property(s, d, name))
        else:
            return None

    def update_property(self, s, d, name):
        """Update the meta attribute name from the given namespace.
        """
        setattr(d, name, getattr(s, name))

    def diff_generic(self, element_name, s, d):
        if d is None:
            return
        # check type and author/date. If different, it is very
        # likely that it is in fact a new element, with
        # duplicate ids.
        if (
            s.creator != d.creator or s.created != d.created
            or (hasattr(s, 'type') and s.type.id != d.type.id) ):
            yield ('new_%s' % element_name, s, d, getattr(self, 'new_%s' % element_name))
        else:
            # Present. Check if it was modified
            for n in (
                # Common properties
                'description', 'title',
                # Annotation properties
                'begin', 'end',
                # Contentable properties
                'content_mimetype', 'content_data',
                # Type properties
                'mimetype', 'color', 'element_color',
                ):
                if hasattr(s, n):
                    c=self.check_property(s, d, n)
                    if c:
                        yield c
                # FIXME: handle tags

    def diff_schemas(self):
        ids = dict([ (s.id, s) for s in self.destination.own.schemas ])
        self.source_ids['schemas']=ids
        for s in self.source.own.schemas:
            if s.id in ids:
                d=ids[s.id]
                for c in self.diff_generic('schema', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
            else:
                yield ('new', s, None, lambda s, d: self.copy_schema(s) )

    def diff_annotation_types(self):
        ids = dict([ (s.id, s) for s in self.destination.own.annotation_types ])
        self.source_ids['annotation-types']=ids
        for s in self.source.own.annotation_types:
            if s.id in ids:
                d=ids[s.id]
                for c in self.diff_generic('annotation_type', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
            else:
                yield ('new', s, None, lambda s, d: self.copy_annotation_type(s) )

    def diff_relation_types(self):
        ids = dict([ (s.id, s) for s in self.destination.own.relation_types ])
        self.source_ids['relation-types']=ids
        for s in self.source.own.relation_types:
            if s.id in ids:
                d=ids[s.id]
                # Present. Check if it was modified
                for c in self.diff_generic('relation_type', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
                # FIXME: check member types
                #if s.member_types != d.member_types:
                #    yield ('update_member_types', s, d, lambda s, d: d.memsetHackedMemberTypes( s.hackedMemberTypes ))
            else:
                yield ('new', s, None, lambda s, d: self.copy_relation_type(s) )


    def diff_annotations(self):
        ids = dict([ (s.id, s) for s in self.destination.own.annotations ])
        self.source_ids['annotations']=ids
        for s in self.source.own.annotations:
            if s.id in ids:
                d=ids[s.id]
                for c in self.diff_generic('annotation', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
                # FIXME: handle tags
            else:
                yield ('new', s, None, lambda s, d: self.copy_annotation(s) )


    def diff_relations(self):
        ids = dict([ (s.id, s) for s in self.destination.own.relations ])
        self.source_ids['relations']=ids
        for s in self.source.own.relations:
            if s.id in ids:
                d=ids[s.id]
                for c in self.diff_generic('relation', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
                # Check members
                sm=[ a.id for a in s ]
                dm=[ a.id for a in d ]
                if sm != dm:
                    yield ('update_members', s, d, self.update_members)
                # FIXME: handle tags
            else:
                yield ('new', s, None, lambda s, d: self.copy_relation(s) )

    def diff_views(self):
        ids = dict([ (s.id, s) for s in self.destination.own.views ])
        self.source_ids['views']=ids
        for s in self.source.own.views:
            if s.id in ids:
                # Present. Check if it was modified
                d=ids[s.id]
                for c in self.diff_generic('view', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
            else:
                yield ('new', s, None, lambda s, d: self.copy_view(s) )

    def diff_queries(self):
        ids = dict([ (s.id, s) for s in self.destination.own.queries ])
        self.source_ids['queries']=ids
        for s in self.source.own.queries:
            if s.id in ids:
                # Present. Check if it was modified
                d=ids[s.id]
                for c in self.diff_generic('query', s, d):
                    yield c
                    if c[0].startswith('new_'):
                        continue
            else:
                yield ('new', s, None, lambda s, d: self.copy_query(s) )

    def diff_resources(self):
        # FIXME: not implemented yet
        #if self.source.resources is None or self.destination.resources is None:
        #    # FIXME: warning message ?
        #    return
        #sdir=self.source.resources.dir_
        #ddir=self.destination.resources.dir_
        #
        #d=filecmp.dircmp(sdir, ddir)
        #
        #def relative_path(origin, dirname, name):
        #    """Return the relative path (hence id) for the resource 'name' in resource dir 'dirname',
        #    relative to the origin dir.
        #    """
        #    return os.path.join(dirname, name).replace(origin, '')
        #
        #def handle_dircmp(dc):
        #    for n in dc.left_only:
        #        yield ('create_resource',
        #               relative_path(sdir, dc.left, n),
        #               relative_path(ddir, dc.right, n), self.create_resource)
        #    for n in dc.diff_files:
        #        yield ('update_resource',
        #               relative_path(sdir, dc.left, n),
        #               relative_path(ddir, dc.right, n), self.update_resource)
        #
        #for t in handle_dircmp(d):
        #    yield t
        #
        #for sd in d.subdirs.itervalues():
        #    for t in handle_dircmp(sd):
        #        yield t
        print "Resource merge not implemented yet"
        yield

    def copy_schema(self, s):
        el=self.destination.create_schema(id=s.id)
        el.title=s.title or s.id
        return el

    def copy_annotation_type(self, s):
        # Find parent, and create it if necessary
        sch=self.destination.get(s.schema.id)
        if not sch:
            # Create it
            source_schema=self.source.get(s.schema.id)
            sch=self.copy_schema(source_schema)
        el=self.destination.create_annotation_type(id=s.id)
        for p in ('creator', 'created', 'title', 'description', 'mimetype', 'color', 'element_color', 'representation'):
            setattr(el, p, getattr(s, p))
        sch.append(el)
        return el

    def copy_relation_type(self, s):
        # Find parent, and create it if necessary
        sch=self.destination.get(s.schema.id)
        if not sch:
            # Create it
            source_schema=self.source.get(s.schema.id)
            sch=self.copy_schema(source_schema)
        el=self.destination.create_relation_type(id=s.id)
        for p in ('creator', 'created', 'title', 'description', 'mimetype', 'color', 'element_color', 'representation'):
            setattr(el, p, getattr(s, p))
        sch.append(el)
        # FIXME: todo
        # Handle membertypes, ensure that annotation types are defined
        #for m in s.membertypes:
        #    if m == '':
        #        # Any type, no import necessary
        #        continue
        #    if not m.startswith('#'):
        #        print "Cannot handle non-fragment membertypes", m
        #        continue
        #    at=helper.get_id(self.destination.annotationTypes, m[1:])
        #    if not at:
        #        # The annotation type does not exist. Create it.
        #        at=helper.get_id(self.source.annotationTypes, m[1:])
        #        at=self.copy_annotation_type(at)
        # Now we can set member types
        #el.setHackedMemberTypes(s.getHackedMemberTypes())
        return el

    def update_members(self, s, d):
        """Update the relation members.
        """
        sm=[ a.id for a in s ]
        del d[:]
        for i in sm:
            # Handle translated ids
            if i in self.translated_ids:
                i=self.translated_ids[i]
            a=self.destination.get(i)
            if a is None:
                raise "Error: missing annotation %s" % i
            d.append(a)
        return d

    def new_annotation(self, s):
        return self.copy_annotation(s, new_id=True)

    def copy_annotation(self, s, new_id=False):
        """Create a new annotation with a new id.

        Try to keep track of the occurences of its id, to fix them later on.
        """
        if new_id:
            id_=self.destination._idgenerator.get_id(Annotation)
            self.destination._idgenerator.add(id_)
            self.translated_ids[s.id]=id_
        else:
            id_=s.id

        at=self.destination.get(s.type.id)
        if not at:
            # The annotation type does not exist. Create it.
            at=self.copy_annotation_type(self.source.get(s.type.id))
        el=self.destination.create_annotation(id=id_,
                                              type=at,
                                              mimetype=s.mimetype,
                                              begin=s.begin,
                                              end=s.end)
        for p in ('creator', 'created', 'title', 'description', 'content_data'):
            setattr(el, p, getattr(s, p))
        return el

    def copy_relation(self, s, new_id=False):
        if new_id:
            id_=self.destination._idgenerator.get_id(Relation)
            self.destination._idgenerator.add(id_)
            self.translated_ids[s.id]=id_
        else:
            id_=s.id

        rt=self.destination.get(s.type.id)
        if not rt:
            # The annotation type does not exist. Create it.
            rt=self.copy_relation_type(self.source.get(s.type.id))
        # Ensure that annotations exist
        members=[]
        for sa in s:
            # check translated_ids
            i=sa.id
            if i in self.translated_ids:
                i=self.translated_ids[i]

            a=self.destination.annotations.get(i)
            if not a:
                a=self.copy_annotation(sa)
            members.append(a)
        el=self.destination.create_relation(id=id_,
                                            type=rt,
                                            members=members)
        for p in ('creator', 'created', 'title', 'description', 'content_data'):
            setattr(el, p, getattr(s, p))
        return el

    def copy_query(self, s):
        el=self.destination.create_query(id=s.id,
                                         mimetype=s.content.mimetype)
        for p in ('creator', 'created', 'title', 'description', 'content_data'):
            setattr(el, p, getattr(s, p))
        return el

    def copy_view(self, s):
        el=self.destination.create_view(id=s.id,
                                        mimetype=self.content.mimetype)
        # FIXME: ideally, we should try to fix translated_ids in
        # views. Or at least try to signal possible occurrences.
        for p in ('creator', 'created', 'title', 'description', 'content_data'):
            setattr(el, p, getattr(s, p))
        return el

    def create_resource(self, s, d):
        # FIXME: not implemented
        return

    def update_resource(self, s, d):
        # FIXME: not implemented
        return

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "Should provide 2 package names"
        sys.exit(1)

    sourcename=sys.argv[1]
    destname=sys.argv[2]

    print sourcename, destname
    source=Package(uri=sourcename)
    dest=Package(uri=destname)

    differ=Differ(source, dest)
    diff=differ.diff()
    for name, s, d, action in diff:
        print name, unicode(s).encode('utf-8'), unicode(d).encode('utf-8')
        #action(s, d)
    #dest.save('foo.xml')
