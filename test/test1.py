from os import unlink
from os.path import exists, join, split
import gc
import sys

from advene.model.core.package import Package

uri = "sqlite:%s" % (join (split (__file__)[0], "test1.db"))
#uri = "sqlite::memory:"

def trace_wrapper (f):
    def wrapped (*args, **kw):
        print "===", f.__name__, (args or ""), (kw or "")
        r = f (*args, **kw)
        print "===", f.__name__, "->", r
        return r
    return wrapped

def trace_wrap_all (obj):
    cd = obj.__class__.__dict__
    od = obj.__dict__
    for k,v in cd.iteritems():
        if k[0] != "_" and callable (v):
            f = getattr (obj, k)
            od[k] = trace_wrapper (f)

if __name__ == "__main__":


    if exists (uri[7:]): unlink (uri[7:])

    Package.make_metadata_property ("dc#Creator", "dc_creator")

    p = Package(uri, create=True)
    #trace_wrap_all (p._backend)

    m1 = p.create_media("m1", "http://champin.net/stream.avi")
    a1 = p.create_annotation("a1", m1, 20, 30)
    p.create_annotation("a2", m1, 0, 20)
    p.create_relation("r1")
    print [a._id for a in p.own.annotations]
    print p.get("a1")
    print p["a2"]
    p.get_element("a1").content.data = "hello"
    p.dc_creator = "pchampin"
    a1.begin += 1
    

    NB = 10
    print "creating %s annotations" % NB
    for i in range(NB):
        p.create_annotation("aa%s" % i, m1, i*10, i*10+9)
    print "done"

    # ensure that backend is collected
    a1 = None; a = None; m1 = None; p = None; gc.collect()

    print

    print "about to re-load package"
    p = Package(uri)
    print "package loaded"
    #trace_wrap_all (p._backend)

    l = list (p.own.annotations)
    #print [a._id for a in p.own.annotations]
    a1 = p.get_element ("a1")
    a2 = p.get_element ("a2")
    print id(a1) == id(p.get_element ("a1"))
    print a1.content.data
    print p.dc_creator
    print a1.begin

    l = None; a1 = None; a2 = None; p = None
