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
