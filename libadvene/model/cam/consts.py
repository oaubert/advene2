from libadvene.model.consts import ADVENE_NS_PREFIX

BOOTSTRAP_URI = "http://liris.cnrs.fr/advene/cam/bootstrap"

CAM_NS_PREFIX = "%s%s" % (ADVENE_NS_PREFIX, "cinelab/0.1#")
CAMSYS_NS_PREFIX = CAM_NS_PREFIX + "system-"
CAM_XML = CAM_NS_PREFIX

# commonly used metadata

CAM_TYPE = "%stype" % CAM_NS_PREFIX
CAMSYS_TYPE = "%stype" % CAMSYS_NS_PREFIX
