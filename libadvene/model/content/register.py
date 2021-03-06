import libadvene.model.content.avpairs as avpairs
import libadvene.model.content.json_content as json
import libadvene.model.content.values as values

# content_handler register functions

def iter_content_handlers():
    global _content_handlers
    return iter(_content_handlers)

def register_content_handler(b):
    global _content_handlers
    _content_handlers.insert(0, b)

def unregister_content_handler(b):
    global _content_handlers
    _content_handlers.remove(b)

# implementation

_content_handlers = []

# default registration

register_content_handler(avpairs)
register_content_handler(json)
register_content_handler(values)

################################################################

# textual mimetypes register function

def iter_textual_mimetypes():
    global _textual_mimetypes
    return iter(_textual_mimetypes)

def register_textual_mimetype(m):
    global _textual_mimetypes
    m = m.split("/")
    _textual_mimetypes.append(m)

def unregister_textual_mimetypes(m):
    global _textual_mimetypes
    m = m.split("/")
    _textual_mimetypes.remove(m)

# implementation

_textual_mimetypes = []

# default registration

register_textual_mimetype("application/json")
register_textual_mimetype("application/schema+json")
register_textual_mimetype("application/xml")
register_textual_mimetype("application/x-ldt-structured")
register_textual_mimetype("image/svg")
for mimetype in avpairs.MIMETYPES:
    register_textual_mimetype(mimetype)
