import os, tempfile, unittest, importlib, sys
from pathlib import Path
from fastapi.testclient import TestClient
class AgentHubTest(unittest.TestCase):
    def test_transaction_rolls_back_on_failure(self):
        """An exception must never leave a partially written transaction."""
        from importlib import import_module
        db_module = import_module('main')
        with self.assertRaises(RuntimeError):
            with db_module.conn() as connection:
                connection.execute("INSERT INTO agents(name,fallback,rules_json) VALUES ('Transient Agent','none','[]')")
                raise RuntimeError('simulate failed transaction')
        with db_module.conn() as connection:
            count = connection.execute("SELECT COUNT(*) FROM agents WHERE name LIKE 'Transient%'").fetchone()[0]
        self.assertEqual(count, 0)

    def test_csv_export_endpoint(self):
        response=self.client.get('/api/export/agents.csv')
        self.assertEqual(response.status_code,200)
        self.assertIn('text/csv',response.headers['content-type'])
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertIn('"id"',response.text)


    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        os.environ['DATABASE_PATH']=str(Path(cls.tmp.name)/'test.db')
        sys.modules.pop('main', None)
        cls.client=TestClient(importlib.import_module('main').app)
    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
    def test_rules_and_audit(self):
        a=self.client.post('/api/agents',json={'name':'Helper','fallback':'Unknown','rules':[{'keyword':'hello','response':'Hi there'}]})
        self.assertEqual(a.status_code,201)
        ident=a.json()['id']
        r=self.client.post(f'/api/agents/{ident}/run',json={'text':'HELLO world'})
        self.assertEqual(r.json()['output'],'Hi there')
        self.assertEqual(r.json()['matched_keyword'],'hello')
        self.assertEqual(len(self.client.get(f'/api/agents/{ident}/runs').json()),1)
        self.assertEqual(self.client.get('/api/agents/999999').status_code,404)
    def test_validation(self):
        self.assertEqual(self.client.post('/api/agents',json={'name':'','fallback':'x','rules':[]}).status_code,422)


    def test_preview_does_not_write_audit_history(self):
        a=self.client.post('/api/agents',json={'name':'Preview','fallback':'No match',
              'rules':[{'keyword':'query','response':'Answered'}]})
        self.assertEqual(a.status_code,201)
        ident=a.json()['id']
        before=len(self.client.get(f'/api/agents/{ident}/runs').json())
        preview=self.client.post(f'/api/agents/{ident}/preview',json={'text':'QUERY'})
        self.assertEqual(preview.status_code,200)
        self.assertEqual(preview.json()['output'],'Answered')
        self.assertFalse(preview.json()['saved_to_history'])
        self.assertEqual(before,len(self.client.get(f'/api/agents/{ident}/runs').json()))
        too_many=self.client.post('/api/agents',json={'name':'Too many','fallback':'no',
            'rules':[{'keyword':'k','response':'r'}]*101})
        self.assertEqual(too_many.status_code,422)

    def test_word_matching_prevents_partial_word_false_positive(self):
        created=self.client.post('/api/agents',json={'name':'Keyword QA','fallback':'No rule',
             'rules':[{'keyword':'ship','response':'Shipping instructions'}]})
        self.assertEqual(created.status_code,201)
        agent_id=created.json()['id']
        target=f'/api/agents/{agent_id}/preview'
        self.assertIsNone(self.client.post(target,json={'text':'a shipment'}).json()['matched_keyword'])
        self.assertEqual(self.client.post(target,json={'text':'please SHIP today'}).json()['output'],'Shipping instructions')
        self.assertEqual(self.client.post(target,json={'text':'can you help with ship?'}).json()['matched_keyword'],'ship')
