"""
Cinelab parser implementation.

This parser has been re-implemented to support arbitrary order of package
sub-elements. A such, it can not take advantage of the stream-based parsing
implemented in `advene_xml.Parser` and contains a lot of code redundant with
it. However, we subclass it in order to inherit the implementation of the Parser API (claims_for_parse, etc.) and the `do_or_postpone` mechanism.
"""
# Readability note:
# as there is an term ambiguity between XML element and Cinelab package element
# this code uses the following convention for variable names
# - 'xelt' is the abbreviation of XML element
# - 'celt' is the abbreviation of Cinelab package element

from urlparse import urlparse
from xml.etree.ElementTree import Element

from libadvene.model.cam.consts import CAM_XML
import libadvene.model.cam.util.bookkeeping as bk
import libadvene.model.serializers.cinelab_xml as serializer
from libadvene.model.parsers.advene_xml import Parser as _AdveneXmlParser

"""
Unstable and experimental parser implementation.
"""

import base64
from functools import partial
from os import path
from os.path import exists

from libadvene.model.consts import ADVENE_XML, PARSER_META_PREFIX, PACKAGED_ROOT
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.parsers.base_xml import XmlParserBase
from libadvene.model.parsers.exceptions import ParserError
import libadvene.model.serializers.advene_xml as serializer
from libadvene.util.files import get_path, is_local

class Parser(_AdveneXmlParser):

    NAME = serializer.NAME
    EXTENSION = serializer.EXTENSION
    MIMETYPE = serializer.MIMETYPE
    DEFAULTS = serializer.DEFAULTS
    SERIALIZER = serializer # may be None for some parsers

    # this implementation tries to maximize the reusing of code from 
    # _AdveneXmlParser. It does so by "luring" it into using some methods
    # of self.package instead of others. This is a bit of a hack, but works
    # well... It assumes, however, that the parser is *not* multithreaded.

    _NAMESPACE_URI = CAM_XML

    def __init__(self, file_, package):
        _AdveneXmlParser.__init__(self, file_, package)

    def visit_subsubelements(self, xelt, tag, func_or_children, *args, **kw):
        if isinstance(func_or_children, basestring):
            children, func, args = func_or_children, args[0], args[1:]
        else:
            children, func = tag[:-1], func_or_children

        tag = self.tag_template % tag
        children = self.tag_template % children
        sub = xelt.find(tag)
        if sub is not None:
            for i in sub.findall(children):
                func(i, *args, **kw)

    def manage_package_subelements(self):
        root = self.stream.elem
        # parse the whole XML file; we do not use stream functionalities here,
        # which allows the cinelab format to be very tolerant regarding the
        # order of the XML elements
        self.complete_current()
        # at this point, root contains all the subelements we are interested in
        self.manage_meta(root, self.package)
        visit_subsub = self.visit_subsubelements
        visit_subsub(root, "imports", self.manage_import)
        visit_subsub(root, "tags", self.manage_tag)
        visit_subsub(root, "annotation-types", self.manage_tag,
                     "annotation_type")
        visit_subsub(root, "relation-types", self.manage_tag, "relation_type")
        visit_subsub(root, "medias", self.manage_media)
        visit_subsub(root, "resources", self.manage_simple, "resource")
        visit_subsub(root, "annotations", self.manage_annotation)
        visit_subsub(root, "relations", self.manage_relation)
        visit_subsub(root, "views", self.manage_simple, "view")
        visit_subsub(root, "queries", "query", self.manage_simple, "query")
        visit_subsub(root, "schemas", self.manage_list, "schema")
        visit_subsub(root, "lists", self.manage_list)
        visit_subsub(root, "external-tag-associations", "association",
                     self.manage_association)

    def manage_import(self, xelt):
        id_ = xelt.attrib["id"]
        url = xelt.attrib["url"]
        uri = xelt.get("uri", "")
        celt = self.package._create_import_in_parser(id_, url, uri)
        celt.enter_no_event_section()
        try:
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
            celt.exit_no_event_section()

    def manage_tag(self, xelt, kind="user_tag"):
        creator = getattr(self.package, "create_%s" % kind)
        id_ = xelt.attrib["id"]
        celt = creator(id_)
        celt.enter_no_event_section()
        try:
            self.visit_subsubelements(xelt, "imported-elements", "element",
                                      self.manage_tagged_imported, celt)
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
            celt.exit_no_event_section()        

    def manage_media(self, xelt):
        id_ = xelt.attrib["id"]
        url = xelt.attrib["url"]
        foref = xelt.get("frame-of-reference") # for backward compatibility
        if foref is None:
            unit = xelt.get("unit", self.DEFAULTS["media@unit"])
            origin = xelt.get("origin", self.DEFAULTS["media@origin"])
            foref = "%s%s;o=%s" % (FOREF_PREFIX, unit, origin)
        celt = self.package.create_media(id_, url, foref)
        celt.enter_no_event_section()
        try:
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
            celt.exit_no_event_section()

    def manage_simple(self, xelt, kind):
        creator = getattr(self.package, "create_%s" % kind)
        id_ = xelt.attrib["id"]
        args, content_model, content_data = self.manage_content(xelt)
        celt = creator(id_, *args)
        celt.enter_no_event_section()
        try:
            if content_model:
                self.do_or_postpone(content_model, celt._set_content_model)
            if content_data:
                celt.content_data = content_data
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
             celt.exit_no_event_section()

    def manage_annotation(self, xelt):
        id_ = xelt.attrib["id"]
        media = xelt.attrib["media"]
        if media.find(":") <= 0: # same package
            media = self.package.get(media)
        if media is None:
            raise ParserError("unknown media %s" % xelt.attrib["media"])
        begin = xelt.attrib["begin"]
        try:
            begin = int(begin)
        except ValueError:
            raise ParserError("annotation %s has invalid begin %s"
                              % (id_, begin))
        end = xelt.attrib["end"]
        try:
            end = int(end)
        except ValueError:
            raise ParserError("annotation %s has invalid end %s"
                              % (id_, end))
        if end < begin:
            raise ParserError("end is before begin in %s" % id_)
        args, content_model, content_data = self.manage_content(xelt)
        celt = self.package.create_annotation(id_, media, begin, end, *args)
        celt.enter_no_event_section()
        try:
            if content_model:
                self.do_or_postpone(content_model, celt._set_content_model)
            if content_data:
                celt.content_data = content_data
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
            celt.exit_no_event_section()

    def manage_relation(self, xelt):
        id_ = xelt.attrib["id"]
        args, content_model, content_data = self.manage_content(xelt, False)
        celt = self.package.create_relation(id_, *args)
        celt.enter_no_event_section()
        try:
            if content_model:
                self.do_or_postpone(content_model, celt._set_content_model)
            if content_data:
                celt.content_data = content_data
            self.visit_subsubelements(xelt, "members", self.manage_member, celt)
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
             celt.exit_no_event_section()

    def manage_list(self, xelt, kind="user_list"):
        creator = getattr(self.package, "create_%s" % kind)
        id_ = xelt.attrib["id"]
        celt = creator(id_)
        celt.enter_no_event_section()
        try:
            self.visit_subsubelements(xelt, "items", self.manage_item, celt,
                                      [0])
            self.visit_subsubelements(xelt, "tags", self.manage_tag_on, celt)
            self.manage_meta(xelt, celt)
        finally:
             celt.exit_no_event_section()

    def manage_association(self, xelt):
        elt_id = xelt.attrib["element"]
        tag_id = xelt.attrib["tag"]
        # both tag and element should be imported, so no check
        self.package.associate_user_tag(elt_id, tag_id)

    def manage_tag_on(self, tag_xelt, celt):
        id_ = tag_xelt.attrib["id-ref"]
        self.do_or_postpone(id_,
                            partial(self.package.associate_user_tag, celt))

    def manage_meta(self, xelt, celt):
        meta_tag = self.tag_template % "meta"
        meta_xelt = xelt.find(meta_tag)
        if meta_xelt is not None:
            for child in meta_xelt:
                key = child.tag
                if key.startswith("{"):
                    cut = key.find("}")
                    key = key[1:cut] + key[cut+1:]
                val = child.get("id-ref")
                if val is None:
                    text = child.text or "" # because child.text could be None
                    celt.enter_no_event_section()
                    try:
                        celt.set_meta(key, text, False)
                    finally:
                        celt.exit_no_event_section()
                elif val.find(":") > 0: # imported
                    celt.enter_no_event_section()
                    try:
                        celt.set_meta(key, val, True)
                    finally:
                        celt.exit_no_event_section()
                else:
                    self.do_or_postpone(val, partial(celt.set_meta, key))
    
        package = self.package
        if celt is not package:
            creator = celt.get_meta(_CREATOR, None)
            created = celt.get_meta(_CREATED, None)
            if creator is None:
                celt.set_meta(_CREATOR, package.creator)
            if created is None:
                celt.set_meta(_CREATED, package.created)
            if celt.get_meta(_CONTRIBUTOR, None) is None:
                celt.set_meta(_CONTRIBUTOR, creator or package.contributor)
            if celt.get_meta(_MODIFIED, None) is None:
                celt.set_meta(_MODIFIED, created or package.modified)
                

    def manage_tagged_imported(self, imp_xelt, tag_celt):
        id_ = imp_xelt.attrib["id-ref"]
        # should only be imported, so no check
        self.package.associate_user_tag(id_, tag_celt)

    def manage_content(self, xelt, required=True):
        content_tag = self.tag_template % "content"
        content_xelt = xelt.find(content_tag)
        if not required and content_xelt is None:
            return [ "x-advene/none", "", "" ], None, None

        mimetype = content_xelt.get("mimetype",
                                    self.DEFAULTS["content@mimetype"])
        url = content_xelt.get("url", "")
        if url and not self.standalone_xml:
            purl = urlparse(url)
            scheme, netloc, path = purl[:3]
            if scheme == '' and netloc == '':
                if path.startswith("../"):
                    url = path[3:] # make URL relative to package URI
                elif not path.startswith("/"):
                    url = "packaged:/%s" % path
        args = [mimetype , "", url]
        content_model = content_xelt.get("model", "")
        encoding = content_xelt.get("encoding", "")
        if len(content_xelt):
            raise ParserError("%s: for XML contents, use &lt;tag> or CDATA"
                              % xelt.attrib["id"])
        data = content_xelt.text
        if url and data and data.strip():
            raise ParserError("%s: content has both url (%s) and data" %
                              (xelt.attrib["id"], url))
        elif data:
            if encoding:
                if encoding == "base64":
                    data = base64.decodestring(data)
                else:
                    raise ParserError("encoding %s is not supported", encoding)
        return args, content_model, data

    def manage_member(self, xelt, rel_celt):
        a = xelt.attrib["id-ref"]
        if ":" not in a:
            a = self.package.get(a)
        rel_celt.append(a)

    def manage_item(self, xelt, list_celt, c):
        # c is a 1-item list containing the virtual length of the list,
        # i.e. the length taking into account the postponed elements
        # it is used to insert postponed elements at the right index
        id_ = xelt.attrib["id-ref"]
        self.do_or_postpone(id_,
                            list_celt.append, # if now
                            partial(list_celt.insert, c[0])) # if postponed
        c[0] += 1

#

_CAM_PACKAGE = "{%s}package" % CAM_XML
_CAM_META = "{%s}meta" % CAM_XML
_CREATOR = bk.CREATOR
_CREATED = bk.CREATED
_CONTRIBUTOR = bk.CONTRIBUTOR
_MODIFIED = bk.MODIFIED
