from libadvene.model.consts import DC_NS_PREFIX
from libadvene.util.session import session

from datetime import datetime

def _make_bookkeeping_data():
    return datetime.now().isoformat(), session.user

CREATOR = DC_NS_PREFIX + "creator"
CREATED = DC_NS_PREFIX + "created"
CONTRIBUTOR = DC_NS_PREFIX + "contributor"
MODIFIED = DC_NS_PREFIX + "modified"

def init(package, obj):
    d,u = _make_bookkeeping_data()
    obj.enter_no_event_section(); \
        obj.set_meta(CREATOR, u); \
        obj.set_meta(CREATED, d); \
        obj.set_meta(CONTRIBUTOR, u); \
        obj.set_meta(MODIFIED, d)
    obj.exit_no_event_section()
    if obj is not package:
        package.enter_no_event_section(); \
            package.set_meta(CONTRIBUTOR, u); \
            package.set_meta(MODIFIED, d)
        package.exit_no_event_section()

def update(obj, *args):
    d,u = _make_bookkeeping_data()
    #d = "%s %s" % (d, args) # debug
    if len(args) == 2:
        # setting CONTRIBUTOR or MODIFIED should work anyway
        if args[0] == CONTRIBUTOR:
            u = args[1]
        elif args[0] == MODIFIED:
            d = args[1]
    obj.enter_no_event_section(); \
        obj.set_meta(CONTRIBUTOR, u); \
        obj.set_meta(MODIFIED, d)
    obj.exit_no_event_section()

def update_owner(obj, *args):
    d,u = _make_bookkeeping_data()
    #d = "%s %s" % (d, args) # debug
    package = obj._owner
    package.enter_no_event_section(); \
        package.set_meta(CONTRIBUTOR, u); \
        package.set_meta(MODIFIED, d)
    package.exit_no_event_section()

def update_element(obj, *args):
    #import pdb; pdb.set_trace()
    # actually a copy of both update and update_owner
    # but this is more efficient this way,
    # and since it is going to be called *many* times...
    d,u = _make_bookkeeping_data()
    package = obj._owner
    package.enter_no_event_section(); \
        package.set_meta(CONTRIBUTOR, u); \
        package.set_meta(MODIFIED, d)
    package.exit_no_event_section()
    if len(args) == 2:
        # setting CONTRIBUTOR or MODIFIED should work anyway
        if args[0] == CONTRIBUTOR:
            u = args[1]
        elif args[0] == MODIFIED:
            d = args[1]
    obj.enter_no_event_section(); \
        obj.set_meta(CONTRIBUTOR, u); \
        obj.set_meta(MODIFIED, d)
    obj.exit_no_event_section()

def iter_filtered_meta_ids(obj):
    """
    Filter the result of obj.iter_meta_ids() according to inheritance rules.

    Inheritance rules are used to limit the amount of redundant information
    in serialisations.
    """
    package = getattr(obj, "_owner", obj)
    exclude = set()
    if package is not obj:
        if obj.creator == package.creator:
            exclude.add(CREATOR)
        if obj.created == package.created:
            exclude.add(CREATED)
        if obj.contributor == obj.creator and CREATOR not in exclude \
        or obj.contributor == package.contributor and CREATOR in exclude:
            exclude.add(CONTRIBUTOR)
        if obj.modified == obj.created and CREATED not in exclude \
        or obj.modified == package.modified and CREATED in exclude:
            exclude.add(MODIFIED)
    return [ (key, val) for key, val in obj.iter_meta_ids()
             if key not in exclude ]

def inherit_bk_metadata(obj, package):
    """
    Populate missing bk metadata in obj. 
    """
    if obj is package:
        return
    creator = obj.get_meta(CREATOR, None)
    created = obj.get_meta(CREATED, None)
    if creator is None:
        obj.set_meta(CREATOR, package.creator)
    if created is None:
        obj.set_meta(CREATED, package.created)
    if obj.get_meta(CONTRIBUTOR, None) is None:
        obj.set_meta(CONTRIBUTOR, creator or package.contributor)
    if obj.get_meta(MODIFIED, None) is None:
        obj.set_meta(MODIFIED, created or package.modified)
