"""
This file should contain unit tests for cam.package.
Specific features of cam.package must obviously be tested here.

A lot of things informally tested in test/test1-cam.py should be transposed
here.
"""
from datetime import datetime
from unittest import TestCase, main

from libadvene.model.cam.package import Package
from libadvene.util.session import session

class TestBookkeeping(TestCase):
    def setUp(self):
        session.user = "first_user"
        self.origin = datetime.now()
        self.p = Package("file:/tmp/p", create=True)

    def tearDown(self):
        self.p.close()

    def testPackageCreationMD(self):
        p = self.p
        # NB: only 10's of seconds are considered to compare dates
        assert p.creator == "first_user"
        assert p.created[:18] == self.origin.isoformat()[:18]
        assert p.contributor == "first_user"
        assert p.modified == p.created

    def testPackageModificationMD(self):
        p = self.p
        session.user = "second_user"
        p.set_meta("http://example.org/prop", "foo")
        assert p.creator == "first_user"
        assert p.created[:18] == self.origin.isoformat()[:18]
        assert p.contributor == "second_user"
        assert p.modified > p.created
        
    def testElementCreationMD(self):
        p = self.p
        session.user = "second_user"
        r_created = datetime.now()
        r = p.create_resource("r1", "text/plain")
        assert p.creator == "first_user"
        assert p.created[:18] == self.origin.isoformat()[:18]
        assert p.contributor == "second_user"
        assert p.modified[:18] == r_created.isoformat()[:18]
        assert r.creator == "second_user"
        assert r.created[:18] == r_created.isoformat()[:18]
        assert r.contributor == "second_user"
        assert r.modified == r.created

    def testElementModificationMD(self):
        p = self.p
        session.user = "second_user"
        r_created = datetime.now()
        r = p.create_resource("r1", "text/plain")
        session.user = "third_user"
        r.content_data = "bla bla bla"
        assert p.creator == "first_user"
        assert p.created[:18] == self.origin.isoformat()[:18]
        assert p.contributor == "third_user"
        assert p.modified == r.modified
        assert r.creator == "second_user"
        assert r.created[:18] == r_created.isoformat()[:18]
        assert r.contributor == "third_user"
        assert r.modified > r.created

class TestTheRest(TestCase):
    pass
    # TODO

if __name__ == "__main__":
    main()
