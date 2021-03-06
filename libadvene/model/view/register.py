import libadvene.model.view.builtin as builtin
import libadvene.model.view.tal as tal
import libadvene.model.view.type_constraint as type_constraint

# view_handler register functions

def iter_view_handlers():
    global _view_handlers
    return iter(_view_handlers)

def register_view_handler(b):
    global _view_handlers
    _view_handlers.insert(0, b)

def unregister_view_handler(b):
    global _view_handlers
    _view_handlers.remove(b)

# implementation

_view_handlers = []

# default registration

register_view_handler(builtin)
register_view_handler(tal)
register_view_handler(type_constraint)
