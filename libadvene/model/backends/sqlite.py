"""

I am the reference implementation for advene backends modules.

A backend module can be registered by invoking
`libadvene.model.backends.register` with the module as its sole argument. It
must implement 4 functions: `claims_for_create` , `claims_for_bind` , create_
and bind_ . The two latters return a *backend instance* with a standard API,
for which `_SqliteBackend` provides a reference implementation.
"""

#TODO: the backend does not ensure an exclusive access to the sqlite file.
#      this is contrary to the backend specification.
#      We should explore sqlite locking and use it (seems that multiple
#      read-only access is possible), but also the possibility to lock
#      differently each package in the database.

from sqlite3 import dbapi2 as sqlite
from os        import unlink
from os.path   import exists
from urllib    import url2pathname, pathname2url
from weakref   import WeakKeyDictionary, WeakValueDictionary
import re

from libadvene.model.backends.exceptions \
  import ClaimFailure, NoSuchPackage, InternalError, PackageInUse, WrongFormat
import libadvene.model.backends.sqlite_init as sqlite_init
from libadvene.model.core.element \
  import MEDIA, ANNOTATION, RELATION, VIEW, RESOURCE, TAG, LIST, QUERY, IMPORT
from libadvene.model.exceptions import ModelError
from libadvene.util.reftools import WeakValueDictWithCallback


BACKEND_VERSION = "1.2"

IN_MEMORY_URL = "sqlite:%3Amemory%3A"

_DF = False # means that assert will succeed, i.e. *no* debug
# this flag exists so that assertion do not impair efficiency *even* in
# non-optimized mode (because advene is bound to be in non-optimized mode
# for quite a long time ;-) )

def _get_module_debug():
    """Return the state of the module's debug flag.

    The debug flag enables a bunch of ``assert`` statements.
    See also `_set_module_debug`.

    NB: The benefit of disabling debug is not highly significant with sqlite,
    but this would be different with a distant DBMS (because asserts often
    invoke backend methods, resulting on extra queries to the database). Since
    it is expected that a backend implementation over such a DBMS will be done
    by copying and adapting this module, it seems like a good idea to have it.
    """
    global _DF
    return not _DF # _DF == True means "no debug"

def _set_module_debug(b):
    """Set the module's debug flaf. See  _get_module_debug`."""
    global _DF
    _DF = not b # _DF == True means "no debug"



def claims_for_create(url):
    """Is this backend able to create a package to the given URL ?

    Checks whether the URL is recognized, and whether the requested package
    does not already exist at that URL.

    When the result of that method is False, it must be a `ClaimFailure` rather
    than a `bool`. If it has no exception, then the URL is not recognized at
    all. If it has an exception, then the URL is recognized, but attempting
    to create the package will raise that exception.
    """
    if not url.startswith("sqlite:"): return ClaimFailure()

    path, pkgid = _strip_url(url)

    # if already loaded
    bi = _cache.get(path)
    if bi is not None:
        p = bi._bound.get(pkgid)
        if p is not None:
            return ClaimFailure(PackageInUse(p))
        elif _contains_package(bi._conn, pkgid):
            return ClaimFailure(PackageInUse(url))
        else:
            return True

    # in new memory database
    if path == ":memory:":
        return True

    # new connexion to persistent (file) database
    if not exists(path):
        # check that file can be created
        try:
            open(path, "w").close()
        except IOError, e:
            return ClaimFailure(e)
        unlink(path)
        return True
    else:
        try:
            cx = _get_connection(path)
        except Exception, e:
            return ClaimFailure(e)
        if cx is None: return ClaimFailure(WrongFormat(path))
        r = not _contains_package(cx, pkgid)
        cx.close()
        return r or ClaimFailure(PackageInUse(url))

def create(package, force=False, url=None):
    """Creates a new package and return backend instance and package id.

    Parameters
    ----------
    package
      an object with attribute ``url``, which will be used as the backend URL
      unless parameter `url` is also provided.
    force
      should the package be created (i.e. re-initialized) even if it exists?
    url
      URL to be used if ``package.url`` is not adapted to this backend (useful
      for parsed-into-backend packages)
    """
    url = url or package.url
    if force:
        raise NotImplementedError("This backend can not force creation of "
                                  "an existing package")
    r = claims_for_create(url)
    if not r:
        raise r.exception or RuntimeError("Unrecognized URL")

    path, pkgid = _strip_url(url)
    b = _cache.get(path)
    if b is not None:
        conn = b._conn
        curs = b._curs
        b._begin_transaction("EXCLUSIVE")
    else:
        # check the following *before* sqlite.connect creates the file!
        must_init = (path == ":memory:" or not exists(path))
        conn = sqlite.connect(path, isolation_level=None, check_same_thread=False)
        curs = conn.cursor()
        curs.execute("BEGIN EXCLUSIVE")
        if must_init:
            # initialize database
            try:
                for sql in sqlite_init.statements:
                    curs.execute(sql)
                curs.execute("INSERT INTO Version VALUES (?)",
                             (BACKEND_VERSION,))
                curs.execute("INSERT INTO Packages VALUES (?,?,?)",
                             (_DEFAULT_PKGID, "", "",))
            except sqlite.OperationalError, e:
                curs.execute("ROLLBACK")
                raise InternalError("could not initialize model", e)
            except:
                curs.execute("ROLLBACK")
                raise

        b = _SqliteBackend(path, conn, force)
        _cache[path] = b
    try:
        if pkgid != _DEFAULT_PKGID:
            conn.execute("INSERT INTO Packages VALUES (?,?,?)",
                         (pkgid, "", "",))
        b._bind(pkgid, package)
    except sqlite.Error, e:
        curs.execute("ROLLBACK")
        raise InternalError("could not update", e)
    except:
        curs.execute("ROLLBACK")
        raise
    curs.execute("COMMIT")
    return b, pkgid

def claims_for_bind(url):
    """Is this backend able to bind to the given URL ?

    Checks whether the URL is recognized, and whether the requested package
    does already exist in the database.

    When the result of that method is False, it must be a `ClaimFailure` rather
    than a `bool`. If it has no exception, then the URL is not recognized at
    all. If it has an exception, then the URL is recognized, but attempting
    to create the package will raise that exception.
    """
    if not url.startswith("sqlite:"): return ClaimFailure()

    path, pkgid = _strip_url(url)

    # if already loaded
    be = _cache.get(path)
    if be is not None:
        p = be._bound.get(pkgid)
        if p:
            return ClaimFailure(PackageInUse(p))
        else:
            return _contains_package(be._conn, pkgid) \
                or ClaimFailure(NoSuchPackage(pkgid))

    # new memory or persistent (file) database
    if path == ":memory:" or not exists(path):
        return ClaimFailure(NoSuchPackage(url))

    # check that file is a correct database (created by this backend)
    try:
        cx = _get_connection(path)
    except Exception, e:
        return ClaimFailure(e)
    if cx is None:
        return ClaimFailure(WrongFormat(path))
    # check that file does contains the required pkg
    r = _contains_package(cx, pkgid)
    cx.close()
    return r or ClaimFailure(NoSuchPackage(url))

def bind(package, force=False, url=None):
    """Bind to an existing package at the given URL.

    Return the backend an the package id.

    Parameters
    ----------
    package
      an object with attributes ``readonly`` and ``url``, which will be used as
      the backend URL unless parameter `url` is also provided.
    force
      should the package be opened even if it is being used?
    url
      URL to be used if ``package.url`` is not adapted to this backend (useful
      for parsed-into-backend packages)
    """
    url = url or package.url
    if force:
        raise NotImplementedError("This backend can not force access to "
                                   "locked package")
    r = claims_for_bind(url)
    if not r:
        raise r.exception or RuntimeError("Unrecognized URL")

    path, pkgid = _strip_url(url)
    b = _cache.get(path)
    if b is None:
        conn = sqlite.connect(path, isolation_level=None)
        b = _SqliteBackend(path, conn, force)
        _cache[path] = b
    b._begin_transaction("EXCLUSIVE")
    try:
        b._bind(pkgid, package)
    except InternalError:
        b._curs.execute("ROLLBACK")
        raise
    except:
        b._curs.execute("ROLLBACK")
        raise
    b._curs.execute("COMMIT")
    return b, pkgid


_cache = WeakValueDictionary()

_DEFAULT_PKGID = ""

def _strip_url(url):
    """
    Strip URL from its scheme ("sqlite:") and separate path and
    fragment. Also convert path from url to OS-specific pathname expression.
    """
    scheme = 7
    semicolon = url.find(';')
    if semicolon != -1:
        path, pkgid =  url[scheme:semicolon], url[semicolon:]
    else:
        path, pkgid = url[scheme:], _DEFAULT_PKGID
    path = url2pathname(path)
    return path, pkgid

def _get_connection(path):
    try:
        cx = sqlite.connect(path)
        c = cx.execute("SELECT version FROM Version")
        for v in c:
            if v[0] != BACKEND_VERSION: return None
        return cx

    except sqlite.DatabaseError:
        return None
    except sqlite.OperationalError:
        return None

def _contains_package(cx, pkgid):
    c = cx.execute("SELECT id FROM Packages WHERE id = ?", (pkgid,))
    for i in c:
        return True
    return False

def _split_id_ref(id_ref):
    """
    Split an id_ref into a prefix and a suffix.
    Return None prefix if id_ref is a plain id.
    Raise an AssertionError if id_ref has length > 2.
    """
    colon = id_ref.find(":")
    if colon <= 0:
        return "", id_ref
    prefix, suffix = id_ref[:colon], id_ref[colon+1:]
    assert _DF or suffix.find(":") <= 0, "id-path has length > 2"
    return prefix, suffix

def _split_uri_ref(uri_ref):
    """
    Split a uri_ref into a URI and a fragment.
    """
    sharp = uri_ref.find("#")
    return uri_ref[:sharp], uri_ref[sharp+1:]


class _SqliteBackend(object):
    """I am the reference implementation of advene backend instances.

    A number of conventions are used in all methods.

    Method naming rationale
    =======================

    When the parameters *or* return type of methods depend on the element type
    they handle, distinct methods with the element type in their name are
    defined (e.g. `create_annotation` vs. `create_view`). On the other hand, if
    neither the parameters nor the return value change (type-wise) w.r.t. the
    element type, a single method is defined, with the element type as a
    parameter (e.g. `delete_element`).

    Note that, as far as the rule above is concerned, tuples of different size
    have different types, as well as iterators yielding objects of different
    types.

    Note also there is a notable exception to that rule: `get_element`, which
    does not expect the type of an element, but returns a tuple with all the
    elements attributes. A protocol forcing to first get the element type,
    then call the appropriate method, whould have been more regular but
    inconvenient, and probably less efficient.

    Parameter names and semantics
    =============================

    package_id
      the package id as returned in second position by `create` or `bind`. The
      operation will apply to that particular package.

    package_ids
      an iterable of package ids as described above. The operation will apply
      in one shot on all these packages.

    id
      an element id. This is always used in conjunction with ``package_id``.

    element_type
      one of the constants defined in `libadvene.model.core.element`. It is
      always used in conjunction with ``package_id`` and ``id`` and *must* be
      consistent with them (i.e. be the type of the identified element if it
      exists). The behaviour of the method is *unspecified* if ``element_type``
      is not consistent. As a consequence, the fact that this particular
      implementation ignores an inconsistent ``element_type`` and works anyway
      must *not* be relied on.
    """

    # begin of the backend interface

    # package related methods

    def get_bound_url(self, package_id):
        """Return the backend-URL the given package is bound to."""
        return "sqlite:%s%s" % (pathname2url(self._path), package_id)

    def get_url(self, package_id):
        # for the sake of completeness only: this should not be useful, since
        # the URL is told to the backend by the package itself
        q = "SELECT url FROM Packages WHERE id = ?"
        return self._curs.execute(q, (package_id,)).fetchone()[0]

    def update_url(self, package_id, uri):
        q = "UPDATE Packages SET url = ? WHERE id = ?"
        execute = self._curs.execute
        try:
            execute(q, (uri, package_id,))
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def get_uri(self, package_id):
        q = "SELECT uri FROM Packages WHERE id = ?"
        return self._curs.execute(q, (package_id,)).fetchone()[0]

    def update_uri(self, package_id, uri):
        q = "UPDATE Packages SET uri = ? WHERE id = ?"
        execute = self._curs.execute
        try:
            execute(q, (uri, package_id,))
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def close(self, package_id):
        """Inform the backend that a given package will no longer be used.

        NB: this implementation is robust to packages forgetting to close
        themselves, i.e. when packages are garbage collected, this is detected
        and they are automatically unbound.
        """
        d = self._bound
        m = d.get(package_id) # keeping a ref on it prevents it to disappear
        if m is not None:     # in the meantime...
            try:
                self._curs.execute("UPDATE Packages SET url = ? WHERE id = ?",
                                   ("", package_id,))
            except sqlite.Error, e:
                raise InternalError("could not update", e)
            del d[package_id]
        self._check_unused(package_id)

    def delete(self, package_id):
        """Delete from the backend all the data about a bound package.

        Obviously, a deleted package does not need to be closed.
        """
        d = self._bound
        m = d.get(package_id) # keeping a ref on it prevents it to disappear
        if m is not None:     # in the meantime...
            execute = self._curs.execute
            args = [package_id,]

            # NB: all the queries after the first one (and hence the 
            # transaction) are only required because sqlite does not implement
            # foreign keys; with an "ON DELETE CASCADE", the deletion in
            # Packages would suffice

            self._begin_transaction("IMMEDIATE")
            try:
                execute("DELETE FROM Packages WHERE id = ?", args)
                execute("DELETE FROM Elements WHERE package = ?", args)
                execute("DELETE FROM Meta WHERE package = ?", args)
                execute("DELETE FROM Contents WHERE package = ?", args)
                execute("DELETE FROM Medias WHERE package = ?", args)
                execute("DELETE FROM Annotations WHERE package = ?", args)
                execute("DELETE FROM RelationMembers WHERE package = ?", args)
                execute("DELETE FROM ListItems WHERE package = ?", args)
                execute("DELETE FROM Imports WHERE package = ?", args)
                execute("DELETE FROM Tagged WHERE package = ?", args)
            except sqlite.Error, e:
                execute("ROLLBACK")
                raise InternalError("could not delete", e)
            except:
                execute("ROLLBACK")
                raise
            execute("COMMIT")
            del d[package_id]
        self._check_unused(package_id)

    # element creation

    def create_media(self, package_id, id, url, frame_of_reference):
        """Create a new media.

        Raise a ModelException if the identifier already exists in the package.
        """
        c = self._curs
        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, MEDIA)
            execute("INSERT INTO Medias VALUES (?,?,?,?)",
                    (package_id, id, url, frame_of_reference))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not insert", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_annotation(self, package_id, id, media, begin, end,
                          mimetype, model, url):
        """Create a new annotation and its associated content.

        Specific parameters
        -------------------
        media
          id-ref of the media this annotation refs to
        begin, end
          int boundaries of the annotated temporal fragment
        mimetype
          the mimetype of the annotation content
        model
          the id-ref of the content model for the annotation (can be empty)
        url
          if non empty, the annotation content will be not be stored, and will
          be fetched on demand from that URL

        Raise a ModelException if the identifier already exists in the package.
        """
        assert _DF or (isinstance(begin, (int, long)) and begin >= 0), repr(begin)
        mp,ms = _split_id_ref(media) # also assert that media has depth < 2
        assert _DF or mp == "" or self.has_element(package_id, mp, IMPORT), mp
        assert _DF or mp != "" or self.has_element(package_id, ms, MEDIA), ms
        sp,ss = _split_id_ref(model) # also assert that media has depth < 2
        assert _DF or sp == "" or self.has_element(package_id, sp, IMPORT), sp
        assert _DF or sp != "" or ss == "" or \
            self.has_element(package_id, ss, RESOURCE), ss

        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, ANNOTATION)
            execute("INSERT INTO Annotations VALUES (?,?,?,?,?,?)",
                    (package_id, id, mp, ms, begin, end))
            execute("INSERT INTO Contents VALUES (?,?,?,?,?,?,?)",
                    (package_id, id, mimetype, sp, ss, url, "",))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not insert", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_relation(self, package_id, id, mimetype, model, url):
        """Create a new empty relation and its associated content.

        Specific parameters
        -------------------
        mimetype
          the mimetype of the annotation content
        model
          the id-ref of the content model for the annotation (can be empty)
        url
          if non empty, the annotation content will be not be stored, and will
          be fetched on demand from that URL

        Raise a ModelException if the identifier already exists in the package.
        """
        sp,ss = _split_id_ref(model) # also assert that media has depth < 2
        assert _DF or sp == "" or self.has_element(package_id, sp, IMPORT), sp
        assert _DF or sp != "" or ss == "" or \
            self.has_element(package_id, ss, RESOURCE), ss

        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, RELATION)
            execute("INSERT INTO Contents VALUES (?,?,?,?,?,?,?)",
                    (package_id, id, mimetype, sp, ss, url, ""))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_view(self, package_id, id, mimetype, model, url):
        """Create a new view and its associated content.

        Specific parameters
        -------------------
        mimetype
          the mimetype of the view content
        model
          the id-ref of the content model the view (can be empty)
        url
          if non empty, the view content will be not be stored, and will
          be fetched on demand from that URL

        Raise a ModelException if the identifier already exists in the package.
        """
        sp,ss = _split_id_ref(model) # also assert that media has depth < 2
        assert _DF or sp == "" or self.has_element(package_id, sp, IMPORT), sp
        assert _DF or sp != "" or ss == "" or \
            self.has_element(package_id, ss, RESOURCE), ss

        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, VIEW)
            execute("INSERT INTO Contents VALUES (?,?,?,?,?,?,?)",
                    (package_id, id, mimetype, sp, ss, url, "",))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_resource(self, package_id, id, mimetype, model, url):
        """Create a new resource and its associated content.

        Specific parameters
        -------------------
        mimetype
          the mimetype of the resource content
        model
          the id-ref of the content model for the resource (can be empty)
        url
          if non empty, the resource content will be not be stored, and will
          be fetched on demand from that URL

        Raise a ModelException if the identifier already exists in the package.
        """
        sp,ss = _split_id_ref(model) # also assert that media has depth < 2
        assert _DF or sp == "" or self.has_element(package_id, sp, IMPORT), sp
        assert _DF or sp != "" or ss == "" or \
            self.has_element(package_id, ss, RESOURCE), ss

        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, RESOURCE)
            execute("INSERT INTO Contents VALUES (?,?,?,?,?,?,?)",
                    (package_id, id, mimetype, sp, ss, url, "",))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_tag(self, package_id, id):
        """Create a new tag.

        Raise a ModelException if the identifier already exists in the package.
        """
        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, TAG)
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_list(self, package_id, id):
        """Create a new empty list.

        Raise a ModelException if the identifier already exists in the package.
        """
        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, LIST)
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_query(self, package_id, id, mimetype, model, url):
        """Create a new query and its associated content.

        Specific parameters
        -------------------
        mimetype
          the mimetype of the query content
        model
          the id-ref of the content model for the query (can be empty)
        url
          if non empty, the query content will be not be stored, and will
          be fetched on demand from that URL

        Raise a ModelException if the identifier already exists in the package.
        """
        sp,ss = _split_id_ref(model) # also assert that media has depth < 2
        assert _DF or sp == "" or self.has_element(package_id, sp, IMPORT), sp
        assert _DF or sp != "" or ss == "" or \
            self.has_element(package_id, ss, RESOURCE), ss

        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, QUERY)
            execute("INSERT INTO Contents VALUES (?,?,?,?,?,?,?)",
                    (package_id, id, mimetype, sp, ss, url, "",))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating",e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def create_import(self, package_id, id, url, uri):
        """Create a new import.

        Raise a ModelException if the identifier already exists in the package.
        """
        _create_element = self._create_element
        execute = self._curs.execute
        try:
            _create_element(execute, package_id, id, IMPORT)
            execute("INSERT INTO Imports VALUES (?,?,?,?)",
                    (package_id, id, url, uri))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("error in creating", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    # element retrieval

    def has_element(self, package_id, id, element_type=None):
        """
        Return True if the given package has an element with the given id.
        If element_type is provided, only return true if the element has the
        the given type.
        """
        q = "SELECT typ FROM Elements WHERE package = ? and id = ?"
        for i in self._curs.execute(q, (package_id, id,)):
            return element_type is None or i[0] == element_type
        return False

    def get_element(self, package_id, id):
        """Return the tuple describing a given element.

        If the element does not exist, None is returned.
        """

        q = "SELECT e.typ, m.url, m.foref, " \
                   "join_id_ref(a.media_p, a.media_i), " \
                   "a.fbegin, a.fend, i.url, i.uri, c.mimetype, " \
                   "join_id_ref(c.model_p, c.model_i), c.url " \
            "FROM Elements e " \
            "LEFT JOIN Medias m ON e.package = m.package AND e.id = m.id " \
            "LEFT JOIN Annotations a " \
                   "ON e.package = a.package AND e.id = a.id " \
            "LEFT JOIN Imports i ON e.package = i.package AND e.id = i.id " \
            "LEFT JOIN Contents c " \
                   "ON e.package = c.package AND e.id = c.element " \
            "WHERE e.package = ? AND e.id = ?"
        r = self._curs.execute(q, (package_id, id,)).fetchone()
        if r is None:
            return None
        t = r[0]
        if t == MEDIA:
            return(t, package_id, id,) + r[1:3]
        elif t == ANNOTATION:
            return(t, package_id, id,) + r[3:6] + r[8:11]
        elif t in (RELATION, VIEW, RESOURCE, QUERY):
            return(t, package_id, id,) + r[8:11]
        elif t == IMPORT:
            return(t, package_id, id,) + r[6:8]
        else:
            return(t, package_id, id)

    def iter_references(self, package_ids, element):
        """
        Iter over all the elements relying on the identified element
        (where `element` is a uri-ref).

        Yields 3-tuples where the first item one of the given package_ids,
        the second element is either an element id-ref or an empty string to
        identify the package itself. The thirs item describes the relation
        between the second item and the identified element. It can be either:
          an attribute name with an element as its value
            in that case, the identified element is the value of the attribute
            for the element or package identified by the first item.
          the string ":item %s" where %s is an int i
            the first item identifies a list, and its i'th item is the
            identified element
          the string ":member %s" where %s is an int i
            the first item identifies a relation, and its i'th item is the
            identified element
          the string ":meta %s" where %s is a metadata key
            in that case, the identified element is the value of that metadata
            for the element or package identified by the first item.
          the string ":tag %s" where %s is an id-ref
            the identified element is a tag, to which this package identified
            by the first parameter associates the element identified by the
            id-ref.
          the string ":tagged %s" where %s is an id-ref
            this package associates the identified element the tag identified
            by the id-ref.

        The attribute names that may be returned are ``media`` and
        ``content_model``.
        """
        assert _DF or not isinstance(package_ids, basestring)
        elt_u, elt_i = _split_uri_ref(element)
        qmarks = "(" + ",".join("?" for i in package_ids) + ")"
        q = """SELECT a.package, id, 'media'
               FROM Annotations a
               JOIN UriBases u ON a.package = u.package
                               AND media_p = prefix
               WHERE a.package IN %(pid_list)s
               AND uri_base = ? AND media_i = ?
            UNION
               SELECT c.package, element, 'content_model'
               FROM Contents c
               JOIN UriBases u ON c.package = u.package
                               AND model_p = prefix
               WHERE c.package IN %(pid_list)s
               AND uri_base = ? AND model_i = ?
            UNION
               SELECT r.package, relation, ':member '||ord
               FROM RelationMembers r
               JOIN UriBases u ON r.package = u.package
                               AND member_p = prefix
               WHERE r.package IN %(pid_list)s
               AND uri_base = ? AND member_i = ?
            UNION
               SELECT l.package, list, ':item '||ord
               FROM ListItems l
               JOIN UriBases u ON l.package = u.package
                               AND item_p = prefix
               WHERE l.package IN %(pid_list)s
               AND uri_base = ? AND item_i = ?
            UNION
               SELECT t.package, '', ':tag '||join_id_ref(element_p, element_i)
               FROM Tagged t
               JOIN UriBases u ON t.package = u.package
                               AND tag_p = prefix
               WHERE t.package IN %(pid_list)s
               AND uri_base = ? AND tag_i = ?
            UNION
               SELECT t.package, '', ':tagged '||join_id_ref(tag_p, tag_i)
               FROM Tagged t
               JOIN UriBases u ON t.package = u.package
                               AND element_p = prefix
               WHERE t.package IN %(pid_list)s
               AND uri_base = ? AND element_i = ?
            UNION
               SELECT m.package, element, ':meta '||key
               FROM Meta m
               JOIN UriBases u ON m.package = u.package
                               AND value_p = prefix
               WHERE m.package IN %(pid_list)s
               AND uri_base = ? AND value_i = ?
            """ % {"pid_list": qmarks}
        args = (list(package_ids) + [elt_u, elt_i]) * 7
        c = self._conn.execute(q, args)
        r = ( (i[0], i[1], i[2]) for i in c )
        return _FlushableIterator(r, self)

    def iter_references_with_import(self, package_id, id):
        """Iter over all the elements relying on the identified import.

        Yields 3-tuples where the first item is either an element id-ref
        or an empty string to identify the package itself and the third item is
        the id (without the importe prefix) of an element imported through the
        import in question. The second item describes the relation between the
        first and third ones. It can be either:
          an attribute name with an element as its value
            in that case, the imported element is the value of the attribute
            for the element or package identified by the first item.
          the string ":item %s" where %s is an int i
            the first item identifies a list, and its i'th item is the
            imported element
          the string ":member %s" where %s is an int i
            the first item identifies a relation, and its i'th item is the
            imported element
          the string ":meta %s" where %s is a metadata key
            in that case, the imported element is the value of that metadata
            for the element or package identified by the first item.
          the string ":tag %s" where %s is an id-ref
            the identified element is a tag, to which this package identified
            by the first parameter associates the element identified by the
            id-ref.
          the string ":tagged %s" where %s is an id-ref
            this package associates the identified element the tag identified
            by the id-ref.

        The attribute names that may be returned are ``media`` and
        ``content_model``.
        """
        q = """SELECT id, 'media', media_i FROM Annotations
                 WHERE package = ? AND media_p = ?
               UNION
               SELECT element, 'content_model', model_i FROM Contents
                 WHERE package = ? AND model_p = ?
               UNION
               SELECT relation, ':member '||ord, member_i FROM RelationMembers
                 WHERE package = ? AND member_p = ?
               UNION
               SELECT list, ':item '||ord, item_i FROM ListItems
                 WHERE package = ? AND item_p = ?
               UNION
               SELECT '', ':tag '||join_id_ref(element_p, element_i), tag_i
               FROM Tagged
                 WHERE package = ? AND tag_p = ?
               UNION
               SELECT '', ':tagged '||join_id_ref(tag_p, tag_i), element_i
               FROM Tagged
                 WHERE package = ? AND element_p = ?
               UNION
               SELECT element, ':meta '||key, value_i FROM Meta
                 WHERE package = ? AND value_p = ?
            """
        args = [package_id, id, ] * 7
        c = self._conn.execute(q, args)
        return _FlushableIterator(c, self)

    def iter_medias(self, package_ids,
                    id=None,
                    url=None,
                    foref=None,
                   ):
        """
        Yield tuples of the form(MEDIA, package_id, id, url,).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT ?, e.package, e.id, e.url, e.foref",
            "FROM Medias e",
            args = [MEDIA,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if url: q.add_column_filter("e.url", url)
        if foref: q.add_column_filter("e.foref", foref)

        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_annotations(self, package_ids,
                         id=None,
                         media=None,
                         begin=None, begin_min=None, begin_max=None,
                         end=None,   end_min=None,   end_max=None,
                        ):
        """
        Yield tuples of the form
        (ANNOTATION, package_id, id, media, begin, end, mimetype, model, url),
        ordered by begin, end and media id-ref.

        ``media`` is the uri-ref of a media or an iterable of uri-refs.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT ?, e.package, e.id, join_id_ref(e.media_p, e.media_i),"
                  " e.fbegin, e.fend",
            "FROM Annotations e",
            args = [ANNOTATION,]
        )
        q.add_content_columns()
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if media: q.add_media_filter(media)
        if begin: q.append(" AND e.fbegin = ?", begin)
        if begin_min: q.append(" AND e.fbegin >= ?", begin_min)
        if begin_max: q.append(" AND e.fbegin <= ?", begin_max)
        if end: q.append(" AND e.fend = ?", end)
        if end_min: q.append(" AND e.fend >= ?", end_min)
        if end_max: q.append(" AND e.fend <= ?", end_max)
        q.append(" ORDER BY fbegin, fend, media_p, media_i")
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_relations(self, package_ids, id=None, member=None, pos=None):
        """
        Yield tuples of the form (RELATION, package_id, id, mimetype, model, 
        url).
        """
        assert _DF or not isinstance(package_ids, basestring)
        assert _DF or pos is None or member is not None
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [RELATION,]
        )
        q.add_content_columns()
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if member: q.add_member_filter(member, pos)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_views(self, package_ids, id=None):
        """
        Yield tuples of the form (VIEW, package_id, id, mimetype, model, url).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [VIEW,]
        )
        q.add_content_columns()
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_resources(self, package_ids, id=None):
        """
        Yield tuples of the form (RESOURCE, package_id, id, mimetype, model, 
        url).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [RESOURCE,]
        )
        q.add_content_columns()
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_tags(self, package_ids, id=None, meta=None):
        """
        Yield tuples of the form (TAG, package_id, id,).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [TAG,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if meta: q.add_meta_filter(meta)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_lists(self, package_ids, id=None, item=None, pos=None, meta=None):
        """
        Yield tuples of the form (LIST, package_id, id,).
        """
        assert _DF or not isinstance(package_ids, basestring)
        assert _DF or pos is None or item is not None
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [LIST,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if item: q.add_item_filter(item, pos)
        if meta: q.add_meta_filter(meta)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_queries(self, package_ids, id=None):
        """
        Yield tuples of the form (QUERY, package_id, id, mimetype, model,
        url).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.typ, e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [QUERY,]
        )
        q.add_content_columns()
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    def iter_imports(self, package_ids,
                      id=None,
                      url=None,
                      uri=None,
                    ):
        """
        Yield tuples of the form (IMPORT, package_id, id, url, uri).
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT ?, e.package, e.id, e.url, e.uri",
            "FROM Imports e",
            args = [IMPORT,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if url: q.add_column_filter("e.url", url)
        if uri: q.add_column_filter("e.uri", uri)
        r = self._conn.execute(*q.exe())
        return _FlushableIterator(r, self)

    # element counting

    def count_medias(self, package_ids,
                    id=None,
                    url=None,
                    foref=None,
                   ):
        """
        Count the medias matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Medias e",
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if url: q.add_column_filter("e.url", url)
        if foref: q.add_column_filter("e.foref", foref)
        q.wrap_in_count()

        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_annotations(self, package_ids,
                         id=None,
                         media=None,
                         begin=None, begin_min=None, begin_max=None,
                         end=None,   end_min=None,   end_max=None,
                        ):
        """
        Return the number of annotations matching the criteria.

        ``media`` is the uri-ref of a media or an iterable of uri-refs.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Annotations e",
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if media: q.add_media_filter(media)
        if begin: q.append(" AND e.fbegin = ?", begin)
        if begin_min: q.append(" AND e.fbegin >= ?", begin_min)
        if begin_max: q.append(" AND e.fbegin <= ?", begin_max)
        if end: q.append(" AND e.fend = ?", end)
        if end_min: q.append(" AND e.fend >= ?", end_min)
        if end_max: q.append(" AND e.fend <= ?", end_max)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_relations(self, package_ids, id=None, member=None, pos=None):
        """
        Return the number of relations matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        assert _DF or pos is None or member is not None
        if member is None:
            q = _Query(
                "SELECT e.package, e.id",
                "FROM Elements e",
                "WHERE e.typ = ?",
                args = [RELATION,]
            )
        else:
            m_u, m_i = _split_uri_ref(member)

            #q = _Query(
            #    "SELECT DISTINCT rm.package, rm.relation",
            #    "FROM RelationMembers rm "
            #    "JOIN UriBases u ON u.package = rm.package "
            #                    "AND u.prefix = rm.member_p",
            #    "WHERE u.uri_base = ? AND rm.member_i = ?",
            #    [m_u, m_i],
            #    pid = "rm.package", eid = "rm.relation"
            #)

            # since UriBases (above) hinders efficiency, replace with:
            q = _Query(
                "SELECT DISTINCT rm.package, rm.relation",
                "FROM RelationMembers rm "
                "JOIN Packages p ON p.id = rm.package "
                "LEFT JOIN Imports i ON i.package = rm.package "
                                    "AND i.id = rm.member_p",
                "WHERE rm.member_i = ? "
                "AND ("
                 "(member_p = '' AND (p.uri = '' AND ? = p.url OR ? = p.uri))"
                 " OR "
                 "(member_p = i.id AND (i.uri = '' AND ? = i.url OR ? = i.uri))"
                ")",
                [m_i, m_u, m_u, m_u, m_u],
                pid = "rm.package", eid = "rm.relation"
            )
            if pos is not None: q.append(" AND rm.ord = ?", pos)
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_views(self, package_ids, id=None):
        """
        Return the number of views matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [VIEW,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_resources(self, package_ids, id=None):
        """
        Return the number of resources matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [RESOURCE,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_tags(self, package_ids, id=None, meta=None):
        """
        Return the number of tags matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [TAG,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if meta: q.add_meta_filter(meta)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_lists(self, package_ids, id=None, item=None, pos=None, meta=None):
        """
        Return the number of lists matching the criteria.
        """
        assert _DF or not isinstance(package_ids, basestring)
        assert _DF or pos is None or item is not None
        if item is None:
            q = _Query(
                "SELECT e.package, e.id",
                "FROM Elements e",
                "WHERE e.typ = ?",
                args = [LIST,]
            )
        else:
            i_u, i_i = _split_uri_ref(item)
            q = _Query(
                "SELECT DISTINCT li.package, li.list",
                "FROM ListItems li "
                "JOIN UriBases u ON u.package = li.package "
                                "AND u.prefix = li.item_p",
                "WHERE u.uri_base = ? AND li.item_i = ?",
                [i_u, i_i],
                pid = "li.package", eid = "li.list"
            )
            if pos is not None: q.append(" AND li.ord = ?", pos)
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if meta: q.add_meta_filter(meta)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_queries(self, package_ids, id=None):
        """
        Return the number of querties matching the criteria.
        """
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Elements e",
            "WHERE e.typ = ?",
            args = [QUERY,]
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    def count_imports(self, package_ids,
                     id=None,
                     url=None,
                     uri=None
                    ):
        """
        Return the number of imports matching the criteria.
        """
        q = _Query(
            "SELECT e.package, e.id",
            "FROM Imports e",
        )
        q.add_packages_filter(package_ids)
        if id: q.add_id_filter(id)
        if url: q.add_column_filter("e.url", url)
        if uri: q.add_column_filter("e.uri", uri)
        q.wrap_in_count()
        r = self._conn.execute(*q.exe())
        return r.next()[0]

    # element updating

    def update_media(self, package_id, id, url, frame_of_reference):
        assert _DF or self.has_element(package_id, id, MEDIA)
        execute = self._curs.execute
        try:
            execute("UPDATE Medias SET url = ?, foref = ? "
                     "WHERE package = ? AND id = ?",
                    (url, frame_of_reference, package_id, id,))
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def update_annotation(self, package_id, id, media, begin, end):
        """
        ``media`` is the id-ref of an own or directly imported media.
        """
        assert _DF or self.has_element(package_id, id, ANNOTATION)
        assert _DF or isinstance(begin, (int, long)) and begin >= 0, begin

        p,s = _split_id_ref(media) # also assert that media has depth < 2
        assert _DF or p == "" or self.has_element(package_id, p, IMPORT), p
        assert _DF or p != "" or self.has_element(package_id, s, MEDIA), s

        execute = self._curs.execute
        try:
            execute("UPDATE Annotations SET media_p = ?, "
                     "media_i = ?, fbegin = ?, fend = ? "
                     "WHERE package = ? and id = ?",
                    (p, s, begin, end, package_id, id,))
        except sqlite.Error, e:
            self._conn.rollback()
            raise InternalError("could not update", e)
        except:
            self._conn.rollback()
            raise

    def update_import(self, package_id, id, url, uri):
        assert _DF or self.has_element(package_id, id, IMPORT)
        execute = self._curs.execute
        try:
            execute("UPDATE Imports SET url = ?, uri = ? "
                     "WHERE package = ? and id = ?",
                    (url, uri, package_id, id,))
        except sqlite.Error, e:
            self._conn.rollback()
            raise InternalError("error in updating", e)
        except:
            self._conn.rollback()
            raise

    # element renaming

    def rename_element(self, package_id, old_id, element_type, new_id):
        """Rename an own elemenent of package_id.

        NB: element_type must be provided and must be the type constant of the
        identified element, or the behaviour of this method is unspecified.

        NB: This does not update references to that element. For that, you must
        also use `rename_references`. This however does update the id-ref of
        imported elements if the renamed element is an import.
        """
        assert _DF or self.has_element(package_id, old_id, element_type)
        assert _DF or not self.has_element(package_id, new_id)

        # NB: all the queries after the first one (and hence the transaction)
        # are only required because sqlite does not implement foreign keys;
        # with an "ON UPDATE CASCADE", the renaming in Elements would suffice.

        self._begin_transaction("IMMEDIATE")
        execute = self._curs.execute
        args = (new_id, package_id, old_id)
        try:
            execute("UPDATE Elements SET id = ? WHERE package = ? AND id = ?",
                    args)
            if element_type in (ANNOTATION, RELATION, VIEW, RESOURCE, QUERY):
                execute("UPDATE Contents SET element = ? " \
                         "WHERE package = ? AND element = ?",
                        args)

            if element_type == MEDIA:
                execute("UPDATE Medias SET id = ? "\
                         "WHERE package = ? AND id = ?",
                        args)
            elif element_type == ANNOTATION:
                execute("UPDATE Annotations SET id = ? "\
                         "WHERE package = ? AND id = ?",
                        args)
            elif element_type == RELATION:
                execute("UPDATE RelationMembers SET relation = ? " \
                         "WHERE package = ? AND relation = ?",
                        args)
            elif element_type == LIST:
                execute("UPDATE ListItems SET list = ? " \
                         "WHERE package = ? AND list = ?",
                        args)
            elif element_type == IMPORT:
                execute("UPDATE Imports SET id = ? "\
                         "WHERE package = ? AND id = ?",
                        args)
                execute("UPDATE Contents SET model_p = ? " \
                         "WHERE package = ? AND model_p = ?",
                        args)
                execute("UPDATE Annotations SET media_p = ? " \
                         "WHERE package = ? AND media_p = ?",
                        args)
                execute("UPDATE RelationMembers SET member_p = ? " \
                         "WHERE package = ? AND member_p = ?",
                        args)
                execute("UPDATE ListItems SET item_p = ? " \
                         "WHERE package = ? AND item_p = ?",
                        args)
                execute("UPDATE Tagged SET element_p = ? " \
                         "WHERE package = ? AND element_p = ?",
                        args)
                execute("UPDATE Tagged SET tag_p = ? " \
                         "WHERE package = ? AND tag_p = ?",
                        args)
                execute("UPDATE Meta SET value_p = ? " \
                         "WHERE package = ? AND value_p = ?",
                        args)
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not update", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def rename_references(self, package_ids, old_uriref, new_id):
        """Reflect the renaming of an element in several packages.

        Apply the change of id of an element (formerly known as old_uriref)
        in all references to that element in package_ids.
        """
        assert _DF or not isinstance(package_ids, basestring)
        element_u, element_i = _split_uri_ref(old_uriref)
        args = [new_id,] + list(package_ids) + [element_i, element_u,]
        qmarks = "(" + ",".join( "?" for i in package_ids ) + ")"
        execute = self._curs.execute
        self._begin_transaction("IMMEDIATE")
        try:
            # media references
            q2 = """UPDATE Annotations SET media_i = ?
                    WHERE package IN %s
                    AND media_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = Annotations.package
                      AND prefix = media_p
                      AND uri_base = ?
                    )
                  """ % qmarks
            execute(q2, args)
            # model references
            q2 = """UPDATE Contents SET model_i = ?
                    WHERE package IN %s
                    AND model_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = Contents.package
                      AND prefix = model_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
            # member references
            q2 = """UPDATE RelationMembers SET member_i = ?
                    WHERE package IN %s
                    AND member_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = RelationMembers.package
                      AND prefix = member_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
            # item references
            q2 = """UPDATE ListItems SET item_i = ?
                    WHERE package IN %s
                    AND item_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = ListItems.package
                      AND prefix = item_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
            # tags references
            q2 = """UPDATE Tagged SET tag_i = ?
                    WHERE package IN %s
                    AND tag_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = Tagged.package
                      AND prefix = tag_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
            # tagged element references
            q2 = """UPDATE Tagged SET element_i = ?
                    WHERE package IN %s
                    AND element_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = Tagged.package
                      AND prefix = element_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
            # metadata references
            q2 = """UPDATE Meta SET value_i = ?
                    WHERE package IN %s
                    AND value_i = ?
                    AND EXISTS (
                      SELECT * FROM UriBases
                      WHERE UriBases.package = Meta.package
                      AND prefix = value_p
                      AND uri_base = ?
                    )
                 """ % qmarks
            execute(q2, args)
        except InternalError, e:#sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not update", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    # element deletion

    def delete_element(self, package_id, id, element_type):
        """Delete the identified element.

        NB: This does not delete references to that element, *even* in the same
        package. The appropriate methods (`iter_references`,
        `iter_references_with_import`) must be used to detect and delete
        those references prior to deletion.
        """
        assert _DF or self.has_element(package_id, id, element_type)

        # NB: all the queries after the first one (and hence the transaction)
        # are only required because sqlite does not implement foreign keys;
        # with an "ON DELETE CASCADE", the deletion in Elements would suffice.

        self._begin_transaction("IMMEDIATE")
        execute = self._curs.execute
        args = (package_id, id)
        try:
            execute("DELETE FROM Elements WHERE package = ? AND id = ?", args)
            if element_type in (ANNOTATION, RELATION, VIEW, RESOURCE, QUERY):
                execute("DELETE FROM Contents " \
                         "WHERE package = ? AND element = ?",
                        args)

            if element_type == MEDIA:
                execute("DELETE FROM Medias WHERE package = ? AND id = ?",
                        args)
            elif element_type == ANNOTATION:
                execute("DELETE FROM Annotations WHERE package = ? AND id = ?",
                        args)
            elif element_type == RELATION:
                execute("DELETE FROM RelationMembers " \
                         "WHERE package = ? AND relation = ?",
                        args)
            elif element_type == LIST:
                execute("DELETE FROM ListItems WHERE package = ? AND list = ?",
                        args)
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not delete", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    # content management

    def get_content_info(self, package_id, id, element_type):
        """Return information about the content of an element, or None.

        The information is a tuple of the form (mimetype, model_id, url),
        where ``model_id`` and ``url`` can be empty strings.

        None is returned if the element does not exist or has no content.

        Note that this method will not be used often since this information
        is provided by get_element for all elements having a content.
        """
        q = "SELECT mimetype, join_id_ref(model_p,model_i) as model, url " \
            "FROM Contents " \
            "WHERE package = ? AND element = ?"
        return self._curs.execute(q, (package_id, id,)).fetchone() or None

    def update_content_info(self, package_id, id, element_type,
                            mimetype, model, url):
        """Update the content information of the identified element.

        ``model`` is the id of an own or directly imported resource,
        or an empty string to specify no model (not None).

        If ``url`` is not an empty string, any data stored in the backend for
        this content will be discarded.
        """
        assert _DF or self.has_element(package_id, id, element_type)
        assert _DF or element_type in (ANNOTATION,RELATION,VIEW,QUERY,RESOURCE)
        if model:
            p,s = _split_id_ref(model) # also assert that model has depth < 2
            assert _DF or p == "" or self.has_element(package_id,p,IMPORT), p
            assert _DF or p != "" or s == "" or \
                   self.has_element(package_id, s, RESOURCE), s
        else:
            p,s = "",""

        q = "UPDATE Contents "\
            "SET mimetype = ?, model_p = ?, model_i = ?, url = ?%s "\
            "WHERE package = ? AND element = ?"
        args = [mimetype, p, s, url, package_id, id,]
        if url:
            q %= ", data = ?"
            args[4:4] = ["",]
        else:
            q %= ""
        execute = self._curs.execute
        try:
            execute(q, args)
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def get_content_data(self, package_id, id, element_type):
        """Return the stored data, as a string, of the content of an element.

        This method will return an empty string if the content is externally
        stored (non-empty ``url`` attribute).
        """
        assert _DF or self.has_element(package_id, id, element_type)
        assert _DF or element_type in (ANNOTATION,RELATION,VIEW,QUERY,RESOURCE)
        q = "SELECT data FROM Contents WHERE package = ? AND element = ?"
        return self._curs.execute(q, (package_id, id,)).fetchone()[0]

    def update_content_data(self, package_id, id, element_type, data):
        """Update the content data of the identified element.

        If `data` is not an empty string, the ``url`` attribute of the content
        will be cleared.
        """
        assert _DF or self.has_element(package_id, id, element_type)
        assert _DF or element_type in (ANNOTATION,RELATION,VIEW,QUERY,RESOURCE)
        q = "UPDATE Contents SET data = ?%s WHERE package = ? AND element = ?"
        args = [data, package_id, id,]
        if data:
            q %= ", url = ?"
            args[1:1] = ["",]
        else:
            q %= ""
        execute = self._curs.execute
        try:
            execute(q, args)
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def iter_contents_with_model(self, package_ids, model):
        """
        Return tuples of the form (package_id, id) of all the
        elements with a content having the given model.

        @param model the uri-ref of a resource
        """
        assert _DF or not isinstance(package_ids, basestring)

        model_u, model_i = _split_uri_ref(model)

        q = "SELECT c.package, c.element FROM Contents c " \
            "JOIN Packages p ON c.package = p.id "\
            "LEFT JOIN Imports i ON c.model_p = i.id " \
            "WHERE c.package IN (" \
            + ",".join( "?" for i in package_ids ) + ")" \
            " AND model_i = ? AND ("\
            "  (model_p = ''   AND  ? IN (p.uri, p.url)) OR " \
            "  (model_p = i.id AND  ? IN (i.uri, i.url)))"
        args =  list(package_ids) + [model_i, model_u, model_u,]
        r = self._conn.execute(q, args)
        return _FlushableIterator(r, self)

    # meta-data management

    def iter_meta(self, package_id, id, element_type):
        """Iter over the metadata, sorting keys in alphabetical order.

        Yield tuples of the form (key, val, val_is_id) (cf. `get_meta` and
        `set_meta`).

        If package metadata is targeted, id should be an empty string (in
        that case, element_type will be ignored).
        """
        assert _DF or id == "" or self.has_element(package_id, id, element_type)
        q = """SELECT key, value, value_p, value_i FROM Meta
               WHERE package = ? AND element = ? ORDER BY key"""
        r = ( (d[0],
               d[2] and "%s:%s" % (d[2], d[3]) or d[3] or d[1],
               d[3] != "",
              ) for d in self._conn.execute(q, (package_id, id)) )
        return _FlushableIterator(r, self)

    def get_meta(self, package_id, id, element_type, key):
        """Return the given metadata of the identified element.

        Return a tuple of the form (val, val_is_id) where the second item is
        a boolean, indicating whether the first item must be interpreted as an
        id-ref, or None if the element has no metadata with that key.

        If package metadata is targeted, id should be an empty string (in
        that case, element_type will be ignored).
        """
        assert _DF or id == "" or self.has_element(package_id, id, element_type)
        q = """SELECT value, value_p, value_i FROM Meta
               WHERE package = ? AND element = ? AND KEY = ?"""
        d = self._curs.execute(q, (package_id, id, key,)).fetchone()
        if d is None:
            return None
        elif d[2]:
            return (d[1] and "%s:%s" % (d[1], d[2]) or d[2], True)
        else:
            return (d[0], False)

    def set_meta(self, package_id, id, element_type, key, val, val_is_id):
        """Set the given metadata of the identified element.

        Parameter ``val_is_id`` indicates whether parameter ``val`` must be
        interpreted as an id-ref rather than a plain string. Note that ``val`` 
        can also be None to unset the corresponding metadata; in that case,
        val_is_id is ignored.

        If package metadata is targeted, id should be an empty string (in
        that case, element_type will be ignored).
        """
        assert _DF or id == "" or self.has_element(package_id, id, element_type)

        if val is not None and val_is_id:
            val_p, val_i = _split_id_ref(val)
            val = ""
        else:
            val_p = ""
            val_i = ""

        q = """SELECT value FROM Meta
               WHERE package = ? AND element = ? and key = ?"""
        c = self._curs.execute(q, (package_id, id, key))
        d = c.fetchone()

        if d is None:
            if val is not None:
                q = """INSERT INTO Meta
                       VALUES (?,?,?,?,?,?)"""
                args = (package_id, id, key, val, val_p, val_i)
            else:
                q = ""
        else:
            if val is not None:
                q = """UPDATE Meta SET value = ?, value_p = ?, value_i = ?
                       WHERE package = ? AND element = ? AND key = ?"""
                args = (val, val_p, val_i, package_id, id, key)
            else:
                q = """DELETE FROM Meta
                       WHERE package = ? AND element = ? AND key = ?"""
                args = (package_id, id, key)
        if q:
            execute = self._curs.execute
            try:
                execute(q, args)
            except sqlite.Error, e:
                raise InternalError("could not %s" % q[:6], e)

    def iter_meta_refs(self, package_ids, uriref, element_type):
        """
        Iter over the metadata whose value is a reference to the element
        identified by uriref.

        The returned iterator yields triples of the form
        (package_id, element_id, metadata_key) where element_id is the empty
        string for package metadata.d
        """
        # TODO may be deprecated
        assert _DF or not isinstance(package_ids, basestring)
        element_u, element_i = _split_uri_ref(uriref)
        q1 = "SELECT p.id || ' ' || i.id " \
             "FROM Packages p JOIN Imports i ON p.id = i.package " \
             "WHERE ? IN (i.uri, i.url) " \
             "UNION " \
             "SELECT p.id || ' ' FROM Packages p " \
             "WHERE ? IN (p.uri, p.url)"
        # The query above selects all pairs package_id/import_id (where the
        # second can be "") matching the URI prefix of old_uriref.
        # It can then be used to know detect id-refs to update.
        # (see also rename_references)
        q2 = "SELECT package, element, key " \
             "FROM Meta " \
             "WHERE package IN (" \
               + ",".join( "?" for i in package_ids ) + ")" \
               "AND value_i = ? " \
               "AND package || ' ' || value_p IN (%s)" % q1
        args = list(package_ids) \
             + [element_i, element_u, element_u,]
        r = self._conn.execute(q2, args)
        return _FlushableIterator(r, self)

    # relation members management

    def insert_member(self, package_id, id, member, pos, n=-1):
        """
        Insert a member at the given position.
        ``member`` is the id-ref of an own or directly imported member.
        ``pos`` may be any value between -1 and n (inclusive), where n is the
        current number of members.
        If -1, the member will be appended at the end (**note** that this is
        not the same behaviour as ``list.insert`` in python2.5).
        If non-negative, the member will be inserted at that position.

        NB: the total number of members, n, if known, may be provided, as an
        optimization.
        """
        assert _DF or self.has_element(package_id, id, RELATION)
        if n < 0:
            n = self.count_members(package_id, id)
        assert _DF or -1 <= pos <= n, pos
        p,s = _split_id_ref(member) # also assert that member has depth < 2
        assert _DF or p == "" or self.has_element(package_id, p, IMPORT), p
        assert _DF or p != "" or self.has_element(package_id, s, ANNOTATION), s
        if pos == -1:
            pos = n
        execute = self._curs.execute
        executemany = self._curs.executemany
        updates = ((package_id, id, i) for i in xrange(n, pos-1, -1))
        self._begin_transaction()
        try:
            # sqlite does not seem to be able to do the following updates in
            # one query (unicity constraint breaks), so...
            executemany("UPDATE RelationMembers SET ord=ord+1 "
                         "WHERE package = ? AND relation = ? AND ord = ?",
                        updates)
            execute("INSERT INTO RelationMembers VALUES (?,?,?,?,?)",
                    (package_id, id, pos, p, s))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not update or insert", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def update_member(self, package_id, id, member, pos):
        """
        Remobv the member at the given position in the identified relation.
        ``member`` is the id-ref of an own or directly imported member.
        """
        assert _DF or self.has_element(package_id, id, RELATION)
        assert _DF or 0 <= pos < self.count_members(package_id, id), pos

        p,s = _split_id_ref(member) # also assert that member has depth < 2
        assert _DF or p == "" or self.has_element(package_id, p, IMPORT), p
        assert _DF or p != "" or self.has_element(package_id, s, ANNOTATION), s

        execute = self._curs.execute
        try:
            execute("UPDATE RelationMembers SET member_p = ?, member_i = ? "
                     "WHERE package = ? AND relation = ? AND ord = ?",
                    (p, s, package_id, id, pos))
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def count_members(self, package_id, id):
        """
        Count the members of the identified relations.

        This should return 0 if the relation does not exist.
        """
        q = "SELECT count(ord) FROM RelationMembers "\
            "WHERE package = ? AND relation = ?"
        return self._curs.execute(q, (package_id, id)).fetchone()[0]

    def get_member(self, package_id, id, pos, n=-1):
        """
        Return the id-ref of the member at the given position in the identified
        relation.

        NB: the total number of members, n, if known, may be provided, as an
        optimization.
        """
        assert _DF or self.has_element(package_id, id, RELATION)
        if __debug__:
            n = self.count_members(package_id, id)
            assert _DF or -n <= pos < n, pos

        if pos < 0:
            if n < 0:
                n = self.count_members(package_id, id)
            pos += n

        q = "SELECT join_id_ref(member_p,member_i) AS member " \
            "FROM RelationMembers "\
            "WHERE package = ? AND relation = ? AND ord = ?"
        return self._curs.execute(q, (package_id, id, pos)).fetchone()[0]

    def iter_members(self, package_id, id):
        """
        Iter over all the members of the identified relation.
        """
        assert _DF or self.has_element(package_id, id, RELATION)
        q = "SELECT join_id_ref(member_p,member_i) AS member " \
            "FROM RelationMembers " \
            "WHERE package = ? AND relation = ? ORDER BY ord"
        r = ( i[0] for i in self._conn.execute(q, (package_id, id)) )
        return _FlushableIterator(r, self)

    def remove_member(self, package_id, id, pos):
        """
        Remove the member at the given position in the identified relation.
        """
        assert _DF or self.has_element(package_id, id, RELATION)
        assert _DF or 0 <= pos < self.count_members(package_id, id), pos

        execute = self._curs.execute
        self._begin_transaction()
        try:
            execute("DELETE FROM RelationMembers "
                     "WHERE package = ? AND relation = ? AND ord = ?",
                    (package_id, id, pos))
            # We must now decrease all 'ord' above the one we just deleted.
            # This could be done by:
            #   execute("UPDATE RelationMembers SET ord=ord-1 "
            #           "WHERE package = ? AND relation = ? AND ord > ?",
            #           (package_id, id, pos))
            # but this may lead to temporary inconsistency (duplicate PK).
            # Since sqlite chokes on it, and does not allow 'ORDER BY' in
            # an UPDATE query, we first set the to-be-modified 'ord' to a
            # negative value (which is not formally forbidden by the schema)
            # and then convert it back to a modified positive value.
            execute("UPDATE RelationMembers SET ord=-ord "
                    "WHERE package = ? AND relation = ? AND ord > ?",
                    (package_id, id, pos))
            execute("UPDATE RelationMembers SET ord=-ord-1 "
                    "WHERE package = ? AND relation = ? AND ord < 0",
                    (package_id, id))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not delete or update", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    # list items management

    def insert_item(self, package_id, id, item, pos, n=-1):
        """
        Insert an item at the given position.
        ``item`` is the id-ref of an own or directly imported item.
        ``pos`` may be any value between -1 and n (inclusive), where n is the
        current number of items.
        If -1, the item will be appended at the end (**note** that this is
        not the same behaviour as ``list.insert`` in python2.5).
        If non-negative, the item will be inserted at that position.

        NB: the total number of members, n, if known, may be provided, as an
        optimization.
        """
        assert _DF or self.has_element(package_id, id, LIST)
        if n < 0:
            n = self.count_items(package_id, id)
        assert _DF or -1 <= pos <= n, pos
        p,s = _split_id_ref(item) # also assert that item has depth < 2
        assert _DF or p == "" or self.has_element(package_id, p, IMPORT), p
        assert _DF or p != "" or self.has_element(package_id, s), item
        if pos == -1:
            pos = n
        execute = self._curs.execute
        executemany = self._curs.executemany
        updates = ((package_id, id, i) for i in xrange(n, pos-1, -1))
        self._begin_transaction()
        try:
            # sqlite does not seem to be able to do the following updates in
            # one query (unicity constraint breaks), so...
            executemany("UPDATE ListItems SET ord=ord+1 "
                           "WHERE package = ? AND list = ? AND ord = ?",
                        updates)
            execute("INSERT INTO ListItems VALUES (?,?,?,?,?)",
                    (package_id, id, pos, p, s))
        except sqlite.Error, e:
            execute("ROLLBACK")
            raise InternalError("could not update or insert", e)
        except:
            execute("ROLLBACK")
            raise
        execute("COMMIT")

    def update_item(self, package_id, id, item, pos):
        """
        Remobv the item at the given position in the identified list.
        ``item`` is the id-ref of an own or directly imported item.
        """
        assert _DF or self.has_element(package_id, id, LIST)
        assert _DF or 0 <= pos < self.count_items(package_id, id), pos

        p,s = _split_id_ref(item) # also assert that item has depth < 2
        assert _DF or p == "" or self.has_element(package_id, p, IMPORT), p
        assert _DF or p != "" or self.has_element(package_id, s), s

        execute = self._curs.execute
        try:
            execute("UPDATE ListItems SET item_p = ?, item_i = ? "
                       "WHERE package = ? AND list = ? AND ord = ?",
                      (p, s, package_id, id, pos))
        except sqlite.Error, e:
            raise InternalError("could not update", e)

    def count_items(self, package_id, id):
        """
        Count the items of the identified lists.

        This should return 0 if the list does not exist.
        """
        q = "SELECT count(ord) FROM ListItems "\
            "WHERE package = ? AND list = ?"
        return self._curs.execute(q, (package_id, id)).fetchone()[0]

    def get_item(self, package_id, id, pos, n=-1):
        """
        Return the id-ref of the item at the given position in the identified
        list.

        NB: the total number of members, n, if known, may be provided, as an
        optimization.
        """
        assert _DF or self.has_element(package_id, id, LIST)
        if __debug__:
            n = self.count_items(package_id, id)
            assert _DF or -n <= pos < n, pos

        if pos < 0:
            if n < 0:
                n = self.count_items(package_id, id)
            pos += n

        q = "SELECT join_id_ref(item_p,item_i) AS item " \
            "FROM ListItems "\
            "WHERE package = ? AND list = ? AND ord = ?"
        return self._curs.execute(q, (package_id, id, pos)).fetchone()[0]

    def iter_items(self, package_id, id):
        """
        Iter over all the items of the identified list.
        """
        assert _DF or self.has_element(package_id, id, LIST)
        q = "SELECT join_id_ref(item_p,item_i) AS item " \
            "FROM ListItems " \
            "WHERE package = ? AND list = ? ORDER BY ord"
        r = ( i[0] for i in self._conn.execute(q, (package_id, id)) )
        return _FlushableIterator(r, self)

    def remove_item(self, package_id, id, pos):
        """
        Remove the item at the given position in the identified list.
        """
        assert _DF or self.has_element(package_id, id, LIST)
        assert _DF or 0 <= pos < self.count_items(package_id, id), pos

        execute = self._curs.execute
        self._begin_transaction()
        try:
            execute("DELETE FROM ListItems "
                     "WHERE package = ? AND list = ? AND ord = ?",
                    (package_id, id, pos))
            # We must now decrease all 'ord' above the one we just deleted.
            # This could be done by:
            #   execute("UPDATE ListItems SET ord=ord-1 "
            #            "WHERE package = ? AND list = ? AND ord > ?",
            #           (package_id, id, pos))
            # but this may lead to temporary inconsistency (duplicate PK).
            # Since sqlite chokes on it, and does not allow 'ORDER BY' in
            # an UPDATE query, we first set the to-be-modified 'ord' to a
            # negative value (which is not formally forbidden by the schema)
            # and then convert it back to a modified positive value.
            execute("UPDATE ListItems SET ord=-ord "
                     "WHERE package = ? AND list = ? AND ord > ?",
                    (package_id, id, pos))
            execute("UPDATE ListItems SET ord=-ord-1 "
                     "WHERE package = ? AND list = ? AND ord < 0",
                    (package_id, id))
        except sqlite.Error, e:
            execute("ROLLBACK")
            self._conn.rollback()
            raise InternalError("could not delete or update", e)
        except:
            execute("ROLLBACK")
            self._conn.rollback()
            raise
        execute("COMMIT")

    # tagged elements management

    def associate_tag(self, package_id, element, tag):
        """Associate a tag to an element.

        @param element the id-ref of an own or directly imported element
        @param tag the id-ref of an own or directly imported tag
        """
        ep, es = _split_id_ref(element) # also assert that it has depth < 2
        assert _DF or ep == "" or self.has_element(package_id, ep, IMPORT), ep
        assert _DF or ep != "" or self.has_element(package_id, es), es
        tp, ts = _split_id_ref(tag) # also assert that tag has depth < 2
        assert _DF or tp == "" or self.has_element(package_id, tp, IMPORT), tp
        assert _DF or tp != "" or self.has_element(package_id, ts, TAG), ts

        execute = self._curs.execute
        try:
            execute("INSERT OR IGNORE INTO Tagged VALUES (?,?,?,?,?)",
                    (package_id, ep, es, tp, ts))
        except sqlite.Error, e:
            raise InternalError("could not insert", e)

    def dissociate_tag(self, package_id, element, tag):
        """Dissociate a tag from an element.

        @param element the id-ref of an own or directly imported element
        @param tag the id-ref of an own or directly imported tag
        """
        ep, es = _split_id_ref(element) # also assert that it has depth < 2
        assert _DF or ep == "" or self.has_element(package_id, ep, IMPORT), ep
        assert _DF or ep != "" or self.has_element(package_id, es), es
        tp, ts = _split_id_ref(tag) # also assert that tag has depth < 2
        assert _DF or tp == "" or self.has_element(package_id, tp, IMPORT), tp
        assert _DF or tp != "" or self.has_element(package_id, ts, TAG), ts

        execute = self._curs.execute
        try:
            execute("DELETE FROM Tagged WHERE package = ? "
                     "AND element_p = ? AND element_i = ? "
                     "AND tag_p = ? AND tag_i = ?",
                    (package_id, ep, es, tp, ts))
        except sqlite.Error, e:
            raise InternalError("could not delete", e)

    def iter_tags_with_element(self, package_ids, element):
        """Iter over all the tags associated to element in the given packages.

        @param element the uri-ref of an element
        """
        assert _DF or not isinstance(package_ids, basestring)

        element_u, element_i = _split_uri_ref(element)
        q = "SELECT t.package, join_id_ref(tag_p, tag_i) " \
            "FROM Tagged t " \
            "JOIN Packages p ON t.package = p.id " \
            "LEFT JOIN Imports i ON t.element_p = i.id " \
            "WHERE t.package IN (" \
            + ",".join( "?" for i in package_ids ) + ")" \
            " AND element_i = ? AND ("\
            "  (element_p = ''   AND  ? IN (p.uri, p.url)) OR " \
            "  (element_p = i.id AND  ? IN (i.uri, i.url)))"
        args = list(package_ids) + [element_i, element_u, element_u]

        r = self._conn.execute(q, args)
        return _FlushableIterator(r, self)

    def iter_elements_with_tag(self, package_ids, tag):
        """Iter over all the elements associated to tag in the given packages.

        @param tag the uri-ref of a tag
        """
        assert _DF or not isinstance(package_ids, basestring)

        tag_u, tag_i = _split_uri_ref(tag)
        q = "SELECT t.package, join_id_ref(element_p, element_i) " \
            "FROM Tagged t " \
            "JOIN Packages p ON t.package = p.id " \
            "LEFT JOIN Imports i ON t.tag_p = i.id " \
            "WHERE t.package IN (" \
            + ",".join( "?" for i in package_ids ) + ")" \
            " AND tag_i = ? AND ("\
            "  (tag_p = ''   AND  ? IN (p.uri, p.url)) OR " \
            "  (tag_p = i.id AND  ? IN (i.uri, i.url)))"
        args = list(package_ids) + [tag_i, tag_u, tag_u]

        r = self._conn.execute(q, args)
        return _FlushableIterator(r, self)

    def iter_taggers(self, package_ids, element, tag):
        """Iter over all the packages associating element to tag.

        @param element the uri-ref of an element
        @param tag the uri-ref of a tag
        """
        assert _DF or not isinstance(package_ids, basestring)

        element_u, element_i = _split_uri_ref(element)
        tag_u, tag_i = _split_uri_ref(tag)
        q = "SELECT t.package " \
            "FROM Tagged t " \
            "JOIN Packages p ON t.package = p.id " \
            "LEFT JOIN Imports ie ON t.element_p = ie.id " \
            "LEFT JOIN Imports it ON t.tag_p = it.id " \
            "WHERE t.package IN (" \
            + ",".join( "?" for i in package_ids ) + ")" \
            " AND element_i = ? AND ("\
            "  (element_p = ''    AND  ? IN (p.uri,  p.url)) OR " \
            "  (element_p = ie.id AND  ? IN (ie.uri, ie.url)))" \
            " AND tag_i = ? AND ("\
            "  (tag_p = ''    AND  ? IN (p.uri,  p.url)) OR " \
            "  (tag_p = it.id AND  ? IN (it.uri, it.url)))"
        args = list(package_ids) \
             + [element_i, element_u, element_u, tag_i, tag_u, tag_u,]

        r = ( i[0] for i in self._conn.execute(q, args) )
        return _FlushableIterator(r, self)

    def iter_external_tagging(self, package_id):
        """Iter over all tagging involving two imported elements.

        This is useful for serialization.
        """
        q = "SELECT join_id_ref(element_p, element_i), " \
                   "join_id_ref(tag_p, tag_i) " \
            "FROM Tagged t " \
            "WHERE t.package = ? AND element_p > '' AND tag_p > ''"
        r = self._conn.execute(q, (package_id,))
        return _FlushableIterator(r, self)


    # end of the backend interface

    def __init__(self, path, conn, force):
        """
        Is not part of the interface. Instances must be created either with
        the L{create} or the L{bind} module functions.

        Create a backend, and bind it to the given URL.
        """

        self._path = path
        self._conn = conn
        self._curs = conn.cursor()
        # NB: self._curs is to be used for any *internal* operations
        # Iterators intended for *external* use must be based on a new cursor.
        conn.create_function("join_id_ref", 2,
                              lambda p,s: p and "%s:%s" % (p,s) or s)
        conn.create_function("regexp", 2,
                              lambda r,l: re.search(r,l) is not None )
        # NB: for a reason I don't know, the defined function regexp
        # receives the righthand operand first, then the lefthand operand...
        # hence the lambda function above
        self._bound = WeakValueDictWithCallback(self._check_unused)
        # NB: the callback ensures that even if packages "forget" to close
        # themselves, once they are garbage collected, we check if the
        # connexion to sqlite can be closed.
        self._iterators = WeakKeyDictionary()
        # _iterators is used to store all the iterators returned by iter_*
        # methods, and force them to flush their underlying cursor anytime
        # an modification of the database is about to happen

    def _bind(self, package_id, package):
        d = self._bound
        old = d.get(package_id)
        if old is not None:
            raise PackageInUse(old)
        try:
            self._curs.execute("UPDATE Packages SET url = ? WHERE id = ?",
                               (package.url, package_id,))
        except sqlite.Error, e:
            raise InternalError("could not update", e)
        d[package_id] = package

    def _check_unused(self, package_id):
        conn = self._conn
        if conn is not None and len(self._bound) == 0:
            #print "DEBUG:", __file__, \
            #      "about to close SqliteBackend", self._path
            try:
                self._curs.execute("UPDATE Packages SET url = ?", ("",))
            finally:
                conn.close()
            self._conn = None
            self._curs = None
            # the following is necessary to break a cyclic reference:
            # self._bound references self._check_unused, which, as a bound
            # method, references self
            self._bound = None
            # the following is not stricly necessary, but does no harm ;)
            if self._path in _cache: del _cache[self._path]

    def _begin_transaction(self, mode=""):
        """Begin a transaction.

        This method must *always* be used to begin a transaction (do *not* use
        `self._curs.execute("BEGIN")` directly. See `_FlushableIterator` .
        """
        for i in self._iterators.iterkeys():
            i.flush()
        self._curs.execute("BEGIN %s" % mode)

    def _create_element(self, execute, package_id, id, element_type):
        """Perform controls and insertions common to all elements.

        NB: This starts a transaction that must be commited by caller.
        """
        # check that the id is not in use
        self._begin_transaction("IMMEDIATE")
        c = execute("SELECT id FROM Elements WHERE package = ? AND id = ?",
                    (package_id, id,))
        if c.fetchone() is not None:
            raise ModelError("id in use: %s" % id)
        execute("INSERT INTO Elements VALUES (?,?,?)",
                (package_id, id, element_type))


class _FlushableIterator(object):
    """Cursor based iterator that may flush the cursor whenever needed.

       Transactions to the database cannot be commited while a cursor is
       being used. So it is unsafe for _SqliteBackend to return cursors direcly
       because it may hinder further execution of methods using transactions.

       On the other hand, it may be inefficient to flush all cursors into lists
       before returning them. This class provides an efficient solution.

       All cursors (or cursor based iterators) are wrapped info a
       _FlushableIterator before being returned, and the latter is weakly
       referenced by the backend instance. Whenever a transaction is started,
       all known _FlushableIterators are flushed, i.e. they internally change
       their underlying iterator into a list, so that the transaction can be
       committed, but users can continue to transparently use them.

       Note that this implementation uses the iterable interface of sqlite
       cursors rather than the DB-API cursor interface. This is less portable,
       but allows to wrap iterators that are not cursors but relying on a
       cursor, e.g.:::

           return _FlusableIterator(( r[1] for r in conn.execute(query) ), be)
    """
    __slots__ = ["_cursor", "__weakref__",]
    def __init__ (self, cursor, backend):
        self._cursor = cursor
        backend._iterators[self] = True
    def __iter__ (self):
        return self
    def flush(self):
        """Flush the underlying cursor."""
        self._cursor = iter(list(self._cursor))
    def next(self):
        return self._cursor.next()

# NB: the wrapping of cursors into _FlushableIterators could be implemented
# as a decorator on all iter_* functions. However
#  - "classical" (i.e. wrapping) decorators have a high overhead
#  - "smart" (i.e. code-modifying) decorators are hard to write
# so for the moment, we opt for old-school copy/paste...

class _Query(object):
    """
    I provide useful functionalities for building SQL queries to the backend
    schema.
    """

    def __init__(self, select, from_, where="WHERE 1", args=(),
                 pid="e.package", eid="e.id"):
        self.s = select
        self.f = from_
        self.w = where
        self.a = list(args)
        self.pid = pid
        self.eid = eid

    def add_package_filter(self, pid):
        self.w += " AND %(pid)s = ?" % self.__dict__
        self.a.append(pid)

    def add_packages_filter(self, pids):
        self.w += " AND %(pid)s IN (%%s)" % self.__dict__
        self.w %= ",".join( "?" for i in pids )
        self.a.extend(pids)

    def add_id_filter(self, id):
        assert id is not None
        if isinstance(id, basestring):
            self.w += " AND %(eid)s = ?" % self.__dict__
            self.a.append(id)
        else:
            self.w += " AND %(eid)s IN (%%s)" % self.__dict__
            self.w %= ",".join( "?" for i in id )
            self.a.extend(id)

    def add_column_filter(self, column, value):
        assert value is not None
        if isinstance(value, basestring):
            self.w += " AND %s = ?" % (column,)
            self.a.append(value)
        else:
            self.w += " AND %s IN (%%s)" % (column,)
            self.w %= ",".join( "?" for i in value )
            self.a.extend(value)

    def add_content_columns(self):
        self.s += ", c.mimetype, join_id_ref(c.model_p, c.model_i), c.url"
        self.f += " JOIN Contents c"\
                  " ON %(pid)s = c.package AND %(eid)s = c.element"\
                  % self.__dict__

    def add_media_filter(self, media):
        if isinstance(media, basestring):
            media = (media,)
        media = [ _split_uri_ref(m) for m in media ]
        n = len(media)
        self.f += " JOIN UriBases mu ON mu.package = %(pid)s "\
                                   "AND mu.prefix = media_p"\
                  % self.__dict__
        self.w += " AND (%s)"\
                  % " OR ".join(n*["mu.uri_base = ? AND media_i = ?"])
        self.a.extend(sum(media, ()))

    def add_member_filter(self, member, ord=None):
            m_u, m_i = _split_uri_ref(member)
            self.w += " AND EXISTS ("\
                          "SELECT m.relation FROM RelationMembers m "\
                          "JOIN UriBases u ON m.package = u.package "\
                                          "AND m.member_p = u.prefix "\
                          "WHERE m.package = %(pid)s "\
                          "AND m.relation = %(eid)s "\
                          "AND u.uri_base = ? AND m.member_i = ?"\
                      ")" % self.__dict__
            self.a.extend([m_u, m_i])
            if ord is not None:
                self.w = self.w[:-1] + " AND m.ord = ?)"
                self.a.append(ord)

    def add_item_filter(self, item, ord=None):
            i_u, i_i = _split_uri_ref(item)
            self.w += " AND EXISTS ("\
                          "SELECT i.list FROM ListItems i "\
                          "JOIN UriBases u ON i.package = u.package "\
                                          "AND i.item_p = u.prefix "\
                          "WHERE i.package = %(pid)s "\
                          "AND i.list = %(eid)s "\
                          "AND u.uri_base = ? AND i.item_i = ?"\
                      ")" % self.__dict__
            self.a.extend([i_u, i_i])
            if ord is not None:
                self.w = self.w[:-1] + " AND i.ord = ?)"
                self.a.append(ord)

    def add_meta_filter(self, meta):
        """
        The meta parameter, is an iterable of triples of the form
        (key, value, uriref_flag). If uriref_flag is false, the value is
        interpreted as a string; if it is true, the value is interpreted as the
        uri-ref of an element. Note that value can also be None. This parameter
        is used to filter elements that have the given (key, value) pair in
        their metadata (value set to None filtering elements having no value
        for the given key).
        """
        for k,v,u in meta:
           if v is None:
               self.w += " AND NOT EXISTS ("\
                             "SELECT m.element FROM Meta m "\
                             "WHERE m.package = %(pid)s "\
                             "AND m.element = %(eid)s "\
                             "AND m.key = ?"\
                         ")" % self.__dict__
               self.a.append(k)
           elif not u:
               self.w += " AND EXISTS ("\
                             "SELECT m.element FROM Meta m "\
                             "WHERE m.package = %(pid)s "\
                             "AND m.element = %(eid)s "\
                             "AND m.key = ? AND m.value = ?"\
                         ")" % self.__dict__
               self.a.extend([k, v])
           else:
               v_u, v_i = _split_uri_ref(v)
               self.w += " AND EXISTS ("\
                            "SELECT m.element FROM Meta m "\
                            "JOIN UriBases u  ON m.package = u.package "\
                                             "AND m.value_p = u.prefix "\
                            "WHERE m.package = %(pid)s "\
                            "AND m.element = %(eid)s "\
                            "AND m.key = ? AND u.uri_base = ? "\
                            "AND m.value_i = ?"\
                        ")" % self.__dict__
               self.a.extend([k, v_u, v_i,])

    def append(self, txt, *args):
        """
        Append something at the end of the query.

        This should be used with care, and preferably just before call to exe,
        since it may break other methods (e.g. appending an ORDER BY
        statement).
        """
        self.w += txt
        self.a.extend(args)

    def wrap_in_count(self):
        q,_ = self.exe()
        self.s = "SELECT COUNT(*)"
        self.f = "FROM (%s)" % q
        self.w = "WHERE 1"

    def exe(self):
        """
        Return a list of arguments suitable to the ``execute`` methods.
        """
        #print "===", self.s, self.f, self.w, self.a
        return " ".join((self.s, self.f, self.w)), self.a

#
