import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('configure_acceptance',ROOT/'scripts/acceptance-configure.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DispatchTests(unittest.TestCase):
    def helper(self,temp):
        a=m.Acceptance.__new__(m.Acceptance)
        a.c={'limit':'testbox.net.krglv.com','check':True}
        a.state={};a.repo='/api/v1/repos/test/automation';a.path=Path(temp)/'request.json'
        return a
    def test_uncertain_dispatch_is_persisted_and_never_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            a=self.helper(temp)
            a.api=Mock(side_effect=[{'commit':{'id':'a'*40}},TimeoutError()])
            with self.assertRaises(TimeoutError):a.dispatch()
            self.assertEqual(json.loads(a.path.read_text())['dispatch'],'uncertain')
            with self.assertRaises(m.AcceptanceError):a.dispatch()
            self.assertEqual(a.api.call_count,2)
    def test_acceptance_scope_and_mode_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            a=self.helper(temp);a.c['limit']='all';a.api=Mock()
            with self.assertRaises(m.AcceptanceError):a.dispatch()
            a.api.assert_not_called()
            a.c['limit']='testbox.net.krglv.com';a.c['check']='false'
            with self.assertRaises(m.AcceptanceError):a.dispatch()
            a.api.assert_not_called()

class RedirectTests(unittest.TestCase):
    def test_only_same_origin_get_redirects_are_allowed(self):
        from urllib.request import Request
        handler=m.NoRedirect()
        request=Request('https://git.example.com/api/artifact')
        redirected=handler.redirect_request(request,None,302,'',{},'https://git.example.com/attachments/one')
        self.assertEqual(redirected.full_url,'https://git.example.com/attachments/one')
        with self.assertRaises(m.AcceptanceError):
            handler.redirect_request(request,None,302,'',{},'https://outside.example/artifact')
        with self.assertRaises(m.AcceptanceError):
            handler.redirect_request(Request(request.full_url,data=b'{}',method='POST'),None,302,'',{},'https://git.example.com/other')
