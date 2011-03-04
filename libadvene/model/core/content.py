"""I define class Content and a mixin class WithContentMixin for all types of
elements that can have a content.

Note that Content instances are just place-holders for content-related
attributes and methods. They do not store data about the content, the data is
stored in the element owning the content, thanks to WithContentMixin. This
makes their on-demand-generation relatively cheap (no data retrieving).

Note also attributes/methods of the form e.content.X are also
accessible under the form e.content_X, which might be slightly more
efficient (less lookup). Maybe the former should be eventually
deprecated...
"""

from cStringIO import StringIO
from os import path, tmpfile, unlink
from os.path import dirname, exists, join, sep
from tempfile import mkdtemp
from urllib2 import urlopen, url2pathname
from urlparse import urljoin, urlparse
from weakref import ref

from libadvene.model.consts import _RAISE, PACKAGED_ROOT
from libadvene.model.content.register import iter_content_handlers, \
                                          iter_textual_mimetypes
from libadvene.model.core.element import RELATION, RESOURCE
from libadvene.model.exceptions import ModelError
from libadvene.util.autoproperty import autoproperty
from libadvene.util.files import recursive_mkdir

class WithContentMixin:
    """I provide functionality for elements with a content.

    I assume that I will be mixed in subclasses of PackageElement.

    Internal / external contents
    ============================

    At the most abstract levels, there are 3 kinds of contents:

    internal contents
      they are stored in the package, and can be modified.
    external contents
      they are referenced by the package with a URL, and can not be modified.
    empty contents
      only authorized for relations; they are marked by the special mimetype
      "x-advene/none"; neither their model, URL nor data can be modified.

    This is the only distinction the end-user (or the casual developer) should
    be aware of.

    It follows that content-related properties are not independant from one
    another. Property `content_mimetype` has higher priority, as it is used to
    decide whether the content is empty or not (hence whether the other
    properties can be set or not). Then `content_url` is used to decide between
    the two other kinds of content, in order to decide whether `content_data`
    can be set or not. See the documentation of each property for more detail.

    In memory / packaged contents
    =============================

    For packages stored in a transient backend (typically those loaded from and
    saved to a file), there are actually two kinds of internal contents:

    in-memory contents
      are stored in the transient backend, i.e. in memory.
    packaged contents
      are stored in the local file systems; they have a special URL starting
      with 'packaged:'.

    This distinction is useful at runtime (to prevent loading big contents in
    memory) and for serialization: in ZIP formats, packaged contents will not
    be stored in the XML file but in additional files in the archive.

    The package automatically decides whether a content should be in-memory or
    packaged through its method `should_package_content`. This can be manually
    overriden by manually setting the content URL, but note that the package
    may reset this each time the mimetype or data is modified.

    Note that the special 'packaged:' URLs will never appear in the saved
    packaged; the different serializer will convert them according to the
    specification of the file format. For example, the CXP (xml) serializer
    will serialize both in-memory and packaged contents in the XML file, while
    the CZP (zipped) serializer will only put in-memory content in the XML
    file, while packaged contents will be stored as separate files in the zip
    archive, and reference by a relative URL (relative to the file hierarchy
    inside the archive).

    Content initialization
    ======================

    According to CODING_STYLE, a mixin class should not require any
    initialization. However, whenever an element is instantiated from backend
    data, its content information is available, so it would be a waste of
    CPU time (and possibly network traffic) to reload those info from the
    backend for the sake of purity.

    Hence, this class provides a method _instantiate_content, to be used as an
    optimization in the instantiate class method of element classes.
    However, the implementation does not rely on the fact that the mixin will
    be initialized with this method.

    Content handler
    ===============

    Some element types, like views and queries, require a content handler which
    depends on their content's mimetype. This mixin provides a hook method,
    named `_update_content_handler`, which is invoked after the mimetype is
    modified.
    """

    __mimetype = None
    __model_id = None
    __model_wref = staticmethod(lambda: None)
    __url = None
    __data = None # backend data, unless __as_synced_file is not None
    __as_synced_file = None
    __handler = None

    __cached_content = staticmethod(lambda: None)

    def _instantiate_content(self, mimetype, model, url):
        """
        This is method is for optimization only: it is not strictly required
        (though recommended) to call it at instantiate time (see class
        docstring).

        No integrity constraint is checked: the backend is assumed to be sane.
        """
        self.__mimetype = mimetype
        self.__model_id = model
        self.__url = url
        self._update_content_handler()
        self._automanage_storage()

    def _check_content(self, mimetype=None, model_id=None, url=None,
                       _package=None):
        """
        Check that the provided values (assumed to be the future values of
        the corresponding attributes) are valid and consistent (with each other
        *and* with unmodified attributes).

        NB: we do *not* check that model_id identifies a resource. Use
        _check_reference for that.
        """
        # the _package parameter is useful for _check_content_cls (the
        # classmethod version of this method)
        if _package is None:
            _package = self._owner
        if mimetype is not None:
            if len(mimetype.split("/")) != 2:
                raise ModelError("%r does not look like a mimetype" % mimetype)
            if mimetype == "x-advene/none":
                if self.ADVENE_TYPE != RELATION:
                    raise ModelError("Only relations may have an empty content")
                if model_id is None and self.__model_id != "":
                    raise ModelError("Empty content must have no model")
                if url is None and self.__url != "":
                    raise ModelError("Empty content must have no URL")
        if model_id is not None:
            if model_id != "":
                if mimetype == "x-advene/none" \
                or mimetype is None and self.__mimetype == "x-advene/none":
                    raise ModelError("Can not set model of empty content")
        if url is not None:
            if url != "":
                if mimetype == "x-advene/none" \
                or mimetype is None and self.__mimetype == "x-advene/none":
                    raise ModelError("Can not set URL of empty content")
                if url.startswith("packaged:") and not _package._transient:
                    raise ModelError("Can not use packaged contents with "
                                     "persistent backend")

    def _update_caches(self, old_idref, new_idref, element, relation):
        """
        :see-also: `libadvene.model.core.element.PackageElement._update_caches`
        """
        if relation == ("content_model"):
            self.__model_id = new_idref
        else:
            super(WithContentMixin, self) \
                ._update_caches(old_idref, new_idref, element, relation)

    @classmethod
    def _check_content_cls(cls, mimetype, model, url, package,
                           _func=_check_content):
        """
        This is a classmethod variant of _check_content, to be use in
        _instantiate (note that all parameters must be provided in this
        variant).
        """
        # it happens that luring _check_content into using cls as self works
        # and prevents us from writing redundant code
        _func(cls, mimetype, model, url, package)

    def _update_content_handler(self):
        """See :class:`WithContentMixin` documentation."""
        # the following updates the handler for content_parsed
        m = self.__mimetype
        cmax = 0; hmax = None
        for h in iter_content_handlers():
            c = h.claims_for_handle(m)
            if c > cmax:
                cmax, hmax = c, h
        if cmax > 0:
            self.__handler = hmax
        else:
            self.__handler = None


    def _load_content_info(self):
        """Load the content info (mimetype, model, url)."""
        # should actually never be called if _instantiate is used.
        o = self._owner
        self.__mimetype, self.__model_id, self.__url = \
            o._backend.get_content_info(o._id, self._id, self.ADVENE_TYPE)

    def __store_info(self):
        "store info in backend"
        o = self._owner
        o._backend.update_content_info(o._id, self._id, self.ADVENE_TYPE,
                                       self.__mimetype or "",
                                       self.__model_id or "",
                                       self.__url or "")

    def __store_data(self):
        "store data in backend"
        o = self._owner
        o._backend.update_content_data(o._id, self._id, self.ADVENE_TYPE,
                                       self.__data or "")

    def get_content_model(self, default=None):
        """Return the resource used as the model of the content of this element.

        Return None if that content has no model.
        If the model can not be retrieved, the default value is returned.

        See also `content_model` and `content_model_id`.
        """
        # NB: if the default value is _RAISE and the model is unreachable,
        # an exception will be raised.

        mid = self.__model_id
        if mid is None:
            self._load_content_info()
            mid = self.__model_id
        if mid:
            m = self.__model_wref()
            if m is None:
                m = self._owner.get_element(self.__model_id, default)
                if m is not default:
                    self._media_wref = ref(m)
            return m

    def get_content_as_synced_file(self):
        """Return a file-like object giving access to the content data.

        The file-like object is updatable unless the content is external.

        It is an error to try to modify the data while such a file-like object
        is opened. An exception will thus be raised whenever this method is
        invoked or `content_data` is set before a previously returned file-like
        object is closed.

        See also `content_data`.
        """
        url = self.__url
        if url is None:
            self._load_content_info()
            url = self.__url

        if url: # non-empty string
            if url.startswith("packaged:"):
                # special URL scheme
                if self.__as_synced_file:
                    raise IOError("content already opened as a file")
                filename = self._get_content_packaged_path()
                assert filename, "Could not guess packaged path (no root?)"
                f = self.__as_synced_file = PackagedDataFile(filename, self)
            else:
                abs = urljoin(self._owner._url, url)
                f = urlopen(abs)
        else:
            if self.__as_synced_file:
                raise IOError("content already opened as a file")
            f = self.__as_synced_file = ContentDataFile(self)
        return f

    def _automanage_storage(self):
        """
        Switch the way the content of this element is stored.

        If parameter yes is not provided, ask owner package.

        This should only be used with a non-empty, internal content.

        @see-also Package.should_package_content
        """
        if (self._owner._transient is False or
            self.__mimetype == "x-advene/none" or
            self.__url and self.__url[:9] != "packaged:"):
            return
        if self._owner.should_package_content(self):
            self._set_content_url("packaged:/data/%s" % self.id)
        else:
            self._set_content_url("")

    @autoproperty
    def _get_content_mimetype(self):
        """The mimetype of this element's content.

        If set to "x-advene/none", the other properties are erased and become
        unsettable. Note that it is only possible for relations.
        """
        r = self.__mimetype
        if r is None:
            self._load_content_info()
            r = self.__mimetype
        return r

    @autoproperty
    def _set_content_mimetype(self, mimetype):
        if self.__mimetype is None:
            self._load_content_info()
        if mimetype == "x-advene/none":
            self._check_content(mimetype, "", "")
            self._set_content_model(None)
            self._set_content_data("")
            # it is important to set the URL last, because _automanage_storage
            # will re-set it when setting data
            self._set_content_url("")
        else:
            self._check_content(mimetype)
        self.emit("pre-modified::content_mimetype", "content_mimetype", mimetype)
        self.__mimetype = mimetype
        self.__store_info()
        self.emit("modified::content_mimetype", "content_mimetype", mimetype)
        self._automanage_storage()
        self._update_content_handler()

    @autoproperty
    def _get_content_is_textual(self):
        """
        This property indicates if this element's content data can be handled
        as text.

        It uses the mimetypes registered with
        `libadvene.model.content.register.register_textual_mimetype`.
        """
        t1,t2 = self._get_content_mimetype().split("/")
        if t1 == "text":
            return True
        elif t2.endswith("+xml"):
            return True
        for m1,m2 in iter_textual_mimetypes():
            if m1 == "*" or m1 == t1 and m2 == "*" or m2 == t2:
                return True
        return False

    @autoproperty
    def _get_content_model(self):
        """The resource used as the model of the content of this element.

        None if that content has no model.
        If the model can not be retrieved, an exception is raised.

        See also `get_content_model` and `content_model_id`.
        """
        return self.get_content_model(_RAISE)

    @autoproperty
    def _set_content_model(self, resource):
        """FIXME: missing docstring.
        """
        if self.__model_id is None:
            self._load_content_info()
        resource_id = self._check_reference(self._owner, resource, RESOURCE)
        self._check_content(model_id=resource_id)
        op = self._owner
        self.emit("pre-modified::content_model", "content_model", resource)
        if resource_id is not resource:
            self.__model_id = resource_id
            if resource is not None:
                self.__model_wref  = ref(resource)
            elif self.__model_wref() is not None:
                del self.__model_wref
        else:
            if self.__model_wref():
                del self.__model_wref
            if resource is None:
                self.__model_id = ""
            else:
                self.__model_id = unicode(resource_id)
        self.__store_info()
        self.emit("modified::content_model", "content_model", resource)

    @autoproperty
    def _get_content_model_id(self):
        """The id-ref of the content model, or an empty string.

        This is a read-only property giving the id-ref of the resource held
        by `content_model`, or an empty string if there is no model.

        Note that this property is accessible even if the corresponding
        model is unreachable.

        See also `get_content_model` and `content_model`.
        """
        return self.__model_id or ""

    @autoproperty
    def _get_content_url(self):
        """This property holds the URL of the content, or an empty string.

        Its value determines whether the content is external, in-memory or
        packaged.

        Note that setting a standard URL (i.e. not in the ``packaged:`` scheme)
        to an in-memory or packaged URL will discard its data. On the
        other hand, changing in-memory to packaged and vice-versa keeps the
        data.

        Finally, note that setting the URL to one in the ``packaged:`` scheme
        will, if needed,  automatically create a temporary directory and set
        the PACKAGED_ROOT metadata of the package to that directory.
        """
        r = self.__url
        if r is None: # should not happen, but that's safer
            self._load_content_info()
            r = self.__url
        return r

    @autoproperty
    def _set_content_url(self, url):
        """
        The doc is in `_get_content_url` in order to be inherited by the
        property 'content_url' (see `autoproperty` decorator).
        """
        if self.__url is None: # should not happen, but safer
            self._load_content_info()
        if url == self.__url:
            return # no need to perform the complicate things below
        self._check_content(url=url)
        oldurl = self.__url
        if oldurl.startswith("packaged:"):
            # delete packaged data
            fname = self._get_content_packaged_path()
            f = self.__as_synced_file or PackagedDataFile(fname, self)
            f.seek(0)
            self.__data = safe_decode(f.read(), self)
            f.close()
            del self.__as_synced_file
            unlink(fname)
        elif not oldurl:
            self.content_data # ensure self.__data contains the data

        if url.startswith("packaged:"):
            rootdir = self._owner.get_meta(PACKAGED_ROOT, None)
            if rootdir is None:
                rootdir = create_temporary_packaged_root(self._owner)
            fname = self._get_content_packaged_path(url)
            f = PackagedDataFile(fname, self)
            f.write(safe_encode(self.__data))
            f.close()

        if url:
            if self.__data:
                del self.__data
                # don't need to remove data from backend, that will be done
                # when setting URL

        self.emit("pre-modified::content_url", "content_url", url)
        self.__url = url
        self.__store_info()
        if not url:
            self.__store_data()
        self.emit("modified::content_url", "content_url", url)

    @autoproperty
    def _get_content_data(self):
        """This property holds the data of the content.

        It can be read whatever the kind of content (backend-stored, external
        or packaged). However, only backend-stored and packaged can have their
        data safely modified. Trying to set the data of an external content
        will raise a `ValueError`. Its `content_url` must first be set to the
        empty string or a ``packaged:`` URL.

        See also `get_content_as_synced_file`.
        """
        url = self.__url
        if url is None: # should not happen, but that's safer
            self._load_content_info()
            url = self.__url
        f = self.__as_synced_file
        if f: # backend data or "packaged:" url
            # NB: this is not threadsafe
            pos = f.tell()
            f.seek(0)
            r = safe_decode(f.read(), self)
            f.seek(pos)
        elif url: # non-empty string
            f = self.get_content_as_synced_file()
            r = safe_decode(f.read(), self)
            f.close()
        else:
            r = self.__data
            if r is None:
                op = self._owner
                r = self.__data = op._backend. \
                    get_content_data(op._id, self._id, self.ADVENE_TYPE)
        return r

    @autoproperty
    def _set_content_data(self, data):
        """
        The doc is in `_get_content_data` in order to be inherited by the
        property 'content_data' (see `autoproperty` decorator).
        """
        url = self.__url
        if url is None: # should not happen, but that's safer
            self._load_content_info()
            url = self.__url
        if self.__mimetype == "x-advene/none":
            raise ModelError("Can not set data of empty content")
        if url.startswith("packaged:"):
            f = self.get_content_as_synced_file()
            diff = None # TODO make a diff object
            f.truncate()
            f.write(safe_encode(data))
            f.close()
        else:
            if url:
                raise AttributeError("content is external, can not set data")
            elif self.__as_synced_file:
                raise IOError("content already opened as a synced file")
            diff = None # TODO make a diff object
            self.__data = data
            self.__store_data()
        self.emit("modified-content-data", diff)
        self._automanage_storage()

    @autoproperty
    def _get_content_parsed(self):
        h = self.__handler
        if h is not None:
            return h.parse_content(self)
        else:
            return self._get_content_data()

    @autoproperty
    def _set_content_parsed(self, parsed):
        h = self.__handler
        if h is not None:
            return self._set_content_data(h.unparse_content(parsed))
        else:
            return self._set_content_data(self, parsed)

    @autoproperty
    def _get_content_as_file(self):
        """
        This property returns a *copy* of this element's content data wrapped in
        a file-like object.

        Note that the returned file-like object may be writable, but the
        written data will *not* be reflected back to the content. Also, if the
        content data is modified between the moment where this method is called
        and the moment the file-like object is actually read, those changes
        will not be included in the read data.

        For a synchronized file-like object, see `get_content_as_synced_file`.
        """
        return StringIO(safe_encode(self.content_data))

    @autoproperty
    def _get_content_packaged_path(self, _new_url=None):
        """
        Return the path of the content data if it is packaged, else None.
        """

        #If `_new_url` is provided, it is used instead of the current
        #`content_url` (useful when changing URL).

        url = _new_url or self.content_url
        if not url or url[:9] != "packaged:":
            return None
        p_root = self._owner.get_meta(PACKAGED_ROOT, None)        
        if p_root is None:
            return None
        return join(p_root, url2pathname(url[10:]))

    @autoproperty
    def _get_content(self):
        """Return a `Content` instance representing the content."""
        c = self.__cached_content()
        if c is None:
            c = Content(self)
            self.__cached_content = ref(c)
        return c



class Content(object):
    """A class for content objects.

    This class may be deprecated in the future. All attributes and methods have
    equivalent ones in WithContentMixin, with prefix "content_".
    """

    def __init__(self, owner_element):
        self._owner_elt = owner_element

    def get_model(self, default=None):
        return self._owner_elt.get_content_model(default)

    def get_as_synced_file(self):
        return self._owner_elt.get_content_as_synced_file()

    @autoproperty
    def _get_mimetype(self):
        return self._owner_elt._get_content_mimetype()

    @autoproperty
    def _set_mimetype(self, mimetype):
        return self._owner_elt._set_content_mimetype(mimetype)

    @autoproperty
    def _get_is_textual(self):
        """
        This property indicates if this content's data can be handled as text.

        It uses the mimetypes registered with
        `libadvene.model.content.register.register_textual_mimetype`.
        """
        return self._owner_elt._get_content_is_textual()

    @autoproperty
    def _get_model(self):
        return self._owner_elt._get_content_model()

    @autoproperty
    def _set_model(self, model):
        return self._owner_elt._set_content_model(model)

    @autoproperty
    def _get_model_id(self):
        """The id-ref of the model, or None.

        This is a read-only property giving the id-ref of the resource held
        by `model`, or None if there is no model.

        Note that this property is accessible even if the corresponding
        model is unreachable.
        """
        return self._owner_elt._get_content_model_id()

    @autoproperty
    def _get_url(self):
        return self._owner_elt._get_content_url()

    @autoproperty
    def _set_url(self, url):
        return self._owner_elt._set_content_url(url)

    @autoproperty
    def _get_data(self):
        return self._owner_elt._get_content_data()

    @autoproperty
    def _set_data(self, data):
        return self._owner_elt._set_content_data(data)

    @autoproperty
    def _get_parsed(self):
        return self._owner_elt._get_content_parsed()

    @autoproperty
    def _set_parsed(self, parsed):
        return self._owner_elt._set_content_parsed(parsed)

    @autoproperty
    def _get_as_file(self):
        return self._owner_elt._get_content_as_file()

    @autoproperty
    def _get_packaged_path(self):
        return self._owner_elt._get_content_packaged_path()


class PackagedDataFile(file):
    """
    This class fulfils two purposes:

    * create the packaged file when it does not exist (useful because ZIP
      archives do not store empty files)
    * notify the content when the file is closed
    """
    __slots__ = ["_element",]
    def __init__(self, filename, element):
        if exists(filename):
            file.__init__ (self, filename, "r+")
        else:
            base, seq = dirname(filename).split(sep, 1)
            seq.split(sep)
            recursive_mkdir(base+sep, seq.split(sep))
            file.__init__ (self, filename, "w+")
        self._element = element

    def close(self):
        self.seek(0)
        self._element._WithContentMixin__data = safe_decode(self.read(),
                                                            self._element)
        self._element._WithContentMixin__as_synced_file = None
        file.close(self)
        self._element = None


class ContentDataFile(object):
    """FIXME: missing docstring.

    R/W file-like object
    """
    def __init__ (self, element):
        self._element = element
        self._file = f = tmpfile()
        self.flush = f.flush
        self.fileno = f.fileno
        self.isatty = f.isatty
        self.read = f.read
        self.readlines = f.readlines
        self.xreadlines = f.xreadlines
        self.seek = f.seek
        self.tell = f.tell

        f.write(safe_encode(element._WithContentMixin__data or ""))
        f.seek(0)

    def info(self):
        mimetype = self._element._get_content_mimetype()
        return {"content-type": mimetype,}

    def close(self):
        self.seek(0)
        self._element._WithContentMixin__data = safe_decode(self.read(),
                                                            self._element)
        self._element._WithContentMixin__as_synced_file = None
        self._file.close()
        self._element = None

    def truncate(self, *args):
        self._file.truncate(*args)
        self._element._WithContentMixin__store_data()

    def write(self, str_):
        self._file.write(str_)
        self._element._WithContentMixin__store_data()

    def writelines(self, seq):
        self._file.writelines(seq)
        self._element._WithContentMixin__store_data()

    @property
    def closed(self): return self._file.closed

    @property
    def encoding(self): return self._file.encoding

    @property
    def mode(self): return self._file.mode

    @property
    def name(self): return self._file.name

    @property
    def newlines(self): return self._file.newlines

    @autoproperty
    def _get_softspace(self): return self._file.softspace

    @autoproperty
    def _set_softspace(self, val): self._file.softspace = val


def create_temporary_packaged_root(package):
    d = mkdtemp(prefix="advene2_pkg_")
    package.set_meta(PACKAGED_ROOT, d)
    return d

def safe_encode(data):
    if isinstance(data, unicode):
        return data.encode("utf8")
    else:
        return data

def safe_decode(data, element):
    if element.content_is_textual:
        return data.decode("utf8")
    else:
        return data
