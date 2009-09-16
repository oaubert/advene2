from time import time

from libadvene.model.cam.package import Package
from libadvene.util.session import session

import hotshot, os, sys

_t = 0

def measure_time(label=None):
    global _t
    nt = time()
    if label:
        print >> sys.stderr, "%s: %0.3fs" % (label, nt-_t)
    _t = nt

if __name__ == "__main__":

    p = None

    measure_time() # take origin
    p = Package("file:examples/nosferatu.czp")
    measure_time("loading time")

    session.package = p

    def the_test():
        #global p
        #p = Package("file:examples/nosferatu.czp"
        [len(a.relations) for a in p.all.annotations]
        pass

    measure_time() # take origin
    the_test()
    measure_time("the test took")

    measure_time() # take origin
    prof = hotshot.Profile("test/p_nosferatu.prof", lineevents=1)
    prof.run("the_test()")
    prof.close()
    measure_time("the test took")

    p.close()

    os.system("hotshot2calltree -o test/cachegrind.out test/p_nosferatu.prof")
    os.system("kcachegrind test/cachegrind.out")
