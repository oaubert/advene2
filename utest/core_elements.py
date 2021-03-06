import gc
from os import path, rmdir, unlink
from os.path import abspath, exists
from tempfile import mkdtemp as mkdtemp_orig
from urllib import pathname2url, url2pathname
from unittest import TestCase, main

from libadvene.model.backends.sqlite import _set_module_debug
from libadvene.model.consts import DC_NS_PREFIX
from libadvene.model.core.content import PACKAGED_ROOT
from libadvene.model.core.media import FOREF_PREFIX, DEFAULT_FOREF
from libadvene.model.core.element import RELATION
from libadvene.model.core.package import Package, UnreachableImportError, \
    NoSuchElementError
from libadvene.model.exceptions import ModelError
from libadvene.util.session import session

_set_module_debug(True) # enable all asserts in backend_sqlite

dc_creator = "http://purl.org/dc/elements/1.1/creator"
dc_description = "http://purl.org/dc/elements/1.1/description"
rdfs_seeAlso = "http://www.w3.org/1999/02/22-rdf-syntax-ns#seeAlso"

def mkdtemp(suffix="", prefix="advene2_utest_core_element_", dir=None):
    return mkdtemp_orig(suffix, prefix, dir)

class TestElements(TestCase):
    def setUp(self):
        self.p = Package("file:/tmp/p", create=True)
        self.p.create_media("m1", "http://example.com/m1.avi")

        self.q = Package("file:/tmp/q", create=True)

    def tearDown(self):
        self.q.close()
        self.p.close()

    # utility methodes for mixins and common behaviours

    def _test_volatile(self, eid, package=None):
        # PRECONDITION: the element identified by eid must have no instance
        # referenced outside this function
        #
        # NB: we can not test that objects are volatile by comparing the python
        # id at two points of their lifetime, because python recycles ids.
        # Hence we use out knowledge of the implementation: we check that the
        # element disappeared from p._elements.
        # This is not good unit-test practice, but I have no better solution
        # for the moment.
        p = package or self.p
        gc.collect()
        # by default, elements are volatile
        self.assertEqual(p._elements.get(eid), None)

        p.get(eid).foo = "foo"
        p.get(eid).bar = "bar"
        del p.get(eid).foo
        gc.collect()
        # custom attributes makes them heavier
        self.assertNotEqual(p._elements.get(eid), None)

        del p.get(eid).bar
        gc.collect()
        # removing all custom attributes makes them volatile again
        self.assertEqual(p._elements.get(eid), None)

    def _test_with_content(self, e):
        # content related attributes (model is tested below)
        self.assertEqual("text/plain", e.content_mimetype)
        self.assertEqual("text/plain", e.content.mimetype)
        self.assertEqual("", e.content_url)
        self.assertEqual("", e.content.url)
        self.assertEqual("", e.content_data)
        self.assertEqual("", e.content.data)
        e.content_mimetype = "text/html"
        self.assertEqual("text/html", e.content_mimetype)
        self.assertEqual("text/html", e.content.mimetype)
        self.assert_(e.content_is_textual)
        self.assert_(e.content.is_textual)
        e.content.mimetype = "application/binary"
        self.assert_(not e.content_is_textual)
        self.assert_(not e.content.is_textual)
        # the package must have automatically switched to packaged
        self.assert_(e.content_url)
        self.assert_(e.content_url.startswith("packaged:"))
        e.content_data # check that data is accessible
        e.content.mimetype = "image/svg"
        self.assert_(e.content_is_textual)
        self.assert_(e.content.is_textual)
        # the package must have automaticcaly switched back to in-memory
        self.assert_(not e.content_url)
        e.content.mimetype = "text/plain"
        self.assertEqual("text/plain", e.content_mimetype)
        self.assertEqual("text/plain", e.content.mimetype)
        e.content_data = "listen carefuly"
        self.assertEqual("listen carefuly", e.content_data)
        self.assertEqual("listen carefuly", e.content.data)
        e.content.data = "I shall say this only once"
        self.assertEqual("I shall say this only once", e.content_data)
        self.assertEqual("I shall say this only once", e.content.data)

        # external content (url)
        filename = __file__
        if filename[-1] == "c": filename = filename[:-1] # use .py, not .pyc
        url = "file:" + pathname2url(abspath(filename))
        e.content_url = url
        f = open(filename); lines = f.read(); f.close()
        self.assertEqual(url, e.content_url)
        self.assertEqual(url, e.content.url)
        self.assertEqual(lines, e.content_data)
        self.assertEqual(lines, e.content.data)

        f = e.content_as_file
        self.assertEqual(lines, f.read())
        f.close()

        f = e.get_content_as_synced_file()
        self.assertEqual(lines, f.read())
        f.close()

        # a second time, to check that the closing of the synced file
        # allows to open it again
        f = e.content.get_as_synced_file()
        self.assertEqual(lines, f.read())
        f.close()

        # backend-stored content
        self.assertRaises(AttributeError, setattr, e, "content_data", "x")
        e.content_url = ""
        e.content_data = "good moaning"
        self.assertEqual("", e.content_url)
        self.assertEqual("", e.content.url)

        f = e.get_content_as_synced_file()
        self.assertEqual("good moaning", f.read())
        f.seek(0)
        f.truncate()
        f.write("hello chaps")
        f.seek(0)
        self.assertEqual("hello chaps", f.read())
        pos = f.tell()
        self.assertEqual("hello chaps", e.content_data)
        self.assertEqual("hello chaps", e.content.data)
        self.assertEqual(pos, f.tell())
        self.assertRaises(IOError, setattr, e, "content_data", "foo")
        self.assertRaises(IOError, setattr, e.content, "data", "foo")
        self.assertRaises(IOError, e.get_content_as_synced_file)
        self.assertRaises(IOError, e.content.get_as_synced_file)
        f.close()
        # test accents in backend-stored content
        e.content_data = u"\xe9"
        self.assertEqual(u"\xe9", e.content_data)
        self.assertEqual(u"\xe9", e.content.data)
        e.content_data = "hello chaps" # back to old value, used below

        # packaged content
        e.content_mimetype = "application/binary" # ensure it will be packaged
        base = e._owner.get_meta(PACKAGED_ROOT, None)
        self.assert_(base) # packaged root automatically created
        self.assertEqual(e.content_url, "packaged:/data/%s" % e.id)
        filename = path.join(base, url2pathname("data/%s" % e.id))
        self.assert_(exists(filename), filename) # file automatically created
        # data has not been changed
        self.assertEqual("hello chaps", e.content_data)
        self.assertEqual("hello chaps", e.content.data)
        # data in file are in sync
        f = open(filename, "w")
        f.write("packaged data")
        f.close()
        self.assertEqual("packaged data", e.content_data)
        self.assertEqual("packaged data", e.content.data)
        long_data = "still packaged data"
        e.content_data = "still packaged data"
        f = open(filename, "r")
        self.assertEqual("still packaged data", f.read())
        f.close()
        # get packaged content as_synced_file
        f = e.get_content_as_synced_file()
        self.assertEqual("still packaged data", f.read())
        f.seek(0)
        f.truncate()
        f.write("hello chaps")
        f.seek(0)
        self.assertEqual("hello chaps", f.read())
        pos = f.tell()
        self.assertEqual("hello chaps", e.content_data)
        self.assertEqual("hello chaps", e.content.data)
        self.assertEqual(pos, f.tell())
        self.assertRaises(IOError, setattr, e, "content_data", "foo")
        self.assertRaises(IOError, setattr, e.content, "data", "foo")
        self.assertRaises(IOError, e.get_content_as_synced_file)
        self.assertRaises(IOError, e.content.get_as_synced_file)
        f.close()
        # test binary data in packaged content
        e.content_data = "\x01\x02\x03"
        self.assertEqual("\x01\x02\x03", e.content_data)
        self.assertEqual("\x01\x02\x03", e.content.data)
        # test unicode in packaged content
        e.content_mimetype = "text/plain"
        e.content_data = u"\xe9"
        e.content_url = "packaged:/data/%s" % e.id # force again packaged:
        self.assertEqual(u"\xe9", e.content_data)
        self.assertEqual(u"\xe9", e.content.data)
        # back to previous values, used in the following
        e.content_mimetype = "application/binary"
        e.content_data = "hello chaps" # back to old value, used below

        # back to backend-stored
        e.content_url = ""
        # data is still there
        self.assertEqual("hello chaps", e.content_data)
        self.assertEqual("hello chaps", e.content.data)
        # file has been cleaned
        self.assert_(not exists(filename), filename)

        # model
        self.assertEqual(None, e.content_model)
        self.assertEqual(None, e.content.model)
        self.assertEqual("", e.content_model_id)
        self.assertEqual("", e.content.model_id)
        s = e._owner.create_resource("mymodel", "test/plain")
        e.content_model = s
        self.assertEqual(s, e.content_model)
        self.assertEqual(s, e.content.model)
        self.assertEqual("mymodel", e.content_model_id)
        self.assertEqual("mymodel", e.content.model_id)
        e.content_model = None
        self.assertEqual(None, e.content_model)
        self.assertEqual(None, e.content.model)
        self.assertEqual("", e.content_model_id)
        self.assertEqual("", e.content.model_id)

        # empty content
        if e.ADVENE_TYPE == RELATION:
            e.content_mimetype = "x-advene/none"
            self.assertEqual(None, e.content_model)
            self.assertEqual("", e.content_model_id)
            self.assertEqual("", e.content_url)
            self.assertEqual("", e.content_data)
            self.assertRaises(ModelError, setattr, e, "content_model", s)
            self.assertRaises(ModelError, setattr, e, "content_url", url)
            self.assertRaises(ModelError, setattr, e, "content_data", "")
            e.content_mimetype = "text/plain"
        else:
            self.assertRaises(ModelError, setattr, e, "content_mimetype",
                              "x-advene/none")
        s.delete()
        e.content_url = ""
        e._owner.del_meta(PACKAGED_ROOT)

        # parsed content
        s = "a=b\n\n c  =  d "
        d = {"a":"b", "c":"d"}
        e.content_data = "a=b\n\n c  =  d "
        e.content_mimetype = "text/plain"
        self.assertEqual(e.content_parsed, s)
        self.assertEqual(e.content.parsed, s)
        e.content_mimetype = "application/x-advene-builtin-view"
        self.assertEqual(e.content_parsed, d)
        self.assertEqual(e.content.parsed, d)

        d["c"] = "D"
        d["e"] = "f"
        del d["a"]
        e.content_parsed = d
        self.assertEqual(e.content_parsed, d)


    def _test_with_meta(self, e):

        def test_is_list():
            def has_id(a): return hasattr(a, "ADVENE_TYPE")
            def id(a): return has_id(a) and a.id or a
            eq = self.assertEqual
            refid = [ (k, id(v)) for k, v in ref ]
            refiid = [ (k, has_id(v)) for k, v in ref ]
            def mapisid1(L): return [ i.is_id for i in L ]
            def mapisid2(L): return [ (k, v.is_id) for k, v in L ]

            eq(ref, list(e.iter_meta()))
            eq(ref, e.meta.items())
            eq(ref, list(e.meta.iteritems()))
            eq([k for k,v in ref], e.meta.keys())
            eq([k for k,v in ref], list(e.meta))
            eq([k for k,v in ref], list(e.meta.iterkeys()))
            eq([v for k,v in ref], e.meta.values())
            eq([v for k,v in ref], list(e.meta.itervalues()))

            eq(refid, list(e.iter_meta_ids()))
            eq(refid, e.meta.items_ids())
            eq(refid, list(e.meta.iteritems_ids()))
            eq([v for k,v in refid], e.meta.values_ids())
            eq([v for k,v in refid], list(e.meta.itervalues_ids()))

            eq(refiid, mapisid2(e.iter_meta_ids()))
            eq(refiid, mapisid2(e.meta.items_ids()))
            eq(refiid, mapisid2(e.meta.iteritems_ids()))
            eq([v for k,v in refiid], mapisid1(e.meta.values_ids()))
            eq([v for k,v in refiid], mapisid1(e.meta.itervalues_ids()))

        def test_has_item(k, v):
            self.assert_(e.meta.has_key(k))
            self.assertEqual(v, e.get_meta(k))
            self.assertEqual(v, e.get_meta(k))
            self.assertEqual(v, e.get_meta(k, None))
            self.assertEqual(v, e.meta[k])
            self.assertEqual(v, e.meta.get(k))
            self.assertEqual(v, e.meta.get(k, None))
            self.assertEqual(v, e.meta.pop(k)); e.meta[k] = v
            self.assertEqual(v, e.meta.pop(k, None)); e.meta[k] = v
            if hasattr(v, "ADVENE_TYPE"):
                id = v.make_id_in(self.p)
                self.assertEqual(id, e.get_meta_id(k))
                self.assertEqual(id, e.get_meta_id(k, "!"))
                self.assertEqual(id, e.meta.get_id(k))
                self.assertEqual(id, e.meta.get_id(k, "!"))
                self.assertEqual(id, e.meta.pop_id(k)); e.meta[k] = v
                self.assertEqual(id, e.meta.pop_id(k, "!")); e.meta[k]= v
                self.assert_(e.get_meta_id(k).is_id)
                self.assert_(e.meta.get_id(k).is_id)
                self.assert_(e.meta.pop_id(k).is_id); e.meta[k] = v
            else:
                self.assertEqual(v, e.get_meta_id(k))
                self.assertEqual(v, e.get_meta_id(k, "!"))
                self.assertEqual(v, e.meta.get_id(k))
                self.assertEqual(v, e.meta.get_id(k, "!"))
                self.assertEqual(v, e.meta.pop_id(k)); e.meta[k] = v
                self.assertEqual(v, e.meta.pop_id(k, "!")); e.meta[k] = v
                self.assert_(not e.get_meta_id(k).is_id)
                self.assert_(not e.meta.get_id(k).is_id)
                self.assert_(not e.meta.pop_id(k).is_id); e.meta[k] = v

        def test_has_not_item(k):
            self.assert_(not e.meta.has_key(k))
            self.assertRaises(KeyError, e.get_meta, k)
            self.assertRaises(KeyError, e.get_meta_id, k)
            self.assertRaises(KeyError, e.meta.__getitem__, k)
            self.assertRaises(KeyError, e.meta.pop, k)
            self.assertRaises(KeyError, e.meta.pop_id, k)
            self.assertEqual("!", e.get_meta(k, "!"))
            self.assertEqual("!", e.get_meta_id(k, "!"))
            self.assertEqual(None, e.meta.get(k))
            self.assertEqual("!", e.meta.get(k, "!"))
            self.assertEqual("!", e.meta.get_id(k, "!"))
            self.assertEqual("!", e.meta.pop(k, "!"))
            self.assertEqual("!", e.meta.pop_id(k, "!"))

        info = self.p.create_resource("info", "text/html")
        ref = []
        random_items = [
            (dc_description, "bla bla bla"),
            (rdfs_seeAlso, info),
            (dc_creator, "pchampin"),
        ]

        test_is_list() # ref is empty

        for k, v in random_items:
            test_has_not_item(k)
            ref.append((k, v))
            ref.sort()
            e.set_meta(k, v)
            for k2, v2 in ref:
                test_has_item(k2, v2)
            test_is_list()

        for k, v in random_items:
            ref.remove((k,v))
            e.del_meta(k)
            for k2, v2 in ref:
                test_has_item(k2, v2)
            test_is_list()
            test_has_not_item(k)

        test_is_list() # ref is empty

        # TODO: not yet tested: some dict methods in meta

    def _test_list_like(self, L, a, name):
        # L is the list-like element to test
        # a is a list of 2O potential items for L
        p = self.p

        get_item = getattr(L, "get_%s" % name)
        get_id = getattr(L, "get_%s_id" % name)
        iter_ids = getattr(L, "iter_%s_ids" % name)

        self.assertEqual([], list(L))
        self.assertEqual([], list(iter_ids()))
        L.append(a[2])
        self.assertEqual([a[2],], list(L))
        self.assertEqual([a[2].id,], list(iter_ids()))
        L.insert(0,a[1])
        self.assertEqual([a[1], a[2]], list(L))
        self.assertEqual([a[1].id, a[2].id], list(iter_ids()))
        L.insert(2,a[4])
        self.assertEqual([a[1], a[2], a[4]], list(L))
        self.assertEqual([a[1].id, a[2].id, a[4].id], list(iter_ids()))
        L.insert(100,a[5])
        self.assertEqual([a[1], a[2], a[4], a[5]], list(L))
        self.assertEqual([a[1].id, a[2].id, a[4].id, a[5].id], 
                         list(iter_ids()))
        L.insert(-2,a[3])
        self.assertEqual(a[1:6], list(L))
        self.assertEqual([ i.id for i in a[1:6] ], list(iter_ids()))
        L.insert(-6,a[0])
        self.assertEqual(a[0:6], list(L))
        self.assertEqual([ i.id for i in a[0:6] ], list(iter_ids()))
        L.extend(a[6:9])
        self.assertEqual(a[0:9], list(L))
        self.assertEqual([ i.id for i in a[0:9] ], list(iter_ids()))

        for i in xrange(9):
            self.assertEqual(a[i], L[i])
            self.assertEqual(a[i], get_item(i))
            self.assertEqual(a[i].id, get_id(i))
            L[i] = a[i+10]
            self.assertEqual(a[i+10], L[i])
            self.assertEqual(a[i+10], get_item(i))
            self.assertEqual(a[i+10].id, get_id(i))

        del L[5]
        self.assertEqual(a[10:15]+a[16:19], list(L))
        self.assertEqual([i.id for i in a[10:15]+a[16:19] ], list(iter_ids()))
        L.insert(5,a[15])


        self.assertEqual(a[10:19], L[:])
        self.assertEqual(a[10:13], L[:3])
        self.assertEqual(a[12:19], L[2:])
        self.assertEqual(a[12:13], L[2:3])
        self.assertEqual(a[10:19:2], L[::2])
        self.assertEqual(a[15:11:-2], L[5:1:-2])

        b = L[:]

        L[2:4] = a[0:9]
        b[2:4] = a[0:9]
        self.assertEqual(b, list(L))
        self.assertEqual([ i.id for i in b ], list(iter_ids()))

        L[:] = a[0:10]
        b[:] = a[0:10]
        self.assertEqual(b, list(L))
        self.assertEqual([ i.id for i in b ], list(iter_ids()))

        L[9:0:-2] = a[19:10:-2]
        b[9:0:-2] = a[19:10:-2]
        self.assertEqual(b, list(L))
        self.assertEqual([ i.id for i in b ], list(iter_ids()))

        del L[0::2]
        del b[0::2]
        self.assertEqual(b, list(L))
        self.assertEqual([ i.id for i in b ], list(iter_ids()))

    def _test_with_tag(self, e):
        p = self.p
        t1 = p.create_tag("t1")
        t2 = p.create_tag("t2")
        t3 = p.create_tag("t3")
        tm = p.create_media("tm", "http://example.com/tm.avi")
        ta1 = p.create_annotation("ta1", tm, 0, 10, "text/plain")
        ta2 = p.create_annotation("ta2", tm, 5, 15, "text/plain")
        p.associate_tag(tm, t1)
        p.associate_tag(tm, t2)
        p.associate_tag(ta1, t1)
        p.associate_tag(ta2, t2)
        p.associate_tag(e, t1)
        p.associate_tag(e, t3)

        def ids(elts, p):
            return frozenset( t.make_id_in(p) for t in elts )       
        eq = self.assertEqual

        eq(frozenset((t1, t3)), frozenset(e.iter_my_tags(p)))
        eq(frozenset((t1, t2)), frozenset(tm.iter_my_tags(p)))
        eq(frozenset((t1,)), frozenset(ta1.iter_my_tags(p)))
        eq(frozenset((t2,)), frozenset(ta2.iter_my_tags(p)))
        eq(ids((t1, t3), p), frozenset(e.iter_my_tag_ids(p)))
        eq(ids((t1, t2), p), frozenset(tm.iter_my_tag_ids(p)))
        eq(ids((t1,), p), frozenset(ta1.iter_my_tag_ids(p)))
        eq(ids((t2,), p), frozenset(ta2.iter_my_tag_ids(p)))

        eq(frozenset((t1, t3)), frozenset(e.iter_my_tags(p, 0)))
        eq(frozenset((t1, t2)), frozenset(tm.iter_my_tags(p, 0)))
        eq(frozenset((t1,)), frozenset(ta1.iter_my_tags(p, 0)))
        eq(frozenset((t2,)), frozenset(ta2.iter_my_tags(p, 0)))
        eq(ids((t1, t3), p), frozenset(e.iter_my_tag_ids(p, 0)))
        eq(ids((t1, t2), p), frozenset(tm.iter_my_tag_ids(p, 0)))
        eq(ids((t1,), p), frozenset(ta1.iter_my_tag_ids(p, 0)))
        eq(ids((t2,), p), frozenset(ta2.iter_my_tag_ids(p, 0)))

        eq(frozenset((tm, ta1, e)), frozenset(t1.iter_elements(p)))
        eq(frozenset((tm, ta2)), frozenset(t2.iter_elements(p)))
        eq(frozenset((e,)), frozenset(t3.iter_elements(p)))
        eq(ids((tm, ta1, e), p), frozenset(t1.iter_element_ids(p)))
        eq(ids((tm, ta2), p), frozenset(t2.iter_element_ids(p)))
        eq(ids((e,), p), frozenset(t3.iter_element_ids(p)))

        eq(frozenset((tm, ta1, e)), frozenset(t1.iter_elements(p, 0)))
        eq(frozenset((tm, ta2)), frozenset(t2.iter_elements(p, 0)))
        eq(frozenset((e,)), frozenset(t3.iter_elements(p, 0)))
        eq(ids((tm, ta1, e), p), frozenset(t1.iter_element_ids(p, 0)))
        eq(ids((tm, ta2), p), frozenset(t2.iter_element_ids(p, 0)))
        eq(ids((e,), p), frozenset(t3.iter_element_ids(p, 0)))

        q = self.q
        q.create_import("i", self.p)
        q.associate_tag(tm, t3)
        q.associate_tag(ta1, t2)
        q.associate_tag(ta2, t1)
        q.associate_tag(e, t2)
        q.associate_tag(e, t3)

        eq(frozenset((t1, t2, t3)), frozenset(e.iter_my_tags(q)))
        eq(frozenset((t1, t2, t3)), frozenset(tm.iter_my_tags(q)))
        eq(frozenset((t1, t2)), frozenset(ta1.iter_my_tags(q)))
        eq(frozenset((t1, t2)), frozenset(ta2.iter_my_tags(q)))
        eq(ids((t1, t2, t3), q), frozenset(e.iter_my_tag_ids(q)))
        eq(ids((t1, t2, t3), q), frozenset(tm.iter_my_tag_ids(q)))
        eq(ids((t1, t2), q), frozenset(ta1.iter_my_tag_ids(q)))
        eq(ids((t1, t2), q), frozenset(ta2.iter_my_tag_ids(q)))

        eq(frozenset((t2, t3)), frozenset(e.iter_my_tags(q, 0)))
        eq(frozenset((t3,)), frozenset(tm.iter_my_tags(q, 0)))
        eq(frozenset((t2,)), frozenset(ta1.iter_my_tags(q, 0)))
        eq(frozenset((t1,)), frozenset(ta2.iter_my_tags(q, 0)))
        eq(ids((t2, t3), q), frozenset(e.iter_my_tag_ids(q, 0)))
        eq(ids((t3,), q), frozenset(tm.iter_my_tag_ids(q, 0)))
        eq(ids((t2,), q), frozenset(ta1.iter_my_tag_ids(q, 0)))
        eq(ids((t1,), q), frozenset(ta2.iter_my_tag_ids(q, 0)))

        eq(frozenset((t1, t3)), frozenset(e.iter_my_tags(p)))
        eq(frozenset((t1, t2)), frozenset(tm.iter_my_tags(p)))
        eq(frozenset((t1,)), frozenset(ta1.iter_my_tags(p)))
        eq(frozenset((t2,)), frozenset(ta2.iter_my_tags(p)))
        eq(ids((t1, t3), p), frozenset(e.iter_my_tag_ids(p)))
        eq(ids((t1, t2), p), frozenset(tm.iter_my_tag_ids(p)))
        eq(ids((t1,), p), frozenset(ta1.iter_my_tag_ids(p)))
        eq(ids((t2,), p), frozenset(ta2.iter_my_tag_ids(p)))

        eq(frozenset((tm, ta1, ta2, e)), frozenset(t1.iter_elements(q)))
        eq(frozenset((tm, ta1, ta2, e)), frozenset(t2.iter_elements(q)))
        eq(frozenset((tm, e)), frozenset(t3.iter_elements(q)))
        eq(ids((tm, ta1, ta2, e), q), frozenset(t1.iter_element_ids(q)))
        eq(ids((tm, ta1, ta2, e), q), frozenset(t2.iter_element_ids(q)))
        eq(ids((tm, e), q), frozenset(t3.iter_element_ids(q)))

        eq(frozenset((ta2,)), frozenset(t1.iter_elements(q, 0)))
        eq(frozenset((ta1, e)), frozenset(t2.iter_elements(q, 0)))
        eq(frozenset((tm, e)), frozenset(t3.iter_elements(q, 0)))
        eq(ids((ta2,), q), frozenset(t1.iter_element_ids(q, 0)))
        eq(ids((ta1, e), q), frozenset(t2.iter_element_ids(q, 0)))
        eq(ids((tm, e), q), frozenset(t3.iter_element_ids(q, 0)))

        eq(frozenset((tm, ta1, e)), frozenset(t1.iter_elements(p)))
        eq(frozenset((tm, ta2)), frozenset(t2.iter_elements(p)))
        eq(frozenset((e,)), frozenset(t3.iter_elements(p)))
        eq(ids((tm, ta1, e), p), frozenset(t1.iter_element_ids(p)))
        eq(ids((tm, ta2), p), frozenset(t2.iter_element_ids(p)))
        eq(ids((e,), p), frozenset(t3.iter_element_ids(p)))

        eq(frozenset((p,)), frozenset(e.iter_taggers(t1, q)))
        eq(frozenset((p,)), frozenset(e.iter_taggers(t1, p)))
        eq(frozenset((p, q,)), frozenset(e.iter_taggers(t3, q)))
        eq(frozenset((p,)), frozenset(e.iter_taggers(t3, p)))

        self.assert_(e.has_tag(t1, q))
        self.assert_(not e.has_tag(t1, q, 0))
        self.assert_(e.has_tag(t1, p))
        self.assert_(e.has_tag(t1, p, 0))
        self.assert_(t1.has_element(e, q))
        self.assert_(not t1.has_element(e, q, 0))
        self.assert_(t1.has_element(e, p))
        self.assert_(t1.has_element(e, p, 0))
        self.assert_(e.has_tag(t3, q))
        self.assert_(e.has_tag(t3, q, 0))
        self.assert_(e.has_tag(t3, p))
        self.assert_(t3.has_element(e, q))
        self.assert_(t3.has_element(e, q, 0))
        self.assert_(t3.has_element(e, p))

        p.dissociate_tag(e, t3)
        eq(frozenset((t1, t2, t3)), frozenset(e.iter_my_tags(q)))
        eq(ids((t1, t2, t3), q), frozenset(e.iter_my_tag_ids(q)))
        eq(frozenset((t2, t3)), frozenset(e.iter_my_tags(q, 0)))
        eq(ids((t2, t3), q), frozenset(e.iter_my_tag_ids(q, 0)))
        eq(frozenset((t1,)), frozenset(e.iter_my_tags(p)))
        eq(ids((t1,), p), frozenset(e.iter_my_tag_ids(p)))
        eq(frozenset((tm, e)), frozenset(t3.iter_elements(q)))
        eq(ids((tm, e), q), frozenset(t3.iter_element_ids(q)))
        eq(frozenset((tm, e)), frozenset(t3.iter_elements(q, 0)))
        eq(ids((tm, e), q), frozenset(t3.iter_element_ids(q, 0)))
        eq(frozenset(()), frozenset(t3.iter_elements(p)))
        eq(ids((), p), frozenset(t3.iter_element_ids(p)))
        eq(frozenset((q,)), frozenset(e.iter_taggers(t3, q)))
        eq(frozenset(), frozenset(e.iter_taggers(t3, p)))
        self.assert_(e.has_tag(t3, q))
        self.assert_(e.has_tag(t3, q, 0))
        self.assert_(not e.has_tag(t3, p))
        self.assert_(t3.has_element(e, q))
        self.assert_(t3.has_element(e, q, 0))
        self.assert_(not t3.has_element(e, p))

        q.dissociate_tag(e, t3)
        eq(frozenset((t1, t2)), frozenset(e.iter_my_tags(q)))
        eq(ids((t1, t2), q), frozenset(e.iter_my_tag_ids(q)))
        eq(frozenset((t2,)), frozenset(e.iter_my_tags(q, 0)))
        eq(ids((t2,), q), frozenset(e.iter_my_tag_ids(q, 0)))
        eq(frozenset((t1,)), frozenset(e.iter_my_tags(p)))
        eq(ids((t1,), p), frozenset(e.iter_my_tag_ids(p)))
        eq(frozenset((tm,)), frozenset(t3.iter_elements(q)))
        eq(ids((tm,), q), frozenset(t3.iter_element_ids(q)))
        eq(frozenset((tm,)), frozenset(t3.iter_elements(q, 0)))
        eq(ids((tm,), q), frozenset(t3.iter_element_ids(q, 0)))
        eq(frozenset(()), frozenset(t3.iter_elements(p)))
        eq(ids((), p), frozenset(t3.iter_element_ids(p)))
        eq(frozenset(), frozenset(e.iter_taggers(t3, q)))
        eq(frozenset(), frozenset(e.iter_taggers(t3, p)))
        self.assert_(not e.has_tag(t3, q))
        self.assert_(not e.has_tag(t3, q, 0))
        self.assert_(not e.has_tag(t3, p))
        self.assert_(not t3.has_element(e, q))
        self.assert_(not t3.has_element(e, q, 0))
        self.assert_(not t3.has_element(e, p))

    # actual test methods

    def test_package_meta(self):
        p = self.p
        self._test_with_meta(p)

    def test_media(self):
        p = self.p
        self._test_volatile("m1")
        m = p.get("m1")
        self.assertEqual(m.url, "http://example.com/m1.avi")
        m.url = "http://example.com/m2.ogg"
        m = p.get("m1")
        self.assertEqual(m.url, "http://example.com/m2.ogg")
        self.assertEqual(m.frame_of_reference, DEFAULT_FOREF)
        m.frame_of_reference = FOREF_PREFIX + "s;o=42"
        m = p.get("m1")
        self.assertEqual(m.frame_of_reference, FOREF_PREFIX + "s;o=42")

    def test_annotation(self):
        p = self.p
        m = p["m1"]
        p.create_annotation("a1", m, 10, 25, "text/plain")
        self._test_volatile("a1")
        a = p.get("a1")
        self.assertEqual( m, a.media)
        self.assertEqual(10, a.begin)
        self.assertEqual(25, a.end)
        self.assertEqual(15, a.duration)
        a.begin += 5
        a = p.get("a1")
        self.assertEqual(15, a.begin)
        self.assertEqual(25, a.end)
        a.end += 10
        a = p.get("a1")
        self.assertEqual(15, a.begin)
        self.assertEqual(35, a.end)
        a.duration += 5
        a = p.get("a1")
        self.assertEqual(15, a.begin)
        self.assertEqual(40, a.end)
        m2 = p.create_media("m2", "http://example.com/m2.avi")
        a.media = m2
        a = p.get("a1")
        self.assertEqual(m2, a.media)
        self._test_with_content(a)
        self._test_with_meta(a)
        self._test_with_tag(a)

        a2 = p.create_annotation("a2", m, 42, 43, "test/plain")
        r1 = p.create_relation("r1", members=[a])
        r2 = p.create_relation("r2", members=[a2])
        q = self.q
        #q.create_import("i", p) # already done in _test_with_tag
        r3 = q.create_relation("r3", members=[a])
        r4 = q.create_relation("r4", members=[a2])
        self.assertEqual(frozenset(a.iter_relations(p)), frozenset([r1,]))
        self.assertEqual(frozenset(a.iter_relations(q)), frozenset([r1, r3]))
        self.assertEqual(a.count_relations(p), 1)
        self.assertEqual(a.count_relations(q), 2)
        session.package = q
        r1[0:0] = [a2,a2]
        r3.append(a2)
        r4.append(a)
        self.assertEqual(frozenset(a.relations), frozenset([r1,r3,r4]))
        self.assertEqual(frozenset(a.iter_relations(position=0)), frozenset([r3]))
        self.assertEqual(frozenset(a.relations.filter(position=0)), frozenset([r3]))
        self.assertEqual(frozenset(a.incoming_relations), frozenset([r3]))
        self.assertEqual(frozenset(a.outgoing_relations), frozenset([r4]))

    def test_relation(self):
        p = self.p
        m = p["m1"]
        a = [ p.create_annotation("a%s" % i, m, i*10, i*10+19, "text/plain")
              for i in xrange(20) ]

        p.create_relation("r1", "text/plain")
        self._test_volatile("r1")
        r = p.get("r1")
        self._test_list_like(r, a, "member")
        self._test_with_content(r)
        self._test_with_meta(r)
        self._test_with_tag(r)

        r2 = p.create_relation("r2", "text/plain", members=a)
        self.assertEqual(a, list(r2))

    def test_list(self):
        p = self.p
        a = [ p.create_relation("r%s" % i, "text/plain") for i in xrange(10) ] \
          + [ p.create_list("x%s" % i) for i in xrange(10) ]

        p.create_list("l1")
        self._test_volatile("l1")
        L = p.get("l1")
        self._test_list_like(L, a, "item")
        self._test_with_meta(L)
        self._test_with_tag(L)

        L2 = p.create_list("l2", items=a)
        self.assertEquals(a, list(L2))

    def test_tag(self):
        p = self.p
        p.create_tag("t1")
        self._test_volatile("t1")

    def test_import(self):
        p = self.p
        q = self.q
        q.create_import("i1", p)
        self._test_volatile("i1", package=q)
        i = q.get("i1")
        # TODO test attributes

    def test_query(self):
        p = self.p
        p.create_query("q1", "text/plain")
        self._test_volatile("q1")
        q = p.get("q1")
        # TODO test content handler

    def test_view(self):
        p = self.p
        p.create_view("v1", "text/plain")
        self._test_volatile("v1")
        v = p.get("v1")
        # TODO test content handler

    def test_resource(self):
        p = self.p
        p.create_resource("R1", "text/plain")
        self._test_volatile("R1")
        R = p.get("R1")
        # TODO test content handler


class TestTagAsGroup(TestCase):
    def setUp(self):
        p = Package("file:/tmp/p", create=True)
        self.m1 = p.create_media("m1", "http://example.com/m1.avi")
        self.t1 = p.create_tag("t1")
        p.associate_tag(self.m1, self.t1)
        session.package = p

    def tearDown(self):
        pass

    def testError(self):
        del session.package
        self.assertRaises(TypeError, list, self.t1)
        self.assertRaises(TypeError, list, self.t1.medias)

    def testWorking(self):
        self.assertEquals(list(self.t1), [self.m1,])


class TestUnreachable(TestCase):
    def setUp(self):
        self.dirname = mkdtemp()
        self.filename = path.join(self.dirname, "db")
        self.url1 = "sqlite:" + pathname2url(self.filename)
        self.url2 = self.url1 + ";foo"
        self.url3 = self.url2 + ";bar"

        p1 = Package(self.url1, create=True)
        p2 = Package(self.url2, create=True)
        i = p1.create_import("p2", p2)
        m = p2.create_media("m", "http://example.com/m.avi",
                            FOREF_PREFIX+"ms;o=0")
        s = p2.create_resource("model", "text/plain")
        d = p1.create_resource("desc", "text/plain")
        a2 = p2.create_annotation("a2", m, 0, 10, "text/plain")
        a1 = p1.create_annotation("a1", m, 0, 10, "text/plain", model=s)
        r = p1.create_relation("r", "text/plain", members=[a1, a2,])
        l = p1.create_list("l", items=[a1, s])
        t1 = p1.create_tag("t1")
        t2 = p2.create_tag("t2")
        p1.associate_tag(a1, t1)
        p1.associate_tag(a1, t2)
        p1.associate_tag(a2, t1)
        p1.associate_tag(a2, t2)
        p1.set_meta(dc_description, d)
        p1.set_meta(rdfs_seeAlso, m)
        p1.set_meta(dc_creator, "pchampin")
        p1.close()
        p2.close()

        p3 = Package(self.url3, create=True)
        p3.close()

    def tearDown(self):
        unlink(self.filename)
        rmdir(self.dirname)

    def make_import_unreachable(self):
        p1 = Package(self.url1)
        p1["p2"].url = "x-unknown-scheme:abc"
        p1.close()

    def make_elements_inexistant(self):
        p1 = Package(self.url1)
        p1["p2"].url = self.url3
        p1.close()

    def _make_both_tests(f):
        def both_tests(self, f=f):
            self.make_import_unreachable()
            f(self, UnreachableImportError)
            self.make_elements_inexistant()
            f(self, NoSuchElementError)
        return both_tests

    @_make_both_tests
    def test_model(self, exception_type):
        p1 = Package(self.url1)
        self.assertEquals("p2:model", p1["a1"].content_model_id)
        self.assertRaises(exception_type,
                          getattr, p1["a1"], "content_model")
        self.assertEquals(None, p1["a1"].get_content_model(None))
        p1.close()

    @_make_both_tests
    def test_media(self, exception_type):
        p1 = Package(self.url1)
        self.assertEquals("p2:m", p1["a1"].media_id)
        self.assertRaises(exception_type,
                          getattr, p1["a1"], "media")
        self.assertEquals(None, p1["a1"].get_media(None))
        p1.close()

    @_make_both_tests
    def test_member(self, exception_type):
        p1 = Package(self.url1)
        r = p1["r"]
        a1 = p1["a1"]
        self.assertEquals("p2:a2", r.get_member_id(1))
        self.assertRaises(exception_type, r.__getitem__, 1)
        self.assertEquals(None, r.get_member(1))
        self.assertEquals([a1, None,], list(r))
        self.assertEquals(["a1", "p2:a2",], list(r.iter_member_ids()))
        p1.close()

    @_make_both_tests
    def test_item(self, exception_type):
        p1 = Package(self.url1)
        L = p1["l"]
        a1 = p1["a1"]
        self.assertEquals("p2:model", L.get_item_id(1))
        self.assertRaises(exception_type, L.__getitem__, 1)
        self.assertEquals(None, L.get_item(1))
        self.assertEquals([a1, None,], list(L))
        self.assertEquals(["a1", "p2:model",], list(L.iter_item_ids()))
        p1.close()

    @_make_both_tests
    def test_meta(self, exception_type):
        p1 = Package(self.url1)
        self.assertEqual(None, p1.get_meta(rdfs_seeAlso, None))
        self.assertEqual("!", p1.get_meta(rdfs_seeAlso, "!"))
        self.assertEqual("p2:m", p1.get_meta_id(rdfs_seeAlso, "!"))
        self.assertRaises(exception_type, p1.get_meta, rdfs_seeAlso)
        self.assertEqual(None, p1.meta.get(rdfs_seeAlso))
        self.assertEqual("!", p1.meta.get(rdfs_seeAlso, "!"))
        self.assertEqual("p2:m", p1.meta.get_id(rdfs_seeAlso))
        self.assertEqual("p2:m", p1.meta.get_id(rdfs_seeAlso, "!"))
        self.assertRaises(exception_type, p1.meta.__getitem__, rdfs_seeAlso)

        d = p1["desc"]
        ref = [(dc_creator, "pchampin"), (dc_description, "desc"),
               (rdfs_seeAlso, "p2:m"),]
        ref2 = [(dc_creator, "pchampin"), (dc_description, d),
                (rdfs_seeAlso, None),]
        refiid = [False, True, True,]
        def mapiid1(L):
            return [ v.is_id for v in L ]
        def mapiid2(L):
            return [ v.is_id for k, v in L ]
        i = p1.iter_meta(); i.next(); i.next() # no raise before actual yield
        p1.meta.keys() # no exception when iterating over keys only
        list(p1.meta.iterkeys()) # no exception when iterating over keys only
        list(p1.meta) # no exception when iterating over keys only

        self.assertEquals(ref2, list(p1.iter_meta()))
        self.assertEquals(ref2, list(p1.meta.iteritems()))
        self.assertEquals(ref2, p1.meta.items())
        self.assertEquals([v for k,v in ref2], list(p1.meta.itervalues()))
        self.assertEquals([v for k,v in ref2], p1.meta.values())
        self.assertEqual(ref, list(p1.iter_meta_ids()))
        self.assertEqual(ref, list(p1.meta.iteritems_ids()))
        self.assertEqual(ref, p1.meta.items_ids())
        self.assertEqual([v for k,v in ref], list(p1.meta.itervalues_ids()))
        self.assertEqual([v for k,v in ref], p1.meta.values_ids())
        self.assertEqual(refiid, mapiid2(p1.meta.iteritems_ids()))
        self.assertEqual(refiid, mapiid2(p1.meta.items_ids()))
        self.assertEqual(refiid, mapiid1(p1.meta.itervalues_ids()))
        self.assertEqual(refiid, mapiid1(p1.meta.values_ids()))
        
        p1.close()

    @_make_both_tests
    def test_tag(self, exception_type):
        p1 = Package(self.url1)
        a1 = p1["a1"]
        t1 = p1["t1"]
        self.assertEquals(frozenset(("t1", "p2:t2")),
                                    frozenset(a1.iter_my_tag_ids(p1)))
        self.assertEquals(frozenset((t1, None)),
            frozenset(a1.iter_my_tags(p1)))
        self.assertEquals(frozenset(("a1", "p2:a2")),
                                    frozenset(t1.iter_element_ids(p1)))
        self.assertEquals(frozenset((a1, None)),
            frozenset(t1.iter_elements(p1)))
        p1.close()


class TestEvents(TestCase):
    def setUp(self):
        self.dirname = mkdtemp()
        self.db = path.join(self.dirname, "db")
        self.url = "sqlite:%s" % pathname2url(self.db)
        self.p1 = Package(self.url+";p1", create=True)
        self.p2 = Package(self.url+";p2", create=True)
        self.p2.create_media("m1", "file:/tmp/test.avi")
        self.p2.create_tag("t1")
        self.p2.create_tag("t2")
        self.p2.create_resource("R1", "text/plain")
        self.p2.create_resource("R2", "text/plain")
        self.p1.create_import("i1", self.p2)
        self.p1.create_annotation("a1", self.p2.get("m1"), 10, 20, "text/plain")
        self.p1.create_media("m2", "file:/tmp/test2.avi")
        self.p1.create_annotation("a2", self.p1.get("m2"), 30, 40, "text/plain")
        self.p1.create_relation("r1")
        self.p1.create_list("L1")

        # we use the following to check that event subscription is robust to
        # the fact that elements are volatile
        def _make_accessor(p, id):
            def _accessor():
                gc.collect()
                return p.get(id)
            return _accessor

        self.m1 = _make_accessor(self.p2, "m1")
        self.t1 = _make_accessor(self.p2, "t1")
        self.t2 = _make_accessor(self.p2, "t2")
        self.R1 = _make_accessor(self.p2, "R1")
        self.R2 = _make_accessor(self.p2, "R2")
        self.i1 = _make_accessor(self.p1, "i1")
        self.a1 = _make_accessor(self.p1, "a1")
        self.m2 = _make_accessor(self.p1, "m2")
        self.a2 = _make_accessor(self.p1, "a2")
        self.r1 = _make_accessor(self.p1, "r1")
        self.L1 = _make_accessor(self.p1, "L1")

        self.buf = []
        self.callback_errors = []

    def tearDown(self):
        try:
            if self.p1 and not self.p1.closed: self.p1.close()
            if self.p2 and not self.p2.closed: self.p2.close()
        except ValueError: 
            pass
        unlink(self.db)
        rmdir(self.dirname)


    def default_handler(self, *args):
        self.buf.append(args)

    def attr_handler(self, obj, attr, val, pre=None):
        actual_val = getattr(obj, attr)
        if pre:
            if actual_val == val:
                self.callback_errors.append("%s should not be %r yet" %
                                            (attr, val))
        else:
            if actual_val != val:
                self.callback_errors.append("%s = %r, should be %r" %
                                            (attr, actual_val, val))
        self.default_handler(obj, attr, val)

    def meta_handler(self, obj, key, val, pre=None):
        actual_val = obj.get_meta(key, None)
        if pre:
            if actual_val == val:
                self.callback_errors.append("%s should not be %r yet" %
                                            (key, val))
        else:
            if actual_val != val:
                self.callback_errors.append("%s : %r, should be %r" %
                                            (key, actual_val, val))
        self.default_handler(obj, key, val)

    def tag_handler(self, obj, tag, removed=None):
        if removed:
            if obj.has_tag(tag, self.p1):
                self.callback_errors.append("%s should not have tag %s yet" %
                                            (obj.id, tag.id))
        else:
            if not obj.has_tag(tag, self.p1):
                self.callback_errors.append("%s should have tag %s" %
                                            (obj.id, tag.id))
        self.default_handler(obj, tag)

    def element_handler(self, obj, element, removed=None):
        self.tag_handler(element, obj, removed)

    def test_modified_meta(self):
        k = DC_NS_PREFIX + "creator"
        k2 = DC_NS_PREFIX + "title"
        hid1 = self.m1().connect("modified-meta::" + k, self.meta_handler)
        hid2 = self.m1().connect("pre-modified-meta::" + k, self.meta_handler, 1)
        self.m1().set_meta(k2, "hello world")
        self.assertEqual(self.buf, [])
        self.a1().set_meta(k, "pchampin")
        self.assertEqual(self.buf, [])
        self.m1().set_meta(k, "pchampin")
        self.assertEqual(self.buf, [(self.m1(), k, "pchampin"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().del_meta(k2)
        self.assertEqual(self.buf, [])
        self.a1().del_meta(k)
        self.assertEqual(self.buf, [])
        self.m1().del_meta(k)
        self.assertEqual(self.buf, [(self.m1(), k, None)]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid1)
        self.m1().disconnect(hid2)
        self.m1().set_meta(k, "oaubert")
        self.assertEqual(self.buf, [])

    def test_modified_meta_any(self):
        k = DC_NS_PREFIX + "creator"
        hid1 = self.m1().connect("modified-meta", self.meta_handler)
        hid2 = self.m1().connect("pre-modified-meta", self.meta_handler, "pre")
        self.a1().set_meta(k, "pchampin")
        self.assertEqual(self.buf, [])
        self.m1().set_meta(k, "pchampin")
        self.assertEqual(self.buf, [(self.m1(), k, "pchampin"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().del_meta(k)
        self.assertEqual(self.buf, [])
        self.m1().del_meta(k)
        self.assertEqual(self.buf, [(self.m1(), k, None)]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid1)
        self.m1().disconnect(hid2)
        self.m1().set_meta(k, "oaubert")
        self.assertEqual(self.buf, [])

    def test_added_tag_removed_tag(self):
        hid = self.m1().connect("added-tag", self.tag_handler)
        self.p1.associate_tag(self.a1(), self.t1())
        self.assertEqual(self.buf, [])
        self.p1.associate_tag(self.m1(), self.t1())
        self.assertEqual(self.buf, [(self.m1(), self.t1(),),])
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid)
        self.p1.associate_tag(self.m1(), self.t2())
        self.assertEqual(self.buf, [])
        del self.buf[:]
        hid = self.m1().connect("removed-tag", self.tag_handler, "remove")
        self.p1.dissociate_tag(self.a1(), self.t1())
        self.assertEqual(self.buf, [])
        self.p1.dissociate_tag(self.m1(), self.t1())
        self.assertEqual(self.buf, [(self.m1(), self.t1(),),])
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid)
        self.p1.dissociate_tag(self.m1(), self.t2())
        self.assertEqual(self.buf, [])

    def test_added_removed(self):
        hid = self.t1().connect("added", self.element_handler)
        self.p1.associate_tag(self.m1(), self.t2())
        self.assertEqual(self.buf, [])
        self.p1.associate_tag(self.m1(), self.t1())
        self.assertEqual(self.buf, [(self.m1(), self.t1(),),])
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.t1().disconnect(hid)
        self.p1.associate_tag(self.a1(), self.t1())
        self.assertEqual(self.buf, [])
        del self.buf[:]
        hid = self.t1().connect("removed", self.element_handler, "remove")
        self.p1.dissociate_tag(self.m1(), self.t2())
        self.assertEqual(self.buf, [])
        self.p1.dissociate_tag(self.m1(), self.t1())
        self.assertEqual(self.buf, [(self.m1(), self.t1(),),])
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.t1().disconnect(hid)
        self.p1.dissociate_tag(self.a1(), self.t1())
        self.assertEqual(self.buf, [])

    def test_with_content_modified_mimetype(self):
        hid1 = self.a1().connect("modified::content_mimetype", self.attr_handler)
        hid2 = self.a1().connect("pre-modified::content_mimetype",
                               self.attr_handler, "pre")
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().content_mimetype = "text/html"
        self.assertEqual(self.buf,
                         [(self.a1(), "content_mimetype", "text/html"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().content_mimetype = "image/png"
        self.assertEqual(self.buf, [])

    def test_with_content_modified_model(self):
        hid1 = self.a1().connect("modified::content_model", self.attr_handler)
        hid2 = self.a1().connect("pre-modified::content_model",
                               self.attr_handler, "pre")
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().content_model = self.R1()
        self.assertEqual(self.buf,
                         [(self.a1(), "content_model", self.R1()),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().content_model = self.R2()
        self.assertEqual(self.buf, [])

    def test_with_content_modified_url(self):
        hid1 = self.a1().connect("modified::content_url", self.attr_handler)
        hid2 = self.a1().connect("pre-modified::content_url",
                               self.attr_handler, "pre")
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().content_url = "file:/foo"
        self.assertEqual(self.buf,
                         [(self.a1(), "content_url", "file:/foo"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().content_url = "file:/bar"
        self.assertEqual(self.buf, [])

    def test_with_content_modified_data(self):
        hid1 = self.a1().connect("modified-content-data", self.default_handler)
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().content_data = "listen carefully"
        self.assertEqual(self.buf,
                         [(self.a1(), None),])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().content_url = "I shall say this only once"
        self.assertEqual(self.buf, [])


    def test_media_modified_url(self):
        hid1 = self.m1().connect("modified::url", self.attr_handler)
        hid2 = self.m1().connect("pre-modified::url", self.attr_handler, "pre")
        self.m1().frame_of_reference = FOREF_PREFIX + "s;o=0"
        self.assertEqual(self.buf, [])
        self.m1().url = "file:/foo.avi"
        self.assertEqual(self.buf, [(self.m1(), "url", "file:/foo.avi"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid1)
        self.m1().disconnect(hid2)
        self.m1().url = "file:/bar./avi"
        self.assertEqual(self.buf, [])

    def test_media_modified_frame_of_reference(self):
        hid1 = self.m1().connect("modified::frame_of_reference", self.attr_handler)
        hid2 = self.m1().connect("pre-modified::frame_of_reference",
                               self.attr_handler, "pre")
        self.m1().url = "file:/foo.avi"
        self.assertEqual(self.buf, [])
        self.m1().frame_of_reference = FOREF_PREFIX + "s;o=0"
        self.assertEqual(self.buf, [(self.m1(), "frame_of_reference",
                                     FOREF_PREFIX + "s;o=0",)]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid1)
        self.m1().disconnect(hid2)
        self.m1().frame_of_reference = FOREF_PREFIX + "ms;o=1"
        self.assertEqual(self.buf, [])

    def test_media_modified_any(self):
        hid1 = self.m1().connect("modified", self.attr_handler)
        hid2 = self.m1().connect("pre-modified", self.attr_handler, "pre")
        self.m1().frame_of_reference = FOREF_PREFIX + "s;o=0"
        self.assertEqual(self.buf, [(self.m1(), "frame_of_reference",
                                     FOREF_PREFIX + "s;o=0",)]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().url = "file:/foo.avi"
        self.assertEqual(self.buf, [(self.m1(), "url", "file:/foo.avi"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.m1().disconnect(hid1)
        self.m1().disconnect(hid2)
        self.m1().url = "file:/bar./avi"
        self.assertEqual(self.buf, [])
        self.m1().frame_of_reference = FOREF_PREFIX + "ms;o=1"
        self.assertEqual(self.buf, [])

    def test_annotation_modified_media(self):
        hid1 = self.a1().connect("modified::media", self.attr_handler)
        hid2 = self.a1().connect("pre-modified::media", self.attr_handler, "pre")
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().media = self.m2()
        self.assertEqual(self.buf, [(self.a1(), "media", self.m2()),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().media = self.m1()
        self.assertEqual(self.buf, [])

    def test_annotation_modified_begin(self):
        hid1 = self.a1().connect("pre-modified::begin", self.attr_handler, "pre")
        hid2 = self.a1().connect("modified::begin", self.attr_handler)
        self.a1().end = 21
        self.assertEqual(self.buf, [])
        self.a1().begin = 11
        self.assertEqual(self.buf, [(self.a1(), "begin", 11),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().begin = 12
        self.assertEqual(self.buf, [])

    def test_annotation_modified_end(self):
        hid1 = self.a1().connect("modified::end", self.attr_handler)
        hid2 = self.a1().connect("pre-modified::end", self.attr_handler, "pre")
        self.a1().begin = 11
        self.assertEqual(self.buf, [])
        self.a1().end = 21
        self.assertEqual(self.buf, [(self.a1(), "end", 21),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().end = 22
        self.assertEqual(self.buf, [])

    def test_annotation_modified_any(self):
        hid1 = self.a1().connect("modified", self.attr_handler)
        hid2 = self.a1().connect("pre-modified", self.attr_handler, "pre")
        self.a1().media = self.m2()
        self.assertEqual(self.buf, [(self.a1(), "media", self.m2()),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().begin = 11
        self.assertEqual(self.buf, [(self.a1(), "begin", 11),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().end = 21
        self.assertEqual(self.buf, [(self.a1(), "end", 21),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().content_mimetype = "text/html"
        self.assertEqual(self.buf,
                         [(self.a1(), "content_mimetype", "text/html"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.a1().disconnect(hid1)
        self.a1().disconnect(hid2)
        self.a1().media = self.m1()
        self.a1().begin = 12
        self.a1().end = 22
        self.a1().content_mimetype = "image/png"
        self.assertEqual(self.buf, [])

    def test_relation_setitem(self):
        self.r1().append(self.a1())
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        self.r1()[0] = self.a2()
        s = slice(0,1)
        L = [self.a2(),]
        self.assertEqual(self.buf, [(self.r1(), s, L),]*2)
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        self.r1()[0] = self.a2()
        self.assertEqual(self.buf, [])

    def test_relation_delitem(self):
        self.r1().extend([self.a1(), self.a2()])
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        del self.r1()[0]
        s = slice(0,1)
        self.assertEqual(self.buf, [(self.r1(), s, []),]*2)
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        del self.r1()[0]
        self.assertEqual(self.buf, [])

    def test_relation_append(self):
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        self.r1().append(self.a1())
        s = slice(0,0)
        L = [self.a1(),]
        self.assertEqual(self.buf, [(self.r1(), s, L),]*2)
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        self.r1().append(self.a2())
        self.assertEqual(self.buf, [])

    def test_relation_set_slice(self):
        self.r1().extend([self.a1(), self.a2()])
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        s = slice(1,2)
        L = [self.a2(), self.a1()]
        self.r1()[s] = L
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        self.r1()[1:2] = [self.a1(), self.a2(),]
        self.assertEqual(self.buf, [])

    def test_relation_del_slice(self):
        self.r1().extend([self.a1(), self.a2(), self.a1(), self.a2()])
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        s = slice(0,1)
        del self.r1()[s]
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        del self.r1()[0:1]
        self.assertEqual(self.buf, [])

    def test_relation_extend(self):
        hid1 = self.r1().connect("modified-items", self.default_handler)
        hid2 = self.r1().connect("pre-modified-items", self.default_handler)
        self.r1().extend([self.a1(), self.a2(),])
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.r1().disconnect(hid1)
        self.r1().disconnect(hid2)
        self.r1().extend([self.a2(), self.a1(),])
        self.assertEqual(self.buf, [])

    def test_list_setitem(self):
        self.L1().append(self.a1())
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        self.L1()[0] = self.a2()
        s = slice(0,1)
        L = [self.a2(),]
        self.assertEqual(self.buf, [(self.L1(), s, L),]*2)
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        self.L1()[0] = self.a2()
        self.assertEqual(self.buf, [])

    def test_list_delitem(self):
        self.L1().extend([self.a1(), self.a2()])
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        del self.L1()[0]
        s = slice(0,1)
        self.assertEqual(self.buf, [(self.L1(), s, []),]*2)
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        del self.L1()[0]
        self.assertEqual(self.buf, [])

    def test_list_append(self):
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        self.L1().append(self.a1())
        s = slice(0,0)
        L = [self.a1(),]
        self.assertEqual(self.buf, [(self.L1(), s, L),]*2)
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        self.L1().append(self.a2())
        self.assertEqual(self.buf, [])

    def test_list_set_slice(self):
        self.L1().extend([self.a1(), self.a2()])
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        s = slice(1,2)
        L = [self.a2(), self.a1()]
        self.L1()[s] = L
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        self.L1()[1:2] = [self.a1(), self.a2(),]
        self.assertEqual(self.buf, [])

    def test_list_del_slice(self):
        self.L1().extend([self.a1(), self.a2(), self.a1(), self.a2()])
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        s = slice(0,1)
        del self.L1()[s]
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        del self.L1()[0:1]
        self.assertEqual(self.buf, [])

    def test_list_extend(self):
        hid1 = self.L1().connect("modified-items", self.default_handler)
        hid2 = self.L1().connect("pre-modified-items", self.default_handler)
        self.L1().extend([self.a1(), self.a2(),])
        self.assertNotEqual(self.buf, [])
        del self.buf[:]
        self.L1().disconnect(hid1)
        self.L1().disconnect(hid2)
        self.L1().extend([self.a2(), self.a1(),])
        self.assertEqual(self.buf, [])

    def test_import_modified_url(self):
        hid1 = self.i1().connect("modified::url", self.attr_handler)
        hid2 = self.i1().connect("pre-modified::url", self.attr_handler, "pre")
        self.i1().uri = "file:/foo.bzp"
        self.assertEqual(self.buf, [])
        self.i1().url = "file:/foo.bzp"
        self.assertEqual(self.buf, [(self.i1(), "url", "file:/foo.bzp"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.i1().disconnect(hid1)
        self.i1().disconnect(hid2)
        self.i1().url = "file:/bar.bzp"
        self.assertEqual(self.buf, [])

    def test_import_modified_uri(self):
        hid1 = self.i1().connect("modified::uri", self.attr_handler)
        hid2 = self.i1().connect("pre-modified::uri", self.attr_handler, "pre")
        self.i1().url = "file:/foo.bzp"
        self.assertEqual(self.buf, [])
        self.i1().uri = "file:/foo.bzp"
        self.assertEqual(self.buf, [(self.i1(), "uri", "file:/foo.bzp"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.i1().disconnect(hid1)
        self.i1().disconnect(hid2)
        self.i1().uri = "file:/bar.bzp"
        self.assertEqual(self.buf, [])

    def test_import_modified_any(self):
        hid1 = self.i1().connect("modified", self.attr_handler)
        hid2 = self.i1().connect("pre-modified", self.attr_handler, "pre")
        self.i1().url = "file:/foo.bzp"
        self.assertEqual(self.buf, [(self.i1(), "url", "file:/foo.bzp"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.i1().uri = "file:/foo.bzp"
        self.assertEqual(self.buf, [(self.i1(), "uri", "file:/foo.bzp"),]*2)
        self.assertEqual(self.callback_errors, [])
        del self.buf[:]
        self.i1().disconnect(hid1)
        self.i1().disconnect(hid2)
        self.i1().url = "file:/bar.bzp"
        self.i1().uri = "file:/bar.bzp"
        self.assertEqual(self.buf, [])

    def test_no_event_section(self):
        # NB: we only test it on one kind of element
        # It should be ok because it is implemented in a mixin.
        hid1 = self.a1().connect("modified", self.attr_handler)
        hid2 = self.a1().connect("pre-modified", self.attr_handler, "pre")
        hid1 = self.a1().connect("modified-meta", self.meta_handler)
        hid2 = self.a1().connect("pre-modified-meta", self.meta_handler, "pre")
        self.a1().enter_no_event_section(); \
            self.a1().media = self.m2(); \
            self.a1().begin = 11; \
            self.a1().end = 12; \
            self.a1().set_meta(DC_NS_PREFIX + "creator", "somebody else"); \
            self.assertEqual(self.buf, [])
        self.a1().exit_no_event_section()
        self.a1().end = 13
        self.assertNotEqual(self.buf, [])


class TestReferences(TestCase):

    def setUp(self):
        p = self.p = Package("transient:1", create=True)
        q = self.q = Package("transient:2", create=True)

        m1 = q.create_media("m1", "http://example.com/m1.avi")
        at1 = q.create_tag("at1")
        rt1 = q.create_tag("rt1")
        a1 = q.create_annotation("a1", m1, 0, 42, "text/plain")
        q.associate_tag(a1, at1)
        r1 = q.create_relation("r1", members=[a1,])
        q.associate_tag(r1, rt1)
        L1 = q.create_list("L1", items=[m1, a1, r1,])
        t1 = q.create_tag("t1")
        R1 = q.create_resource("R1", "text/plain")
        a1.content_model = R1

        p.create_import("i", q)
        m2 = p.create_media("m2", "http://example.com/m2.avi")
        at2 = p.create_tag("at2")
        rt2 = p.create_tag("rt2")
        a2 = p.create_annotation("a2", m2, 0, 42, "text/plain")
        p.associate_tag(a2, at2)
        r2 = p.create_relation("r2", members=[a2,])
        p.associate_tag(r2, rt2)
        L2 = p.create_list("L2", items=[m2, a2, r2,])
        t2 = p.create_tag("t2")
        R2 = p.create_resource("R2", "text/plain")
        a2.content_model = R2

        a3 = p.create_annotation("a3", m1, 1, 2, "text/plain")
        p.associate_tag(a3, at1)
        a3.content_model=R1
        r3 = p.create_relation("r3", members=[a2, a1,])
        p.associate_tag(r3, rt2)
        L3 = p.create_list("L3", items=[a1, m1,])

        p.meta["key"] = a1
        p.associate_tag(a1, t1)

    def tearDown(self):
        self.p.close()
        self.q.close()

    def test_iter_references(self):
        def check(it1, it2=None):
            if it2 is None: print list(it1) # debugging
            else:
                #self.assertEqual(frozenset(it1), frozenset(it2))
                try:
                    s1 = frozenset(
                        (r.reference_type, r.referrer, r.reference_parameter)
                        for r in it1
                    )
                    s2 = frozenset(it2)
                    self.assertEqual(s1, s2)
                except AssertionError, e:
                    print "+++", s1.difference(s2)
                    print "---", s2.difference(s1)
                    raise e

        p = self.p
        q = self.q
        at1 = q.get("at1")
        m1 = q.get("m1")
        a1 = q.get("a1")
        a3 = p.get("a3")
        r1 = q.get("r1")
        r3 = p.get("r3")
        t1 = q.get("t1")
        L1 = q.get("L1")
        L3 = p.get("L3")
        R1 = q.get("R1")

        check(at1.iter_references(), [
            (":tag", q, a1), (":tag", p, a3),
        ])

        check(a1.iter_references(), [
            (":tagged", q, at1), (":tagged", p, t1),
            (":item", L1, 1), (":item", L3, 0),
            (":member", r1, 0), (":member", r3, 1),
            (":meta", p, "key"),
        ])

        check(m1.iter_references(), [
            ("media", a1, None), ("media", a3, None),
            (":item", L1, 0), (":item", L3, 1),
        ])


        check(R1.iter_references(), [
            ("content_model", a1, None), ("content_model", a3, None),
        ])

    def _do_test_rename(self):
        p = self.p
        q = self.q

        q.get("m1").id = "m01"
        self.assertNotEqual(q.get("m01"), None)
        self.assertEqual(q.get("a1").media_id, "m01")
        self.assertEqual(p.get("a3").media_id, "i:m01")

        q.get("at1").id = "at01"
        assert not q.has_element("at1")
        assert q.has_element("at01")
        assert "at01" in q.get("a1").iter_my_tag_ids(q)
        assert "i:at01" in p.get("a3").iter_my_tag_ids(p)
        assert "at01" in list(q.get("a1").iter_my_tag_ids(q))
        assert "i:at01" in list(p.get("a3").iter_my_tag_ids(p))

        q.get("a1").id = "a01"
        assert not q.has_element("a1")
        assert q.has_element("a01")
        self.assertEqual(p.get_meta_id("key"), "i:a01")
        assert "a01" in list(q.get("at01").iter_element_ids(q))
        self.assertEqual(q.get("r1").get_member_id(0), "a01")
        self.assertEqual(p.get("r3").get_member_id(1), "i:a01")
        self.assertEqual(q.get("L1").get_item_id(1), "a01")
        assert "i:a01" in p.get("L3").iter_item_ids()

        q.get("R1").id = "R01"
        assert not q.has_element("R1")
        assert q.has_element("R01")
        self.assertEqual(q.get("a01").content_model_id, "R01")
        self.assertEqual(p.get("a3").content_model_id, "i:R01")

        p.get("i").id = "j"
        assert not p.has_element("i")
        assert p.has_element("j")
        assert p.get("i:a01") is None
        assert p.get("j:a01") is not None
        assert "j:at01" in p.get("a3").iter_my_tag_ids(p)
        assert "j:at01" in list(p.get("a3").iter_my_tag_ids(p))
        self.assertEqual(p.get_meta_id("key"), "j:a01")
        self.assertEqual(p.get("r3").get_member_id(1), "j:a01")
        assert "j:a01" in p.get("L3").iter_item_ids()

        # fake name clash: a2 exists in p, but not in q
        q.get("a01").id = "a2"
        assert not q.has_element("a01")
        assert q.has_element("a2")
        self.assertEqual(p.meta.get_id("key"), "j:a2")
        assert "a2" in q.get("at01").iter_element_ids(q)
        self.assertEqual(q.get("r1").get_member_id(0), "a2")
        self.assertEqual(p.get("r3").get_member_id(1), "j:a2")
        self.assertEqual(q.get("L1").get_item_id(1), "a2")
        assert "j:a2" in p.get("L3").iter_item_ids()

        # real name clash
        self.assertRaises(AssertionError, setattr, p.get("a2"), "id", "a3")

    def test_rename_volatile(self):
        # in this method, we check that renaming is performed correctly
        # when the objects are volatile, and mainly relying on the backend

        self._do_test_rename()

    def test_rename_in_caches(self):
        # in this method, we check that renaming is performed correctly
        # when the objects are kept in memory, and rely on their internal
        # cache.
        # For this purpose, we keep a reference of all involved objects,
        # and try to have their cache filled by accessing the attributes

        p = self.p
        q = self.q

        m1 = q.get("m1")
        a1 = q.get("a1"); a1m = a1.media; a1c = a1.content_model
        at1 = q.get("at1")
        r1 = q.get("r1"); r1m = list(r1)
        r3 = p.get("r3"); r3m = list(r3)
        L1 = q.get("L1"); L1i = list(L1)
        L3 = p.get("L3"); L3i = list(L3)
        R1 = q.get("R1")
        a3 = p.get("a3"); a3c = a3.content_model
        pm = list(p.iter_meta())
        a3 = p.get("a3"); a3m = a3.media; a3c = a3.content_model

        self._do_test_rename()

if __name__ == "__main__":
    main()

