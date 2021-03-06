"""
Generic serializer implementation.

Note that the order chosen for XML elements (imports, tags, medias, resources,
annotations, relations, views, queries, lists) is designed to limit the number
of forward references, which makes the work of the parser more difficult.
Forward references are nevetheless still possible in meta-data, tag associated to another tag, list containing another list
"""

import base64
from itertools import chain
from urlparse import urlparse
from xml.etree.ElementTree import Element, ElementTree, SubElement

from libadvene.model.consts import ADVENE_XML, DC_NS_PREFIX
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.serializers.unserialized import \
    iter_unserialized_meta_prefix

NAME = "Generic Advene XML"

EXTENSION = ".bxp" # Advene-2 Xml Package

MIMETYPE = "application/x-advene-bxp"

DEFAULTS = { # default values
  "media@unit": "ms",
  "media@origin": 0,
  "content@mimetype": "text/plain",
}

def make_serializer(package, file_, _standalone_xml=True):
    """Return a serializer that will serialize `package` to `file_`.

    `file_` is a writable file-like object. It is the responsability of the
    caller to close it.

    NB: `_standalone_xml` is an internal parameter which is not part of the
    public interface of serializers.

    The returned object must implement the interface for which
    :class:`_Serializer` is the reference implementation.
    """
    return _Serializer(package, file_, _standalone_xml)

def serialize_to(package, file_, _standalone_xml=True):
    """A shortcut for ``make_serializer(package, file_).serialize()``.

    NB: `_standalone_xml` is an internal parameter which is not part of the
    public interface of serializers.

    See also `make_serializer`.
    """
    return _Serializer(package, file_, _standalone_xml).serialize()


class _Serializer(object):

    def serialize(self):
        """Perform the actual serialization."""

        root = self.root = Element("package", xmlns=self.default_ns)
        package = self.package
        namespaces = package._get_namespaces_as_dict()
        self.namespaces = namespaces
        for uri, prefix in namespaces.iteritems():
            root.set("xmlns:%s" % prefix, uri)
        if package.uri:
            root.set("uri", package.uri)
        # imports
        ximports = SubElement(self.root, "imports")
        for i in package.own.imports:
            self._serialize_import(i, ximports)
        if len(ximports) == 0:
            self.root.remove(ximports)
        # tags
        xtags = SubElement(self.root, "tags")
        for t in package.own.tags:
            self._serialize_tag(t, xtags)
        if len(xtags) == 0:
            self.root.remove(xtags)
        # media
        xmedias = SubElement(self.root, "medias")
        for m in package.own.medias:
            self._serialize_media(m, xmedias)
        if len(xmedias) == 0:
            self.root.remove(xmedias)
        # resources
        xresources = SubElement(self.root, "resources")
        for r in package.own.resources:
            self._serialize_resource(r, xresources)
        if len(xresources) == 0:
            self.root.remove(xresources)
        # annotations
        xannotations = SubElement(self.root, "annotations")
        for a in package.own.annotations:
            self._serialize_annotation(a, xannotations)
        if len(xannotations) == 0:
            self.root.remove(xannotations)
        # relations
        xrelations = SubElement(self.root, "relations")
        for r in package.own.relations:
            self._serialize_relation(r, xrelations)
        if len(xrelations) == 0:
            self.root.remove(xrelations)
        # views
        xviews = SubElement(self.root, "views")
        for v in package.own.views:
            self._serialize_view(v, xviews)
        if len(xviews) == 0:
            self.root.remove(xviews)
        # queries
        xqueries = SubElement(self.root, "queries")
        for q in package.own.queries:
            self._serialize_query(q, xqueries)
        if len(xqueries) == 0:
            self.root.remove(xqueries)
        # lists
        xlists = SubElement(self.root, "lists")
        for L in package.own.lists:
            self._serialize_list(L, xlists)
        if len(xlists) == 0:
            self.root.remove(xlists)
        # external tag associations
        self._serialize_external_tagging(self.root)
        # package meta-data
        self._serialize_meta(package, self.root)

        _indent(self.root)
        ElementTree(self.root).write(self.file, encoding='utf-8')

    # end of the public interface

    def __init__(self, package, file_, _standalone_xml=True):

        # this will be ugly, because ElementTree in python 2.5 does not handle
        # custom namespace prefix, so we just handle them ourselves

        self.package = package
        self.file = file_
        self.unserialized_meta_prefixes = list(iter_unserialized_meta_prefix())
        self.default_ns = ADVENE_XML
        self.standalone_xml = _standalone_xml

    # element serializers

    def _serialize_media(self, m, xmedias, tagname="media"):
        foref = m.frame_of_reference
        if foref.startswith(FOREF_PREFIX):
            attr = {}
            if m.unit != DEFAULTS["media@unit"]:
                attr["unit"] = str(m.unit)
            if m.origin != DEFAULTS["media@origin"]:
                attr["origin"] = str(m.origin)
        else:
            attr = {"frame-of-reference": foref}
        xm = SubElement(xmedias, tagname, id=m.id, url=m.url, **attr)
        self._serialize_element_tags(m, xm)
        self._serialize_meta(m, xm)

    def _serialize_annotation(self, a, xannotations, tagname="annotation"):
        mid = a.media_id
        xa = SubElement(xannotations, tagname, id=a.id,
                       media=mid, begin=str(a.begin), end=str(a.end))
        self._serialize_content(a, xa)
        self._serialize_element_tags(a, xa)
        self._serialize_meta(a, xa)

    def _serialize_relation(self, r, xrelations, tagname="relation"):
        xr = SubElement(xrelations, tagname, id=r.id)
        xmembers = SubElement(xr, "members")
        for m in r.iter_member_ids():
            SubElement(xmembers, "member", {"id-ref":m})
        if len(xmembers) == 0:
            xr.remove(xmembers)
        self._serialize_content(r, xr)
        self._serialize_element_tags(r, xr)
        self._serialize_meta(r, xr)

    def _serialize_list(self, L, xlists, tagname="list"):
        xL = SubElement(xlists, tagname, id=L.id)
        xitems = SubElement(xL, "items")
        for i in L.iter_item_ids():
            SubElement(xitems, "item", {"id-ref":i})
        if len(xitems) == 0:
            xL.remove(xitems)
        self._serialize_element_tags(L, xL)
        self._serialize_meta(L, xL)

    def _serialize_tag(self, t, ximports, tagname="tag"):
        xt = SubElement(ximports, tagname, id=t.id)
        L = [ id for id in t.iter_element_ids(self.package, False)
                    if id.find(":") > 0 ]
        if L:
            ximp = SubElement(xt, "imported-elements")
            for i in L:
                SubElement(ximp, "element", {"id-ref":i})
        self._serialize_element_tags(t, xt)
        self._serialize_meta(t, xt)

    def _serialize_view(self, v, xviews, tagname="view"):
        xv = SubElement(xviews, tagname, id=v.id)
        self._serialize_content(v, xv)
        self._serialize_element_tags(v, xv)
        self._serialize_meta(v, xv)

    def _serialize_query(self, q, xqueries, tagname="query"):
        xq = SubElement(xqueries, tagname, id=q.id)
        self._serialize_content(q, xq)
        self._serialize_element_tags(q, xq)
        self._serialize_meta(q, xq)

    def _serialize_resource(self, r, xresources, tagname="resource"):
        xr = SubElement(xresources, tagname, id=r.id)
        self._serialize_content(r, xr)
        self._serialize_element_tags(r, xr)
        self._serialize_meta(r, xr)

    def _serialize_import(self, i, ximports, tagname="import"):
        xi = SubElement(ximports, tagname, id=i.id, url=i.url)
        if i.uri:
            xi.set("uri", i.uri)
        self._serialize_element_tags(i, xi)
        self._serialize_meta(i, xi)

    # common methods

    def _serialize_content(self, elt, xelt):
        mimetype = elt.content_mimetype
        if mimetype != "x-advene/none":
            xc = SubElement(xelt, "content")
            if mimetype != DEFAULTS["content@mimetype"]:
                xc.set("mimetype", mimetype)
            if elt.content_model_id:
                xc.set("model", elt.content_model_id)
    
            url = elt.content_url
            if url:
                if self.standalone_xml:
                    is_link = (url[:9] != 'packaged:')
                else:
                    is_link = True
                    purl = urlparse(url)
                    scheme, netloc, path = purl[:3]
                    if scheme == 'packaged':
                        url = path[1:]
                    elif scheme == '' and netloc == '' and path[0] != "/":
                        url = "../%s" % url
            else:
                is_link = False

            # if elt.content_url and (elt.content_url[:9] != "packaged:"
            #                         or not self.standalone_xml):
            #     xc.set("url", elt.content_url)
            # else:

            if is_link:
                xc.set("url", url)
            else:
                data = elt.content_data
                if not elt.content_is_textual and len(data):
                    data = base64.encodestring(data)
                    xc.set("encoding", "base64")
                xc.text = data

    def _serialize_meta(self, obj, xobj):
        xm = SubElement(xobj, "meta")
        self._serialize_meta_pairs(xm, obj.iter_meta_ids())
        if len(xm) == 0:
            xobj.remove(xm)
            
    def _serialize_meta_pairs(self, xm, pairs):
        """
        Called by _serialize_meta
        """
        umps = chain(self.unserialized_meta_prefixes, [None,])
        ump = umps.next()

        for k,v in pairs:
            while ump and k > ump:
                if k.startswith(ump):
                    k = None # used below to continue outer loop
                    break
                else:
                    ump = umps.next()
            if k is None: continue

            ns, tag = split_uri_ref(k)
            if ns == self.default_ns:
                xkeyval = SubElement(xm, tag)
            else:
                prefix = self.namespaces.get(ns)
                if prefix is None:
                    xkeyval = SubElement(xm, tag, xmlns=ns)
                else:
                    xkeyval = SubElement(xm, "%s:%s" % (prefix, tag))
            if v.is_id:
                xkeyval.set("id-ref", v)
            else:
                xkeyval.text = v

    def _serialize_element_tags(self, elt, xelt):
        xtags = SubElement(xelt, "tags")
        for t in elt.iter_my_tag_ids(self.package, inherited=False):
            SubElement(xtags, "tag", {"id-ref":t})
        if len(xtags) == 0:
            xelt.remove(xtags)

    def _serialize_external_tagging(self, xpackage):
        xx = SubElement(xpackage, "external-tag-associations")
        pairs = self.package._backend.iter_external_tagging(self.package._id)
        for e, t in pairs:
            xxt = SubElement(xx, "association", element=e)
            xxt.attrib["tag"] = t # can not use kw-argument 'tag' above...
        if len(xx) == 0:
            xpackage.remove(xx)


def _indent(elem, level=0):
    """from http://effbot.org/zone/element-lib.htm#prettyprint"""
    i = "\n" + level*"  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        for child in elem:
            _indent(child, level+1)
            if not child.tail or not child.tail.strip():
                child.tail = i + "  "
        if not child.tail or not child.tail.strip():
            child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def split_uri_ref(uriref):
    """
    Split a URI into the namespace and the suffix parts.
    """
    sharp = uriref.rfind("#")
    slash = uriref.rfind("/")
    cut = max(sharp, slash)
    return uriref[:cut+1], uriref[cut+1:]
