"""
Cinelab RDF/XML serializer implementation.
"""
import base64
from bisect import insort

from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef, XSD
from rdflib.namespace import DC, NamespaceManager

from libadvene.model.cam.consts import CAM_NS_PREFIX, CAM_TYPE, CAMSYS_TYPE
from libadvene.model.cam.util.bookkeeping import iter_filtered_meta_ids
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.serializers.unserialized import \
    iter_unserialized_meta_prefix

from urllib import quote_plus

NAME = "Cinelab Advene RDF/XML"

EXTENSION = ".rdf"

MIMETYPE = "application/rdf+xml"

_FORMAT = "xml"

CLD = Namespace(CAM_NS_PREFIX + "ld#")
MA = Namespace("http://www.w3.org/ns/ma-ont#")
DEFAULT_FOREF = URIRef(FOREF_PREFIX + "ms;o=0")

class CinelabNSManager(NamespaceManager):
    """
    I override NamespaceManager to change its default prefixes.

    This is done through a hack, as rdflib does not provide a clean way to do it.
    """
    def __init__(self, graph):
        self.bind = lambda *a: None # disable the bind method
        NamespaceManager.__init__(self, graph)
        del self.bind # restore original bind method
        self.bind("", str(CLD))
        self.bind("ma", MA)
        self.bind("rdf", RDF)
        self.bind("cam", CAM_NS_PREFIX)


def make_serializer(package, file_):
    """Return a serializer that will serialize `package` to `file_`.

    `file_` is a writable file-like object. It is the responsibility of the
    caller to close it.

    The returned object must implement the interface for which
    :class:`advene_xml._Serializer` is the reference implementation.
    """
    return _Serializer(package, file_, _FORMAT)

def serialize_to(package, file_):
    """A shortcut for ``make_serializer(package, file_).serialize()``.

    See also `make_serializer`.
    """
    return _Serializer(package, file_, _FORMAT).serialize()

class _Serializer(object):

    def serialize(self):
        """Perform the actual serialization."""
        self.prepare_graph()
        self.graph.serialize(self.file, self.format)

    # end of the public interface of Serializer

    def prepare_graph(self):
        """Serializes into rdflib.Graph self.graph, but not in the given file."""

        package = self.package

        graph = self.graph = Graph()
        graph.namespace_manager = CinelabNSManager(graph)
        add = graph.add

        namespaces = package._get_namespaces_as_dict()
        for ns, prefix in namespaces.items():
            graph.bind(prefix, ns)

        add((self.package_uri, RDF.type, CLD.Package))
        if package.uri and package.uri != package.url:
            add((self.package_uri, CLD.url, Literal(package.uri, datatype=XSD.anyURI)))

        for i in package.own.imports:
            for triple in self._serialize_import(i):
                add(triple)

        for i in package.own.annotation_types:
            for triple in self._serialize_tag(i, CLD.AnnotationType):
                add(triple)

        for i in package.own.relation_types:
            for triple in self._serialize_tag(i, CLD.RelationType):
                add(triple)

        for i in package.own.user_tags:
            for triple in self._serialize_tag(i, CLD.UserTag):
                add(triple)

        for i in package.own.medias:
            for triple in self._serialize_media(i):
                add(triple)

        for i in package.own.resources:
            for triple in self._serialize_resource(i, CLD.Resource):
                add(triple)

        for i in package.own.annotations:
            for triple in self._serialize_annotation(i):
                add(triple)

        for i in package.own.relations:
            for triple in self._serialize_relation(i):
                add(triple)

        for i in package.own.views:
            for triple in self._serialize_resource(i, CLD.View):
                add(triple)

        for i in package.own.queries:
            for triple in self._serialize_resource(i, CLD.Query):
                add(triple)

        for i in package.own.schemas:
            for triple in self._serialize_list(i, CLD.Schema):
                add(triple)

        for i in package.own.user_lists:
            for triple in self._serialize_list(i, CLD.UserList):
                add(triple)

        for triple in self._serialize_meta(package, self.package_uri):
            add(triple)

        for triple in self._serialize_external_tagging():
            add(triple)

    def __init__(self, package, file_, format):

        self.package = package
        self.package_uri = URIRef(package.uri or package.url)
        self.graph = None
        self.file = file_
        self.format = format
        self.unserialized_meta_prefixes = list(iter_unserialized_meta_prefix())
        insort(self.unserialized_meta_prefixes, CAM_TYPE)
        insort(self.unserialized_meta_prefixes, CAMSYS_TYPE)
        insort(self.unserialized_meta_prefixes, CLD.fragDim)
        self.unserialized_meta_prefixes.append(None)

    # element serializers

    def _serialize_media(self, m):
        muri = self._coin_uri(m)
        mmuri = URIRef(m.uri or m.url)

        yield (self.package_uri, CLD.hasElement, muri)
        yield (muri, RDF.type, CLD.Media)
        yield (muri, CLD.represents, mmuri)
        yield (mmuri, RDF.type, MA.MediaResource)

        if m.uri and m.uri != m.url:
            yield(mmuri, MA.locator, Literal(m.url, datatype=XSD.anyURI))

        foref = m.frame_of_reference
        if foref != DEFAULT_FOREF:
            yield(muri, CLD.hasFrameOfReference, URIRef(foref))

        for triple in self._serialize_element_tags(m, muri):
            yield triple
        for triple in self._serialize_meta(m, muri):
            yield triple

    def _serialize_annotation(self, a):
        """
        Serialize a in RDF.

        :param a: an annotation
        :return: None

        If the associated media is in the same package,
        and if its associated unit is seconds or milliseconds,
        then the fragment will be represented by a media fragment URI.

        In all other cases,
        the fragment will be represented by a blank node
        with properties cld:hasMediaElement, cld:begin and cld:end .
        """
        auri = self._coin_uri(a)

        yield (self.package_uri, CLD.hasElement, auri)
        yield (auri, RDF.type, CLD.Annotation)

        atyp = a.get_meta_id(CAM_TYPE, None)
        if atyp is not None:
            yield (auri, CLD.hasAType, self._coin_uri_from_id(atyp))

        begin = a.begin
        end = a.end
        use_media_fragment_uri = (
            a.media_id.find(":") <= 0
            and a.media.frame_of_reference.startswith(FOREF_PREFIX)
            and a.media.unit in ("s", "ms")
        )
        if use_media_fragment_uri:
            m = a.media
            mmuri = URIRef(m.uri or m.url)
            begin -= m.origin
            end -= m.origin
            if m.unit == "ms":
                begin = "{}.{}".format(begin / 1000, begin % 1000)
                end = "{}.{}".format(end / 1000, end % 1000)

            other_dimensions = ""
            xywh = a.get_meta(CLD.fragDimXywh, None)
            if xywh is not None:
                other_dimensions = "{}&xywh={}".format(other_dimensions, xywh)
            track = a.get_meta(CLD.fragDimTrack, None)
            if track is not None:
                other_dimensions = "{}&track={}".format(other_dimensions, track)
            id = a.get_meta(CLD.fragDimId, None)
            if id is not None:
                other_dimensions = "{}&id={}".format(other_dimensions, id)

            fnode = URIRef("{}#t={},{}{}"
                .format(mmuri, begin, end, other_dimensions))
            yield (mmuri, MA.hasFragment, fnode)
        else:
            fnode = BNode()
            yield (fnode, CLD.hasMediaElement, self._coin_uri_from_id(a.media_id))
            yield (fnode, CLD.begin, Literal(begin))
            yield (fnode, CLD.end, Literal(end))

        yield(auri, CLD.hasFragment, fnode)

        for triple in self._serialize_content(a, auri):
            yield triple
        for triple in self._serialize_element_tags(a, auri):
            yield triple
        for triple in self._serialize_meta(a, auri):
            yield triple

    def _serialize_relation(self, r):
        ruri = self._coin_uri(r)

        yield (self.package_uri, CLD.hasElement, ruri)
        yield (ruri, RDF.type, CLD.Relation)

        rtyp = r.get_meta_id(CAM_TYPE, None)
        rturi = None
        if rtyp is not None:
            rturi = self._coin_uri_from_id(rtyp)
            yield (ruri, CLD.hasRType, rturi)

        members = list(r.iter_member_ids())
        for triple in self._serialize_rdf_list(ruri, CLD.hasMembers, members):
            yield triple

        for triple in self._serialize_content(r, ruri):
            yield triple
        for triple in self._serialize_element_tags(r, ruri):
            yield triple
        for triple in self._serialize_meta(r, ruri):
            yield triple

        # also, if relation has exactly 2 members, reflect it as an arc
        if rturi is not None and len(members) == 2:
            yield (self._coin_uri_from_id(members[0]),
                   rturi,
                   self._coin_uri_from_id(members[1]))
            yield (rturi, RDF.type, CLD.RelationType)


    def _serialize_list(self, L, typ):
        luri = self._coin_uri(L)

        yield (self.package_uri, CLD.hasElement, luri)
        yield (luri, RDF.type, typ)

        items = list(L.iter_item_ids())
        for triple in self._serialize_rdf_list(luri, CLD.hasItems, items):
            yield triple

        for triple in self._serialize_element_tags(L, luri):
            yield triple
        for triple in self._serialize_meta(L, luri):
            yield triple


    def _serialize_tag(self, t, typ):
        turi = self._coin_uri(t)

        yield (self.package_uri, CLD.hasElement, turi)
        yield (turi, RDF.type, typ)

        for i in t.iter_element_ids(self.package, False):
            if i.find(":") > 0: # imported element
                yield (self._coin_uri_from_id(i), CLD.taggedWith, turi)

        for triple in self._serialize_element_tags(t, turi):
            yield triple
        for triple in self._serialize_meta(t, turi):
            yield triple


    def _serialize_resource(self, r, typ):
        ruri = self._coin_uri(r)

        yield (self.package_uri, CLD.hasElement, ruri)
        yield (ruri, RDF.type, typ)

        for triple in self._serialize_content(r, ruri):
            yield triple
        for triple in self._serialize_element_tags(r, ruri):
            yield triple
        for triple in self._serialize_meta(r, ruri):
            yield triple

    def _serialize_import(self, i):
        iuri = self._coin_uri(i)

        yield (self.package_uri, CLD.hasElement, iuri)
        yield (iuri, RDF.type, CLD.Import)

        puri = URIRef(i.uri or i.url)
        yield (iuri, CLD.hasImportedPackage, puri)
        if i.uri and i.uri != i.url:
            yield (puri, CLD.url, Literal(i.url, datatype=XSD.anyURI))

        for triple in self._serialize_element_tags(i, iuri):
            yield triple
        for triple in self._serialize_meta(i, iuri):
            yield triple

        # also express import directly
        yield (self.package_uri, CLD.imports, puri)

    # common methods

    def _serialize_content(self, elt, uri):
        mimetype = elt.content_mimetype
        if mimetype == "x-advene/none":
            return

        url = elt.content_url
        is_link = (url and url[:9] != 'packaged:')
        if is_link:
            node = URIRef(url)
        else:
            node = BNode()

        yield (uri, CLD.hasContent, node)
        yield (node, CLD.mimetype, Literal(mimetype))
        content_model_id = elt.content_model_id
        if content_model_id:
            yield (node, CLD.hasModel, self._coin_uri_from_id(content_model_id))

        if not is_link:
            data = elt.content_data
            datatype = None
            if not elt.content_is_textual and len(data):
                data = base64.encodestring(data)
                datatype = CLD.base64
            yield (node, CLD.data, Literal(data, datatype=datatype))

    def _serialize_meta(self, obj, uri):
        """
        Transform pairs in a Json-friendly form.

        Assumes that pairs is sorted according to the first component (key).
        """
        ret = {}
        umps = iter(self.unserialized_meta_prefixes)
        ump = umps.next()

        for k, v in iter_filtered_meta_ids(obj):
            while ump and k >= ump:
                if k.startswith(ump):
                    k = None # used below to continue outer loop
                    break
                else:
                    ump = umps.next()
            if k is None:
                continue

            if getattr(v, "is_id", None):
                obj = self._coin_uri_from_id(v)
            else:
                obj = Literal(v)
            yield (uri, URIRef(k), obj)

    def _serialize_element_tags(self, elt, uri):
        for i in elt.iter_my_user_tag_ids(self.package, inherited=False):
            yield (uri, CLD.taggedWith, self._coin_uri_from_id(i))

    def _serialize_external_tagging(self):
        for elt, tag in self.package._backend.iter_external_tagging(self.package._id):
            yield (self._coin_uri_from_id(elt), CLD.taggedWith, self._coin_uri_from_id(tag))

    def _serialize_rdf_list(self, subj, pred, lst):
        for i in lst:
            node = BNode()
            yield (subj, pred, node)
            yield (node, RDF.first, self._coin_uri_from_id(i))
            subj = node
            pred = RDF.rest
        yield (subj, pred, RDF.nil)

    def _coin_uri(self, elt):
        owner = elt.owner
        if owner is self.package:
            base = self.package_uri
        else:
            base = (owner.uri or owner.url)
        return URIRef("{}#{}".format(base, quote_plus(elt.id)))

    def _coin_uri_from_id(self, id):
        if id.find(":") <= 0: # local element
            base = self.package_uri
        else:
            iid, id = id.split(":", 1)
            imp = self.package[iid]
            base = imp.uri or imp.url
        return URIRef("{}#{}".format(base, quote_plus(id)))
