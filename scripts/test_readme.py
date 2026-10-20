"""Regression checks for source preservation, consolidation and safe cleanup."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

TMP=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ['KILN_DATA']=TMP.name
os.environ['KILN_DB']=str(Path(TMP.name)/'test.db')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kiln import artifacts, config, pipeline, readme, release, store, topics
if config.DATA.resolve()!=Path(TMP.name).resolve() or config.DB_PATH.resolve()!=(Path(TMP.name)/'test.db').resolve():
    raise SystemExit('Test isolation failed; refusing to touch the working library. Run this suite as its own process.')

def dossier(code='A',extra=''):
    return '# Tool '+code+'\nSource: https://www.instagram.com/reel/'+code+'/\n\n## Transcript\nCreator claim.\n\n## Setup\nRepository: github.com/example/engine\n```sh\n# code heading\nnpm install engine\n```\n\n## Prompt\nDescribe a test.\n'+extra

def fake_store(iid,path,**kwargs):
    path=Path(path)
    if kwargs.get('pdf'):
        path=path.with_suffix('.pdf');path.write_bytes(b'%PDF-test')
    return {'file':path.name,'source':path.name,'kind':path.suffix.lstrip('.'),'title':kwargs.get('title','Guide')}

class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.c=store.connect()
        for table in ('items','items_fts','tags','links','research_documents','topic_groups','match_reviews'):
            self.c.execute('DELETE FROM '+table)
        self.c.commit()
        self.fake=patch.object(artifacts,'store',side_effect=fake_store);self.fake.start()
    def tearDown(self):self.fake.stop();self.c.close()
    def stage(self,code):return readme.stage(dossier(code),code+'.md',source_id=code,conn=self.c)['id']
    def finish(self,code):
        with patch.object(topics,'check_new',return_value=[]):
            return readme.finish(code,{'answer':'Grounded guide with practical steps. '*30,'summary':'Useful summary','commands':['npm install engine']}, {'sources':[{'url':'https://example.com/docs','checked_at':'2026-10-12'}],'checked_at':'2026-10-12'},conn=self.c)
    def test_parse_fences_links_and_attribution(self):
        n=readme.parse(dossier(extra='See https://www.instagram.com/reel/Related/ later.'))
        self.assertEqual(n['source_urls'][0],'https://www.instagram.com/reel/A/')
        self.assertEqual(len(n['source_urls']),1)
        self.assertIn('https://github.com/example/engine',[l['url'] for l in n['links']])
        self.assertIn('# code heading',n['sections'][1]['detail'])
        self.assertEqual(n['spoken_transcript'],'Creator claim.')
        self.assertTrue(n['prompts'])
        self.assertEqual(readme.urls('https://gist.github.com/karpathy/abc'),['https://gist.github.com/karpathy/abc'])
    def test_owner_advice_stays_in_private_dossier(self):
        source=[{'heading':'Adapting the system for a Dec 2026 CS grad','detail':'Personal graduation and watch setup'},
                {'heading':'Actions','detail':'Use a scratch repository.\n3. Match this user\'s job watch, padel watch and trip copilot.\nKeep the generic checklist.\n### Adapting the system for a Dec 2026 CS grad\nPrivate facts\n#### Details\nMore personal facts\n### Public resources\nKeep this link.\n```text\n### Adapting the system for an example\nA code example\n```'}]
        public=readme.public_sections(source)
        self.assertEqual(len(public),1)
        self.assertNotIn('job watch',public[0]['detail'])
        self.assertIn('generic checklist',public[0]['detail'])
        self.assertNotIn('Private facts',public[0]['detail'])
        self.assertNotIn('More personal facts',public[0]['detail'])
        self.assertIn('Keep this link.',public[0]['detail'])
        self.assertIn('A code example',public[0]['detail'])
        self.assertIn('job watch',source[1]['detail'])
    def test_live_file_mismatch_cannot_issue_receipt(self):
        out=Path(TMP.name)/'release';(out/'data').mkdir(parents=True,exist_ok=True)
        snapshot={'items':[],'built':'fixture'}
        (out/'data/items.json').write_text(json.dumps(snapshot));(out/'guide.pdf').write_bytes(b'expected')
        class Response:
            def __init__(self,data):self.data=data
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return self.data
        def fetch(req,**kwargs):
            return Response(json.dumps(snapshot).encode() if '/data/items.json?' in req.full_url else b'wrong deployed bytes')
        with patch.object(release.urllib.request,'urlopen',side_effect=fetch),patch.object(readme,'mark_published') as mark:
            with self.assertRaisesRegex(ValueError,'Live file differs'):release.verify_public(out)
            mark.assert_not_called()
    def test_matcher_cannot_choose_an_unlisted_topic(self):
        from types import SimpleNamespace
        iid=self.stage('A');other=self.stage('B')
        fake=[{'id':other,'title':'Tool B','score':.4,'reason':'Overlap','auto':False}]
        with patch.object(topics,'candidates',return_value=fake),patch.object(topics.models,'generate',return_value=SimpleNamespace(ok=True,data={'candidate_id':'invented','confidence':1,'reason':'A specific but invented candidate must not be accepted'})),patch.object(topics,'consolidate') as merge:
            topics.check_new(self.c,iid);merge.assert_not_called()
    def test_exact_revision_and_idempotence(self):
        text=dossier().replace('\n','\r\n');r=readme.stage(text,'A.md',source_id='A',conn=self.c)
        d=self.c.execute('SELECT * FROM research_documents').fetchone()
        self.assertEqual(Path(d['path']).read_bytes(),text.encode())
        self.assertEqual(d['digest'],hashlib.sha256(text.encode()).hexdigest())
        self.finish('A')
        self.assertTrue(readme.stage(text,'A.md',source_id='A',conn=self.c)['unchanged'])
        changed=readme.stage(text+'New detail','A.md',source_id='A',conn=self.c)
        self.assertEqual(changed['state'],'pending')
        with self.assertRaisesRegex(ValueError,'changed during research'):
            readme.finish('A',{}, {},expected_digest=d['digest'],conn=self.c)
        self.assertEqual(store.counts(self.c)['total'],1)
    def test_failed_research_cannot_be_cleaned(self):
        self.stage('A')
        with self.assertRaises(ValueError):readme.finish('A',{'answer':'x'*600},{'sources':[]},conn=self.c)
        self.assertFalse(readme.cleanup_plan(self.c)['documents'])
        with self.assertRaises(ValueError):readme.confirm_cleanup('A',digest='bad',conn=self.c)
    def test_publication_and_changed_source_cleanup(self):
        iid=self.stage('A');self.finish('A')
        out=Path(TMP.name)/'public';(out/'data').mkdir(parents=True,exist_ok=True)
        public={'items':[{'id':iid,'followup':{'answer_html':'Guide','artifacts':[{'kind':'pdf'}]}}]}
        (out/'data'/'items.json').write_text(json.dumps(public))
        with self.assertRaises(ValueError):readme.mark_published(out,live_items={'items':[]},conn=self.c)
        self.assertEqual(readme.mark_published(out,live_items=public,conn=self.c),1)
        d=readme.cleanup_plan(self.c)['documents'][0]
        readme.INCOMING.mkdir(parents=True,exist_ok=True);p=readme.INCOMING/'A.md';p.write_text(dossier()+'changed')
        with self.assertRaisesRegex(ValueError,'changed'):readme.confirm_cleanup('A',digest=d['digest'],conn=self.c)
        self.assertTrue(p.exists());p.write_bytes(dossier().encode())
        readme.confirm_cleanup('A',digest=d['digest'],conn=self.c)
        self.assertFalse(p.exists());self.assertTrue(list(readme.KILNED.glob('*-A.md')))
        readme.confirm_cleanup('A',digest=d['digest'],conn=self.c)
    def test_merge_nested_restore_and_remerge(self):
        ids=[self.stage(code) for code in 'ABCD']
        for code in 'ABCD':self.finish(code)
        synthesis={'summary':'Unified','answer':'A coherent combined guide. '*40}
        group=topics.consolidate(self.c,ids[:2],title='Engine',synthesis=synthesis)
        self.assertEqual(len(store.list_items(self.c)),3)
        second=topics.consolidate(self.c,ids[2:],title='Engine part two',synthesis=synthesis)
        combined=topics.consolidate(self.c,[group,second],title='All engine sources',synthesis=synthesis)
        self.assertEqual(len(topics.members(self.c,combined)),4)
        self.assertEqual(store.get_item(self.c,combined)['source_count'],4)
        self.assertEqual(topics.resolve(self.c,ids[-1]),combined)
        self.assertEqual(len(store.list_items(self.c,q='Describe test')),1)
        self.assertEqual(len(store.list_items(self.c,q='""')),1)
        self.assertEqual(len(topics.split(self.c,combined)),4)
        self.assertEqual(len(store.list_items(self.c)),4)
        remerged=topics.consolidate(self.c,ids,title='Restored engine',synthesis=synthesis)
        self.assertEqual(topics.resolve(self.c,ids[0]),remerged)
        self.assertEqual(len(store.list_items(self.c)),1)
    def test_unrelated_category_does_not_auto_merge(self):
        a=self.stage('A');b=self.stage('B')
        store.upsert_item(self.c,{'id':a,'url':store.get_item(self.c,a)['url'],'title':'Claude skills for architecture'})
        store.upsert_item(self.c,{'id':b,'url':store.get_item(self.c,b)['url'],'title':'Claude cooking recipe notebook','note_json':json.dumps({'source_urls':['https://www.instagram.com/reel/B/']})})
        self.assertFalse(any(m['auto'] for m in topics.candidates(self.c,a)))
    def test_renderer_failure_keeps_originals_visible(self):
        ids=[self.stage(code) for code in 'AB']
        with patch.object(artifacts,'store',return_value={'error':'renderer unavailable'}):
            with self.assertRaises(RuntimeError):topics.consolidate(self.c,ids,title='Engine',synthesis={'answer':'guide '*100})
        self.assertEqual(store.counts(self.c)['total'],2)

if __name__=='__main__':unittest.main()
