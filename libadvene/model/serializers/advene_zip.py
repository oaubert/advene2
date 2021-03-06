"""
Unstable and experimental serializer implementation.

See `libadvene.model.serializers.advene_xml` for the reference implementation.
"""

from os import listdir, mkdir, path
from os.path import exists, isdir
from zipfile import ZipFile, ZIP_DEFLATED

from libadvene.model.consts import PACKAGED_ROOT
from libadvene.model.core.content import create_temporary_packaged_root
import libadvene.model.serializers.advene_xml as advene_xml

NAME = "Generic Advene Zipped Package"

EXTENSION = ".bzp" # Advene-2 Zipped Package

MIMETYPE = "application/x-advene-bzp"

def make_serializer(package, file_):
    """Return a serializer that will serialize `package` to `file_`.

    `file_` is a writable file-like object. It is the responsability of the
    caller to close it.
    """
    return _Serializer(package, file_)

def serialize_to(package, file_):
    """A shortcut for ``make_serializer(package, file).serialize()``.

    See also `make_serializer`.
    """
    return _Serializer(package, file_).serialize()

class _Serializer(object):

    _xml_serializer = advene_xml
    mimetype = MIMETYPE

    def serialize(self):
        """Perform the actual serialization."""
        #print "=== serializing directory", self.dir
        f = open(path.join(self.dir, "content.xml"), "w")
        self._xml_serializer.serialize_to(self.package, f, False)
        f.close()

        z = ZipFile(self.file, "w", self.compression)
        _recurse(z, self.dir)
        z.close()

    def __init__(self, package, file_, compression=None):
        if compression is None:
            self.compression = ZIP_DEFLATED
        else:
            self.compression = compression
        self.dir = dir_ = package.get_meta(PACKAGED_ROOT, None)
        if dir_ is None:
            self.dir = dir_ = create_temporary_packaged_root(package)

        if not exists(path.join(dir_, "mimetype")):
            f = open(path.join(dir_, "mimetype"), "w")
            f.write(self.mimetype)
            f.close()
        if not exists(path.join(dir_, "data")):
            mkdir(path.join(dir_, "data"))

            
        self.package = package
        self.file = file_


def _recurse(z, dirname, base=""):
    for f in listdir(dirname):
        abspath = path.join(dirname, f)
        if isdir(abspath):
            _recurse(z, abspath, path.join(base, f))
        else:
            #print "=== zipping", abspath, path.join(base, f)
            z.write(abspath, path.join(base, f).encode('utf-8'))


if __name__ == "__main__":
    # example of using ZIP serialization and parsing
    from libadvene.model.core.package import Package
    p = Package("file:/tmp/foo.bzp", create=True)

    # prepare directories
    if not exists("/tmp/foo"): mkdir("/tmp/foo")
    if not exists("/tmp/foo/data"): mkdir("/tmp/foo/data")

    # it is now safe to define the packaged-root of the package...
    p.set_meta(PACKAGED_ROOT, "/tmp/foo")
    # ... and to create packaged contents
    r = p.create_resource("R1", "text/plain", None, "packaged:/data/R1.txt")
    # this actually writes in /tmp/foo/data/R1.txt
    r.content_data = "good moaning\n"

    # let us serialize it...
    f = open("/tmp/foo.bzp", "w")
    serialize_to(p, f)
    f.close()
    # ... and parse it again
    q = Package("file:/tmp/foo.bzp")

    # note that advene_xml is smart enough to set the packaged-root if
    # needed, so as to allow to open manually-unzipped packages
    r = Package("file:/tmp/foo/content.xml")
    print r.get_meta(PACKAGED_ROOT)
