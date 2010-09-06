from libadvene.model.consts import ADVENE_NS_PREFIX
from libadvene.model.content.register import register_textual_mimetype

BOOTSTRAP_URI = "http://liris.cnrs.fr/advene/cam/bootstrap"

CAM_NS_PREFIX = "%s%s" % (ADVENE_NS_PREFIX, "cinelab/")
CAMSYS_NS_PREFIX = CAM_NS_PREFIX + "system-"
CAM_XML = CAM_NS_PREFIX

# commonly used metadata

CAM_TYPE = "%stype" % CAM_NS_PREFIX
CAMSYS_TYPE = "%stype" % CAMSYS_NS_PREFIX

register_textual_mimetype('application/x-advene-type-constraint')
