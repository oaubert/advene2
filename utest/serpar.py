"""Unit test for serialization and parsing."""

from os import close, fdopen, unlink
from tempfile import mkstemp
from unittest import TestCase, main
from urllib import pathname2url
import warnings

from rdflib import BNode, Graph, Literal, RDF, URIRef

import libadvene.model.backends.sqlite as backend_sqlite
from libadvene.model.cam.exceptions import UnsafeUseWarning
from libadvene.model.cam.package import Package as CamPackage
from libadvene.model.consts import PACKAGED_ROOT, DC_NS_PREFIX, \
                                RDFS_NS_PREFIX, PARSER_META_PREFIX
from libadvene.model.core.diff import diff_packages
from libadvene.model.core.element import IMPORT, RESOURCE
from libadvene.model.core.package import Package
from libadvene.model.parsers.exceptions import ParserError
import libadvene.model.serializers.advene_xml as xml
import libadvene.model.serializers.advene_zip as zip
import libadvene.model.serializers.cinelab_xml as cxml
import libadvene.model.serializers.cinelab_zip as czip
import libadvene.model.serializers.cinelab_json as cjson
import libadvene.model.serializers.cinelab_rdf as crdf
import libadvene.model.serializers.cinelab_ttl as cttl

from libadvene.model.serializers.cinelab_rdf import CLD

from core_diff import fill_package_step_by_step, fix_diff

warnings.filterwarnings("ignore", category=UnsafeUseWarning,
                        module="libadvene.model.core.diff")
#warnings.filterwarnings("ignore", category=UnsafeUseWarning,
#                        module="core_diff")
warnings.filterwarnings("ignore", category=UnsafeUseWarning, module=__name__)



backend_sqlite._set_module_debug(True) # enable assert statements

class TestAdveneXml(TestCase):
    """
    This TestCase is not specific to AdveneXml. It can be reused for other
    serializer-parser pairs by simply overriding its class attributes: `serpar`,
    `pkgcls`.
    """
    pkgcls = Package
    serpar = xml

    def setUp(self):
        fd1, self.filename1 = mkstemp(suffix=self.serpar.EXTENSION,
                                      prefix="advene2_utest_serpar_")
        fd2 , self.filename2 = mkstemp(suffix=self.serpar.EXTENSION,
                                       prefix="advene2_utest_serpar_")
        fdopen(fd1).close()
        fdopen(fd2).close()
        self.url = "file:" + pathname2url(self.filename2)
        self.p1 = self.pkgcls("file:" + pathname2url(self.filename1),
                              create=True)
        self.p2 = None

    def tearDown(self):
        self.p1.close()
        self.p1 = None
        if self.p2 and self.p2._backend:
            self.p2.close()
            self.p2 = None
        unlink(self.filename1)
        try:
            unlink(self.filename2)
        except OSError:
            pass

    def fix_diff(self, diff):
        return fix_diff(diff)

    def fill_package_step_by_step(self):
        #return fill_package_step_by_step(self.p1, empty=True):
        for i in fill_package_step_by_step(self.p1, empty=True):
            yield i

    def test_each_step(self):
        p1 = self.p1
        for i in self.fill_package_step_by_step():
            f = open(self.filename2, "w")
            self.serpar.serialize_to(p1, f)
            f.close()
            try:
                p2 = self.p2 = self.pkgcls(self.url)
            except ParserError, e:
                self.fail("ParserError: %s (%s)" % (e.args[0], self.filename2))

            diff = self.fix_diff(diff_packages(p1, p2))
            #if (diff != []): import pdb; pdb.set_trace()
            self.assertEqual([], diff, (i, diff, self.filename2))
            p2.close()
            

    def test_forward_reference_in_list_items(self):
        p1 = self.p1
        r1 = p1.create_resource("r1", "text/plain")
        r2 = p1.create_resource("r2", "text/plain")
        L1 = p1.create_list("L1")
        L2 = p1.create_list("L2")
        L1[:] = [r1, L2, r2, L2,]
        L2[:] = [r1, L1, r2, L1,]
        # one of the two list will necessarily have forward-references in the
        # serialization

        f = open(self.filename2, "w")
        self.serpar.serialize_to(p1, f)
        f.close()
        try:
            p2 = self.p2 = self.pkgcls(self.url)
        except ParserError, e:
            self.fail("ParserError: %s (%s)" % (e.args[0], self.filename2))
        diff = self.fix_diff(diff_packages(p1, p2))
        self.assertEqual([], diff, (diff, self.filename2))

    def test_forward_reference_in_tagged_imports(self):
        p1 = self.p1
        i1 = p1.create_import("i1", self.pkgcls("urn:123", 1))
        i2 = p1.create_import("i2", self.pkgcls("urn:456", 1))
        p1.associate_tag(i1, "i2:t")
        p1.associate_tag(i2, "i1:t")
        # one of the two imports will necessarily have forward-references in the
        # serialization

        f = open(self.filename2, "w")
        self.serpar.serialize_to(p1, f)
        f.close()
        try:
            p2 = self.p2 = self.pkgcls(self.url)
        except ParserError, e:
            self.fail("ParserError: %s (%s)" % (e.args[0], self.filename2))
        diff = self.fix_diff(diff_packages(p1, p2))
        self.assertEqual([], diff, (diff, self.filename2))

    def test_base64(self):
        p1 = self.p1
        r = p1.create_resource("r", "application/binary")
        r.content_data = "\x01\x02\x03"
        r.content_url = "" # force content to be in the XML

        f = open(self.filename2, "w")
        self.serpar.serialize_to(p1, f)
        f.close()
        try:
            p2 = self.p2 = self.pkgcls(self.url)
        except ParserError, e:
            self.fail("ParserError: %s (%s)" % (e.args[0], self.filename2))
        diff = self.fix_diff(diff_packages(p1, p2))
        self.assertEqual([('<setattr>', 'r', 'content_url', '')],
                         diff, (diff, self.filename2))


class TestAdveneZip(TestAdveneXml):
    serpar = zip


class TestCinelabXml(TestAdveneXml):
    pkgcls = CamPackage
    serpar = cxml

    def setUp(self):
        super(TestCinelabXml, self).setUp()
        self.p3 = None

    def tearDown(self):
        super(TestCinelabXml, self).tearDown()
        if self.p3:
            self.p3.close()
            self.p3 = None

    def fill_package_step_by_step(self):
        dc_creator = DC_NS_PREFIX + "creator"
        dc_description = DC_NS_PREFIX + "description"
        rdfs_seeAlso = RDFS_NS_PREFIX + "seeAlso"
        p = self.p1
        yield "empty"
        p3 = self.p3 = self.pkgcls("urn:xyz", create=True)
        m3  = p3.create_media("m3", "http://example.com/m3.ogm")
        at3 = p3.create_annotation_type("at3")
        a3  = p3.create_annotation("a3", m3, 123, 456, "text/plain", type=at3)
        rt3 = p3.create_relation_type("rt3")
        r3  = p3.create_relation("r3", "text/plain", members=[a3,], type=rt3)
        s3  = p3.create_schema("s3", items=[at3, rt3,])
        L3  = p3.create_user_list("L3", items=[a3, m3, r3,])
        t3  = p3.create_user_tag("t3")
        v3  = p3.create_view("v3", "text/html+tag")
        q3  = p3.create_query("q3", "x-advene/rules")
        R3  = p3.create_resource("R3", "text/css")

        p.uri = "http://example.com/my-package"; yield 1
        i = p.create_import("i", p3); yield 2
        at = p.create_annotation_type("at"); yield 2.25
        rt = p.create_relation_type("rt"); yield 2.75
        m = p.create_media("m", "http://example.com/m.ogm"); yield 3
        m.set_meta(rdfs_seeAlso, m3); yield 4
        Rb = p.create_resource("Rb", "x-advene/regexp"); yield 5
        Rb.content_data = "g.*g"; yield 6
        a = p.create_annotation("a", m, 123, 456,
                                "text/plain", Rb, type=at); yield 7
        a.content_data = "goog moaning"; yield 8
        a2 = p.create_annotation("a2", m3, 123, 456,
                                "text/plain", Rb, type=at3); yield 8.5
        r = p.create_relation("r", members=[a, a3], type=rt); yield 9
        r2 = p.create_relation("r2", "text/plain", type=rt3); yield 10
        s = p.create_schema("s", items=[at, rt, at3, rt3,]); yield 10.5
        L = p.create_user_list("L", items=[a, m, r, m3]); yield 11
        t = p.create_user_tag("t"); yield 12
        v = p.create_view("v", "text/html+tag"); yield 13
        v.content_url = "http://example.com/a-tal-view.html"; yield 14
        q = p.create_query("q", "text/x-python"); yield 15
        q.content_url = "file://%s" % pathname2url(__file__); yield 16
        Ra = p.create_resource("Ra", "text/css"); yield 17
        sorted_p_own = list(p.own); sorted_p_own.sort(key=lambda x: x._id)
        for e in sorted_p_own:
            e.set_meta(dc_creator, "pchampin"); yield 18, e.id
            p.associate_user_tag(e, t); yield 19, e.id
            p.associate_user_tag(e, t3); yield 20, e.id
        sorted_p3_own = list(p3.own); sorted_p3_own.sort(key=lambda x: x._id)
        for e in sorted_p3_own:
            p.associate_user_tag(e, t); yield 21, e.id
            p.associate_user_tag(e, t3); yield 22, e.id
        p.set_meta(dc_creator, "pchampin"); yield 23, e.id
        p.set_meta(dc_description, "a package used for testing diff"); yield 24
        p.set_meta(PARSER_META_PREFIX+"namespaces",
                   "dc http://purl.org/dc/elements/1.1/") ; yield 25
        p.create_resource(":tricky:id", "text/plain")
        yield "done"

class TestCinelabZip(TestCinelabXml, TestAdveneZip):
    serpar = czip

class TestCinelabJson(TestCinelabXml):
    serpar = cjson

    def fill_package_step_by_step(self):
        for i in TestCinelabXml.fill_package_step_by_step(self):
            if i != "done":
                yield i
        p = self.p1
        p.title = "title should be serialized without any prefix"
        p.description = "description as well"
        yield 100
        jv = p.create_resource("jv", "application/json")
        jv.content_data = '{"a": "b"}' # valid json
        yield 101
        ji = p.create_resource("ji", "application/json")
        ji.content_data = '{"a": "b"' # invalid json
        yield 102
        jd = p.create_resource("jd", "application/toto+json")
        jd.content_data = '{"a": "b"}' # valid json in a derived mimetype
        yield 103

        yield "done"

    def test_parse_json_directly(self):
        from libadvene.model.parsers.cinelab_json import Parser as JsonParser
        p = CamPackage("http://localhost:1234/test.json", create=True)
        JsonParser.parse_into({}, p)

class TestUnorderedCinelabXml(TestCase):
    """
    I check that cinelab XML files can have the subelements of <package> in
    any order.
    """
    def setUp(self):
        from libadvene.model.parsers.cinelab_xml import Parser
        fd1, self.filename1 = mkstemp(suffix=".cxp",
                                      prefix="advene2_utest_serpar_")
        f = fdopen(fd1, "w")
        f.write(UNORDERED_XML)
        f.close()
        uri = "file:" + pathname2url(self.filename1)
        self.p1 = CamPackage(uri, parser=Parser)

    def tearDown(self):
        unlink(self.filename1)

    def test_unordered(self):
        p1 = self.p1
        assert len(p1.own.imports) == 1
        assert len(p1.own.user_tags) == 1
        assert len(p1.own.annotation_types) == 1
        assert len(p1.own.relation_types) == 1
        assert len(p1.own.medias) == 1
        assert len(p1.own.resources) == 1
        assert len(p1.own.annotations) == 1
        assert len(p1.own.relations) == 1
        assert len(p1.own.views) == 1
        assert len(p1.own.queries) == 1
        assert len(p1.own.schemas) == 1
        assert len(p1.own.user_lists) == 1


class TestClaimChain(TestCase):
    """
    I check that pr
    """
    def setUp(self):
        fd1, self.filename1 = mkstemp(suffix=".czp",
                                      prefix="advene2_utest_serpar_")
        fdopen(fd1).close()
        self.url1 = "file:" + pathname2url(self.filename1)
        p1 = CamPackage(self.url1, create=True)
        p1.save()
        p1.close()

    def tearDown(self):
        unlink(self.filename1)

    def testCzp(self):
        p = CamPackage(self.filename1)
        p.close()

UNORDERED_XML = """
<package xmlns="http://advene.org/ns/cinelab/"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
>
  <resources>
    <resource id="R">
      <content>hello world</content>
      <meta>%(meta)s</meta>
    </resource>
  </resources>
  <queries>
    <query id="q">
      <content>hello world</content>
      <meta>%(meta)s</meta>
    </query>
  </queries>
  <lists>
    <list id="l1">
      <meta>%(meta)s</meta>
    </list>
  </lists>
  <schemas>
    <schema id="s1">
      <meta>%(meta)s</meta>
    </schema>
  </schemas>
  <views>
    <view id=":constraint:at1">
      <content mimetype="text/plain">hello world</content>
      <meta>%(meta)s</meta>
    </view>
  </views>
  <relations>
    <relation id="r">
      <meta>%(meta)s
        <type id-ref="rt1" />
      </meta>
    </relation>
  </relations>
  <annotations>
    <annotation begin="0" end="1000" id="a" media="m1">
      <content mimetype="text/plain">hello world</content>
      <meta>%(meta)s
        <type id-ref="at1" />
      </meta>
    </annotation>
  </annotations>
  <medias>
    <media id="m1" url="http://example.com/movie" /> 
      <meta>%(meta)s
        <type id-ref="at1" />
      </meta>
  </medias>
  <relation-types>
    <relation-type id="rt1">
      <meta>%(meta)s</meta>
    </relation-type>
  </relation-types>
  <annotation-types>
    <annotation-type id="at1">
      <meta>%(meta)s</meta>
    </annotation-type>
  </annotation-types>
  <tags>
    <tag id="t">
      <meta>%(meta)s</meta>
    </tag>
  </tags>
  <imports>
    <import id="d" url="http://liris.cnrs.fr/advene/cam/dummy">
      <meta>%(meta)s</meta>
    </import>
  </imports>
  <meta>%(meta)s</meta>
</package>
""" % {
  "meta": """
        <dc:contributor>pa</dc:contributor>
        <dc:created>2010-07-01T11:07:48.380560</dc:created>
        <dc:creator>pa</dc:creator>
        <dc:modified>2010-07-01T11:07:48.380560</dc:modified>
  """
}
        
class TestRdf(TestCinelabXml):
    serpar = crdf

    def fix_diff(self, diff):
        return [
            d for d in super(TestRdf, self).fix_diff(diff)
            if d[:4] != ('set_meta', '', '', PARSER_META_PREFIX + "namespaces")
            # namespace declarations are not exactly preserved through RDF
            and not (d[0] == '<setattr>' and d[2:] == ('uri', u''))
            # RDF parser always sets a URI (using URL if required)
        ]

    def fill_package_step_by_step(self):
        for i in TestCinelabXml.fill_package_step_by_step(self):
            if i != "done":
                yield i
        p = self.p1
        a = p["a"]
        a.set_meta(CLD.fragDimXywh, "percent:25,25,50,50")
        yield 100
        a.set_meta(CLD.fragDimTrack, "fre-dubbed")
        yield 101
        a.set_meta(CLD.fragDimId, "frag101")
        yield 102

        yield "done"

class TestTurtle(TestRdf):
    serpar = cttl

class TestRdfSpecifics(TestCase):

    def setUp(self):
        fd, self.filename = mkstemp(".ttl", "advebe2_utest_serpar_")
        self.f = fdopen(fd, "w")
        self.f.write("@prefix : <{}> .\n".format(CLD))
        self.p = None

    def tearDown(self):
        if self.p:
            self.p.close()
        if self.f:
            self.f.close()
        unlink(self.filename)

    def test_bnode_element(self):
        self.f.write("""
        <> a :Package ;
            :hasElement [
                a :Resource ;
                :hasContent [
                    :mimetype "text/plain" ;
                    :data "hello world" ;
                ];
            ];
        .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        elts = list(p.own)
        assert len(elts) == 1, len(elts)
        res = elts[0]
        assert res.ADVENE_TYPE == RESOURCE, res.ADVENE_TYPE
        assert res.content_data == "hello world", res.content_data

    def test_semiexplicit_import(self):
        self.f.write("""
        <> a :Package ;
            :imports <http://example.org/pkg> ;
        .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        elts = list(p.own)
        assert len(elts) == 1, len(elts)
        imp = elts[0]
        assert imp.ADVENE_TYPE == IMPORT, imp.ADVENE_TYPE
        assert imp.uri == "http://example.org/pkg", imp.uri

    def test_semiexplicit_relation(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#m>, <#at>, <#rt>, <#a1>, <#a2> .
        <#at> a :AnnotationType .
        <#rt> a :RelationType .
        <#m> a :Media ; :represents <http://example.org/movie.mp4> .
        <#a1> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        <#a2> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#t=9,10> ;
            :hasContent [ :data "how are you?" ] ;
        .
        <#a1> <#rt> <#a2> .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        elts = list(p.own.relations)
        assert len(elts) == 1, len(elts)
        rel = elts[0]
        assert rel.type == p["rt"], rel.type
        assert list(rel) == [p["a1"], p["a2"]], list(rel)

    def test_implicit_import(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#r> .
        <#r> a :Resource ;
            :hasContent [
                :mimetype "text/plain" ;
                :data "hello world" ;
                :hasModel <http://example.org/pkg#schema> ;
            ];
        .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        elts = list(p.own.imports)
        assert len(elts) == 1, len(elts)
        imp = elts[0]
        assert imp.uri == "http://example.org/pkg", imp.uri

    def test_implicit_media(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#at>, <#a> .
        <#at> a :AnnotationType .
        <#a> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        # implicit media has been created
        elts = list(p.own.medias)
        assert len(elts) == 1, len(elts)
        med = elts[0]
        assert med.url == "http://example.org/movie.mp4", med.url
        # annotation associated with new media
        assert p["a"].media is med, p["a"].media


    def test_fragment_explicit_media(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#m>, <#at>, <#a> .
        <#at> a :AnnotationType .
        <#m> a :Media ; :represents <http://example.org/movie.mp4> .
        <#a> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        """)
        self.f.close()

        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        # no new media created here
        elts = list(p.own.medias)
        assert len(elts) == 1, len(elts)
        # annotation has right media
        assert p["a"].media is p["m"], p["a"].media


    def test_xywh_fragment(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#at>, <#a> .
        <#at> a :AnnotationType .
        <#a> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#xywh=10,20,30,40&t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        """)
        self.f.close()
        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        a = p["a"]
        assert a.get_meta(CLD.fragDimXywh, None) == "10,20,30,40"
        # check that t= was still correctly retrieved
        assert a.begin, a.end == (1234, 5678)

    def test_track_fragment(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#at>, <#a> .
        <#at> a :AnnotationType .
        <#a> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#track=fre-dubbed&t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        """)
        self.f.close()
        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        a = p["a"]
        assert a.get_meta(CLD.fragDimTrack, None) == "fre-dubbed"
        # check that t= was still correctly retrieved
        assert a.begin, a.end == (1234, 5678)

    def test_id_fragment(self):
        self.f.write("""
        <> a :Package ;
            :hasElement <#at>, <#a> .
        <#at> a :AnnotationType .
        <#a> a :Annotation ;
            :hasAType <#at> ;
            :hasFragment <http://example.org/movie.mp4#id=frag101&t=1.234,5.678> ;
            :hasContent [ :data "hello world" ] ;
        .
        """)
        self.f.close()
        p = self.p = CamPackage("file://" + pathname2url(self.filename))
        a = p["a"]
        assert a.get_meta(CLD.fragDimId, None) == "frag101"
        # check that t= was still correctly retrieved
        assert a.begin, a.end == (1234, 5678)


if __name__ == "__main__":
    main()
