"""Finish one frozen real acceptance run after its owned index job completes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

import httpx

from rag_component_acceptance import authenticate_client,wait_job
from rag_regression import read_json


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True)
    p.add_argument('--output-directory',required=True)
    p.add_argument('--max-generation-requests',required=True,type=int)
    p.add_argument('--max-judge-requests',required=True,type=int)
    a=p.parse_args()
    root=Path(a.workspace).resolve()
    target=Path(a.output_directory).resolve()
    state=read_json(root/'state.json')
    if not state.get('index_job'):
        with httpx.Client(base_url=state['backend_url'],timeout=30) as client:
            authenticate_client(client,state)
            jobs=client.get('/api/jobs',params={'project_id':state['corpus_project_id']})
            jobs.raise_for_status()
            candidates=[j for j in jobs.json() if j['job_type']=='knowledge_embedding_reindex']
            if len(candidates)!=1:
                raise ValueError('Cannot uniquely identify the owned formal index job')
            wait_job(client,candidates[0])
    target.mkdir(parents=True,exist_ok=True)
    docs=Path(__file__).resolve().parents[2]/'docs/evaluation/rag-upgrade-20261113'
    if not (target/'snapshot/reviewed-dataset.json').exists():
        subprocess.run([sys.executable,'scripts/rag_review_dataset.py','--workspace',str(root),
            '--dataset',str(docs/'dataset.json'),'--adjudications',str(docs/'source-adjudications-20261115.json'),
            '--holdout',str(docs/'independent-holdout-20261115.json'),'--output-directory',str(target/'snapshot')],check=True)
    common=['--workspace',str(root),'--snapshot-directory',str(target/'snapshot'),'--output-directory',str(target/'replay')]
    for command,options in [('generate',['--max-generation-requests',str(a.max_generation_requests)]),
                            ('judge',['--max-judge-requests',str(a.max_judge_requests)]),('summarize',[])]:
        subprocess.run([sys.executable,'scripts/rag_review_replay.py',command,*common,*options],check=True)
