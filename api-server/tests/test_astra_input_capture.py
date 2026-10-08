"""Literature selection and input freezing are distinct from scientific scoring."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from app.services.astra_input_capture import prepare_astra_inputs


class Rows:
    def __init__(self,items):self.items=items
    def scalars(self):return self
    def all(self):return self.items


class FixtureDB:
    def __init__(self,collection,document):self.collection=collection;self.document=document;self.queries=[]
    async def execute(self,query):
        self.queries.append(query)
        if 'FROM rag_collections' in str(query):
            params=query.compile().params
            return Rows([] if any(value==[] for value in params.values()) else [self.collection])
        return Rows([self.document])


def test_literature_all_active_empty_and_explicit_freeze(tmp_path):
    file=tmp_path/'paper.txt';file.write_text('Provided paper fixture')
    collection=SimpleNamespace(id=4,name='Selected collection',updated_at='frozen-version',description='한글',chromadb_name='actual-search-name')
    doc=SimpleNamespace(id=8,collection_id=4,file_path=str(file),filename='paper.txt',file_type='txt',status='completed')
    order=SimpleNamespace(id=9,order_code='fixture',analysis_context={},rag_collections=None,
        report_options={'research_questions':['전체 질문\n0 false']})
    settings=SimpleNamespace(OUTPUT_DIR=str(tmp_path/'outputs'))
    with patch('app.config.get_settings',return_value=settings):
        db=FixtureDB(collection,doc);snapshot,pin=asyncio.run(prepare_astra_inputs(order,db,tmp_path/'ref'))
        assert pin['selection']=='all_active' and pin['collections'][0]['id']==4
        assert pin['documents'][0]['content_status']=='metadata_only'
        assert pin['collections'][0]['chromadb_name']=='actual-search-name'
        assert pin['documents'][0]['sha256'] and pin['documents'][0]['package_file'] is None
        assert pin['documents'][0]['evidence_export_permission']=='unknown'
        assert snapshot['original']['report_options']==order.report_options
        order.rag_collections=[]
        _,empty=asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
        assert empty['documents']==[] and empty['collections']==[] and empty['selection']=='explicit'
        order.rag_collections=[4];order.analysis_context={'literature_content_permissions':{'8':True}}
        _,full=asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
        assert full['documents'][0]['content_status']=='full_text_included'
        assert (tmp_path/'ref/literature_objects'/full['documents'][0]['sha256']).read_text()==file.read_text()
        # Changed selection cannot reuse an inherited pin from an unrelated selection.
        order.analysis_context['astra_literature_pin']=full;order.rag_collections=[]
        _,changed=asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
        assert changed['documents']==[]


def test_attachment_scope_bytes_and_pin_invalidation(tmp_path):
    import hashlib
    import pytest
    collection=SimpleNamespace(id=4,name='Collection',updated_at='v1',description='fixture')
    doc=SimpleNamespace(id=8,file_path=str(tmp_path/'missing.txt'),filename='paper.txt',file_type='txt',status='completed')
    upload=tmp_path/'order/research_attachments/0';upload.mkdir(parents=True)
    paper=upload/'paper.txt';paper.write_text('전체 원문\nαβ')
    record={'filename':'제공 논문.txt','stored_path':str(paper),'sha256':hashlib.sha256(paper.read_bytes()).hexdigest()}
    order=SimpleNamespace(id=9,order_code='fixture',pr_matrix_path=str(tmp_path/'order/PR.tsv'),
        analysis_context={'research_attachment_records':[record]},rag_collections=[],report_options={})
    settings=SimpleNamespace(OUTPUT_DIR=str(tmp_path/'outputs'))
    with patch('app.config.get_settings',return_value=settings):
        snapshot,pin=asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
        assert 'stored_path' not in snapshot['original']['analysis_context']['research_attachment_records'][0]
        assert snapshot['excluded_fields'][0]['reason']=='server_storage_path'
        assert pin['documents'][0]['content_status']=='full_text_included'
        assert (tmp_path/'ref/literature_objects'/record['sha256']).read_bytes()==paper.read_bytes()
        order.analysis_context['astra_literature_pin']=pin
        paper.write_text('새 원문');record['sha256']=hashlib.sha256(paper.read_bytes()).hexdigest()
        _,changed=asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
        assert changed['research_attachment_hashes']!=pin['research_attachment_hashes']
        record['stored_path']=str(tmp_path/'outside.txt')
        with pytest.raises(ValueError,match='upload scope'):
            asyncio.run(prepare_astra_inputs(order,FixtureDB(collection,doc),tmp_path/'ref'))
