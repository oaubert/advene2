"""
Cinelab Turtle parser implementation.
"""
from __future__ import division

from libadvene.model.cam.consts import CAM_NS_PREFIX, CAM_XML
from libadvene.model.cam.util.bookkeeping import inherit_bk_metadata
from libadvene.model.consts import DC_NS_PREFIX, PARSER_META_PREFIX
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.parsers.exceptions import ParserError
from libadvene.model.serializers.cinelab_rdf import CLD
import libadvene.model.serializers.cinelab_rdf as serializer
from libadvene.util.files import get_path

from rdflib import BNode, Graph, Literal, RDF, URIRef, XSD
from rdflib.exceptions import UniquenessError

import base64
from json import load, dumps
import re
from urllib import unquote_plus
from uuid import uuid1


class Parser(object):

    NAME = serializer.NAME
    EXTENSION = serializer.EXTENSION
    MIMETYPE = serializer.MIMETYPE
    SERIALIZER = serializer # may be None for some parsers

    _FORMAT = "xml"

    @classmethod
    def claims_for_parse(cls, file_):
        """Is this parser likely to parse that file-like object?

        `file_` is a readable file-like object. It is the responsability of the
        caller to close it.

        Return an int between 00 and 99, indicating the likelyhood of this
        parser to handle correctly the given URL. 70 is used as a standard
        value when the parser is pretty sure it can handle the URL.
        """
        r = 0
        info = getattr(file_, "info", lambda: {})()
        mimetype = info.get("content-type", "")
        if mimetype.startswith(cls.MIMETYPE):
            r = 80
        else:
            fpath = get_path(file_)
            if fpath.endswith(cls.EXTENSION):
                r += 50
        return r

    @classmethod
    def make_parser(cls, file_, package):
        """Return a parser that will parse `file_` into `package`.

        `file_` is a writable file-like object. It is the responsability of the
        caller to close it.

        The returned object must implement the interface for which
        :class:`_Parser` is the reference implementation.
        """
        return cls(file_, package)

    @classmethod
    def parse_into(cls, file_, package):
        """A shortcut for ``make_parser(file_, package).parse()``.

        See also `make_parser`.
        """
        cls(file_, package).parse()
        
    def parse(self):
        "Do the actual parsing."
        package = self.package
        graph = self.graph = Graph()
        graph.namespace_manager = serializer.CinelabNSManager(graph)
        graph.load(self.file, package.url, self._FORMAT)

        package.enter_no_event_section()
        sparql_ns = {"": CLD}
        try:
            uri = URIRef(package.url)
            if (uri, RDF.type, CLD.Package) not in graph:
                try:
                    uri = graph.value(None, RDF.type, CLD.Package, any=False)
                except UniquenessError:
                    uris = list(self.query("SELECT ?p { ?p :hasElement [] }"))
                    if len(uris) != 1:
                        uris = list(self.query("SELECT ?p { ?p :url ?u }",
                                                u = Literal(uri, XSD.anyURI)))
                        if len(uris) != 1:
                            raise ParserError("Can not determine package URI")
                    uri = uris[0][0]
                package.uri = str(uri)
            self.uri = uri

            # copy RDF namespace prefixes into package metadata,
            # except for empty namespace
            # (as most serializers define their own empty namespace)
            package.set_meta(PARSER_META_PREFIX+"namespaces",
                             "\n".join("%s %s" % i for i in graph.namespaces()
                                                   if i[0] <> ""))

            # create all elements
            self._parse_imports()
            self._parse_wcontent(CLD.Resource, package.create_resource)
            self._parse_simple(CLD.UserTag, package.create_user_tag)
            self._parse_simple(CLD.AnnotationType, package.create_annotation_type)
            self._parse_simple(CLD.RelationType, package.create_relation_type)
            self._parse_medias()
            self._parse_annotations()
            self._parse_relations()
            self._parse_wcontent(CLD.Query, package.create_query)
            self._parse_wcontent(CLD.View, package.create_view)
            self._parse_simple(CLD.UserList, package.create_user_list)
            self._parse_simple(CLD.Schema, package.create_schema)

            # then populates tagging and metadata
            # (doing it only now prevents forward references)
            self._parse_meta(uri, package)
            self._parse_all_tagging()
            self._parse_pass2()
        finally:
            package.exit_no_event_section()

    # end of public interface

    def __init__(self, file_, package):
        self.file = file_
        self.package = package
        self.graph = None
        self.uri = None
        self._genid_cache = {}

    # NB: most of the following parsing methods have two passes;
    # * in pass 1, objects are only created; this prevents the creation of
    # forward references;
    # * in pass 2, content, metadata and subelements are added, possibly
    # with reference to other objects created in pass 1

    def _parse_pass2(self):
        elements = self.query(""" SELECT ?elt ?etype {
            ?p :hasElement ?elt .
            ?elt a ?etype .
        }""", p=self.uri)
        for node, etype in elements:
            eltid = self.node2idpath(node)
            elt = self.package[eltid]
            elt.enter_no_event_section()
            try:
                if etype in {CLD.Annotation, CLD.Relation, CLD.Resource, CLD.Query, CLD.View}:
                    self._parse_content(node, elt)
                elif etype in {CLD.UserList, CLD.Schema}:
                    self._parse_items(node, elt, CLD.hasItems)
                self._parse_meta(node, elt)
            finally:
                elt.exit_no_event_section()

    def _parse_imports(self):
        factory = self.package._create_import_in_parser
        imports = self.query(""" SELECT ?imp ?uri ?url {
            ?p :hasElement ?imp .
            ?imp a :Import ;
              :hasImportedPackage ?uri .
            OPTIONAL { ?imp :url ?url }
        }""", p=self.uri)
        for imp, uri, url in imports:
            impid = self.node2idpath(imp)
            if url is None:
                url = uri
            factory(impid, str(url), str(uri))

        # then also create semi-explicit imports
        semiexplicit = self.query(""" SELECT ?uri {
            ?p :imports ?uri .
            FILTER(NOT EXISTS {
                ?p :hasElement ?imp .
                ?imp a :Import ;
                  :hasImportedPackage ?uri .
            })
        }""", p=self.uri)
        for uri, in semiexplicit:
            factory(genid(), str(uri), str(uri))


    def _parse_simple(self, typ, factory):
        elements = self.query(""" SELECT ?elt {
            ?p :hasElement ?elt .
            ?elt a ?typ.
        }""", p=self.uri, typ=typ)
        for elt, in elements:
            eid = self.node2idpath(elt)
            factory(eid)

    def _parse_medias(self):
        factory = self.package.create_media
        medias = self.query(""" SELECT ?media ?url ?foref {
            ?p :hasElement ?media .
            ?media a :Media ; :represents ?url .
            OPTIONAL { ?media :hasFrameOfReference ?url }
        }""", p=self.uri)
        for media, url, foref in medias:
            mid = self.node2idpath(media)
            if foref is None:
                foref = serializer.DEFAULT_FOREF
            factory(mid, str(url), str(foref))

    def _parse_wcontent(self, typ, factory):
        elts = self.query(""" SELECT ?elt ?ctype {
            ?p :hasElement ?elt .
            ?elt a ?typ .
            OPTIONAL { ?elt :hasContent [ :mimetype ?ctype ] }
        }""", p=self.uri, typ=typ)
        for elt, ctype in elts:
            eid = self.node2idpath(elt)
            if ctype is None:
                ctype = "text/plain"
            factory(eid, str(ctype))

    def _parse_annotations(self):
        factory = self.package.create_annotation
        annotations = self.query(""" SELECT ?a ?atype ?f ?m ?b ?e ?ctype {
            ?p :hasElement ?a .
            ?a a :Annotation ; :hasAType ?atype ; :hasFragment ?f .
            OPTIONAL { ?f :hasMediaElement ?m ; :begin ?b ; :end ?e .}
            OPTIONAL { ?a :hasContent [ :mimetype ?ctype ] }
        }""", p=self.uri)

        for annot, atype, frag, muri, begin, end, ctype in annotations:
            aid = self.node2idpath(annot)
            media = None
            meta = {}
            if ctype is None:
                ctype = "text/plain"
            if muri is not None:
                mid = self.node2idpath(muri)
            else:
                # decompose MediaFragment URI
                parts = frag.split("#", 1)
                if len(parts) != 2:
                    raise ParserError("Fragment does not look like a media fragment <{}>"
                                      .format(muri))
                murl, mfrag = parts

                for media in self.package.own.iter_medias():
                    if media.url == murl:
                        mid = media.id
                        break
                else: # did not break out of for loop
                    media = self.package.create_media(genid(), str(murl), serializer.DEFAULT_FOREF)
                    mid = media.id

                if media.unit not in ("ms", "s"):
                    raise ParserError("Unit {} of media {} is incompatible with media fragment URI"
                        .format(media.unit, media.id))

                for fragspec in mfrag.split("&"):
                    if fragspec[:2] == "t=":
                        parts = fragspec[2:].split(",")
                        if len(parts) > 2:
                            raise ParserError("Unable to parse t dimension '{}' (too many commas)"
                                              .format(fragspec))
                        if parts[0]:
                            begin = int(float(parts[0])*1000)
                        else:
                            begin = 0
                        if len(parts) == 2:
                            end = int(float(parts[1])*1000)
                        else:
                            end = begin
                        if media.unit == "s":
                            begin //= 1000
                            end //= 1000
                        origin = media.origin
                        if origin != 0:
                            begin += origin
                            end += origin
                    elif fragspec[:5] == "xywh=":
                        meta[CLD.fragDimXywh] = fragspec[5:]
                    elif fragspec[:6] == "track=":
                        meta[CLD.fragDimTrack] = fragspec[6:]
                    elif fragspec[:3] == "id=":
                        meta[CLD.fragDimId] = fragspec[3:]
                    else:
                        raise ParserError("Unrecongized media fragment dimension '{}'".format(fragspec))
            atype = self.node2idpath(atype)
            if atype.find(":") <= 0:
                atype = self.package[atype]
            a = factory(aid, media or mid, begin, end, ctype, type=atype)
            for key, value in meta.items():
                a.set_meta(key, value)

    def _parse_relations(self):
        factory = self.package.create_relation
        relations = self.query(""" SELECT ?r ?rtype ?ctype {
            ?p :hasElement ?r .
            ?r a :Relation ; :hasRType ?rtype .
            OPTIONAL { ?r :hasContent [ :mimetype ?ctype ] }
        }""", p=self.uri)
        for rel, rtype , ctype in relations:
            rid = self.node2idpath(rel)
            if ctype is None:
                ctype = "x-advene/none"
            rtype = self.node2idpath(rtype)
            if rtype.find(":") <= 0: # same package
                rtype = self.package[rtype]
            elt = factory(rid, ctype, type=rtype)
            self._parse_items(rel, elt, CLD.hasMembers)

        # also parse semi-explicit relations
        semiexplicit = self.query(""" SELECT ?rtype ?a1 ?a2 {
            ?a1 ?rtype ?a2 .
            ?a1 a :Annotation . ?a2 a :Annotation .
            FILTER(NOT EXISTS {
                ?p :hasElement [
                    a :Relation ;
                    :hasRType ?rtype ;
                    :hasMembers (?a1 ?a2)
                ]
            })
        }""", p=self.uri)
        for rtype, a1, a2 in semiexplicit:
            rtype = self.node2idpath(rtype)
            if rtype.find(":") <= 0: # same package
                rtype = self.package[rtype]
            a1 = self.node2idpath(a1)
            if a1.find(":") <= 0: # same package
                a1 = self.package[a1]
            a2 = self.node2idpath(a2)
            if a2.find(":") <= 0: # same package
                a2 = self.package[a2]
            elt = factory(genid(), "x-advene/none", type=rtype)
            elt.append(a1)
            elt.append(a2)



    def _parse_content(self, node, elt):
        results = list(self.query(""" SELECT ?c ?ctype ?cmodel ?cdata {
            ?e :hasContent ?c .
            ?c :mimetype ?ctype .
            OPTIONAL { ?c :hasModel ?cmodel }
            OPTIONAL { ?c :data ?cdata }
        }""", e=node))

        if len(results) == 0:
            return

        cnode, ctype, cmodel, cdata = results[0]

        elt.content_mimetype = str(ctype)
        if cmodel:
            cmodel = self.node2idpath(cmodel)
            if cmodel.find(":") <= 0: # same package
                cmodel = self.package[cmodel]
            elt.content_model = cmodel

        if isinstance(cnode, URIRef):
            elt.content_url = str(cnode)
        elif cdata:
            if cdata.datatype == CLD.base64:
                cdata = base64.urlsafe_b64decode(str(cdata))
            elif cdata.datatype is None or cdata.datatype == XSD.string:
                cdata = unicode(cdata)
            else:
                raise ParserError("Can not handle content data with datatype <{}> (in {})"
                    .format(cdata.datatype, elt.id))
            elt.content_data = cdata


    def _parse_items(self, node, elt, prop):
        value = self.graph.value
        listnode = value(node, prop)
        elt.enter_no_event_section()
        try:
            while listnode != RDF.nil:
                item = value(listnode, RDF.first)
                item = self.node2idpath(item)
                if item.find(":") <= 0: # same package
                    item = self.package[item]
                elt.append(item)
                listnode = value(listnode, RDF.rest)
        finally:
            elt.exit_no_event_section()


    def _parse_meta(self, node, elt):
        for _, prop, val in self.graph.triples((node, None, None)):
            if prop.startswith(CLD) or prop == RDF.type:
                continue
            if self.node2idpath(prop, False) is not None:
                continue
                # probably a relation type, so skip
            prop = str(prop)

            if isinstance(val, BNode):
                raise ParserError("Can not set metadata with bnode {} <{}>"
                    .format(elt, prop))
            elif isinstance(val, Literal):
                elt.set_meta(prop, str(val))
            else: # URIRef
                val_id = self.node2idpath(val, False)
                if val_id is None:
                    elt.set_meta(prop, str(val))
                else:
                    if val_id.find(":") > 0: # imported
                        elt.set_meta(prop, val_id, True)
                    else:
                        val = self.package[val_id]
                        elt.set_meta(prop, val)
        if elt is not self.package:
            inherit_bk_metadata(elt, self.package)

    def _parse_all_tagging(self):
        factory = self.package.associate_user_tag
        taggings = self.query(""" SELECT ?tagged ?tag {
                ?tagged :taggedWith ?tag .
            }
            """,
            p=self.uri
        )
        for tagged, tag in taggings:
            tag = self.node2idpath(tag, False)
            if tag is not None:
                if tag.find(":") <= 0: # same package
                    tag = self.package[tag]
                tagged = self.node2idpath(tagged, False)
                if tagged is not None:
                    if tagged.find(":") <= 0: # same package
                        elt = self.package[tagged]
                        elt.enter_no_event_section()
                        try:
                            factory(elt, tag)
                        finally:
                            elt.exit_no_event_section()
                    else:
                        factory(tagged, tag)


    def query(self, query, _initNs = {"": CLD}, **initBindings):
        """ Run a query on the graph being parsed.
        :param query: a SPARQL query
        :param initBindings: initial variable bindings are passed a keywords
        :return: the SPARQL results
        """
        return self.graph.query(query, initNs=_initNs, initBindings=initBindings)

    def node2idpath(self, node, create=True):
        """ Convert a URI into an Advene idpath.

        :param node: The URI of an element (owned or imported) of self.package
        :param create: whether required elements (element itself or import) must be created
        :return: the id of that element

        Assumes that all imports are already parsed.
        """
        if isinstance(node, BNode):
            ret = self._genid_cache.get(node)
            if ret is None and create:
                ret = self._genid_cache[node] = genid()
            return ret
        else:
            assert isinstance(node, URIRef)
            uriparts = node.split("#")
            if len(uriparts) == 2:
                puri, eid = uriparts
                eid = unquote_plus(eid)
                if puri == str(self.uri):
                    return eid
                else:
                    for imp in self.package.own.iter_imports():
                        if imp.uri == puri or imp.url == puri:
                            return "{}:{}".format(imp.id, eid)
            if create:
                iid = genid()
                self.package._create_import_in_parser(iid, str(puri), str(puri))
                return "{}:{}".format(iid, eid)
            return None
#

def genid():
    return "_" + uuid1().get_hex()

_SUFFIX = re.compile("^[a-zA-Z_.-]+$")
_CURIE = re.compile("^[a-zA-Z_.-]+:[a-zA-Z_.-]+$")
