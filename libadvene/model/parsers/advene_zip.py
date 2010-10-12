"""
Unstable and experimental parser implementation.

See `libadvene.model.parsers.advene_xml` for the reference implementation.
"""

from tempfile import mkdtemp
from os import path, tmpfile
from shutil import rmtree
from zipfile import BadZipfile, ZipFile

from libadvene.model.consts import PACKAGED_ROOT
import libadvene.model.parsers.advene_xml as advene_xml
import libadvene.model.serializers.advene_zip as serializer

class Parser(object):

    NAME = serializer.NAME
    EXTENSION = serializer.EXTENSION
    MIMETYPE = serializer.MIMETYPE
    SERIALIZER = serializer # may be None for some parsers

    @classmethod
    def claims_for_parse(cls, file_):
        """Is this parser likely to parse that file-like object?

        `file_` is a readable file-like object. It is the responsability of the
        caller to close it.
        """
        r = 0

        info = getattr(file_, "info", lambda: {})()
        mimetype = info.get("content-type", "")
        if mimetype.startswith(cls.MIMETYPE):
            r = 80 # overrides extension
        elif mimetype.startswith("application/x-zip"):
            r += 30
            fpath = get_path(file_)
            raise Exception
            if fpath.endswith(cls.EXTENSION):
                r += 40
            elif fpath.endswith(".zip"):
                r += 20

        if hasattr(file_, "seek"):
            # If possible, inspect ZIP file to adjust the claim-score.
            # NB: if those tests fail, we do not drop the claim-score to 0,
            # but merely reduce it. This is because, if no other parser claims
            # that file, a ParseError will be more informative than a
            # NoClaimError.
            old_pos = file_.tell()
            try:
                z = ZipFile(file_, "r")
            except BadZipfile:
                r /= 5
            else:
                if "mimetype" in z.namelist():
                    if z.read("mimetype").startswith(cls.MIMETYPE):
                        r = max(r, 70)
                    else:
                        r /= 5
                elif "content.xml" in z.namelist():
                    r = max(r, 20)
                    # wait for other information to make up our mind
                else:
                    r /= 5
                z.close()
            file_.seek(old_pos)
            
        return r

    @classmethod
    def make_parser(cls, file_, package):
        """Return a parser that will parse `url` into `package`.

        `file_` is a writable file-like object. It is the responsability of the
        caller to close it.

        The returned object must implement the interface for which
        :class:`_Parser` is the reference implementation.
        """
        return cls(file_, package)

    @classmethod
    def parse_into(cls, file_, package):
        """A shortcut for ``make_parser(url, package).parse()``.

        See also `make_parser`.
        """
        parser = cls(file_, package)
        try:
            parser.parse()
        finally:
            rmtree(parser.dir, ignore_errors=True)
            

    def parse(self):
        "Do the actual parsing."
        backend = self.package._backend
        pid = self.package._id
        backend.set_meta(pid, "", "", PACKAGED_ROOT, self.dir, False)
        # TODO use notification to clean it when package is closed
        f = open(self.content)
        self._XML_PARSER.parse_into(f, self.package)
        f.close()

    # end of public interface

    _XML_PARSER = advene_xml.Parser

    def __init__(self, file_, package):
        self.dir = d = mkdtemp(prefix="advene2_zip_")

        if hasattr(file_, "seek"):
            g = None
            z = ZipFile(file_, "r")
        else:
            # ZipFile requires seekable file, dump it in tmpfile
            g = tmpfile()
            g.write(file_.read())
            g.seek(0)
            z = ZipFile(g, "r")
        names = z.namelist()
        for zname in names:
            seq = zname.split("/")
            dirname = recursive_mkdir(d, seq[:-1])
            if seq[-1]:
                fname = path.join(dirname, seq[-1])
                h = open(fname, "w")
                h.write(z.read(zname))
                h.close()
        z.close()
        if g is not None:
            g.close()

        self.content = path.join(d, "content.xml")
        self.package = package

