"""Publish measurements without copying private source bodies or credentials."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

from rag_regression import read_json
from rag_source_review import write_json


def export(run,output):
    dataset=read_json(run/'snapshot/reviewed-dataset.json')
    manifest=read_json(run/'snapshot/reviewed-environment.json')
    report=read_json(run/'replay/acceptance-summary.json')
    public={**report,'rows':[{k:v for k,v in row.items() if k!='assessment_reason'} for row in report['rows']]}
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/'source-review-results-20261115.json',public)
    cases=[]
    for c in dataset['cases']:
        cases.append({'case_id':c['case_id'],'query':c['query'],'split':c['split'],
            'agent_decision':c['gold']['decision'],'agent_expected_summary':c['gold']['expected_summary'],
            'anchors':c['gold']['evidence'],'human_reviewer':None,
            'human_action':None,'approved_answer':None,'authoritative_source_path':None,
            'authoritative_version':None,'authoritative_locator':None,
            'note':None})
    write_json(run/'business-confirmation.json',{'schema':'rag-business-confirmation-v1',
        'dataset_version':dataset['dataset_version'],'corpus_hash':manifest['corpus_hash'],
        'allowed_actions':['accept_agent_source_review','keep_needs_confirmation','supply_authoritative_source'],
        'cases':cases})
    blocked=[c for c in cases if c['agent_decision'] in ('pending','partial','insufficient')]
    lines=['# 需要业务确认的事项','',
        '以下内容来自逐题源文件审核。确认人可以选择保持待确认，不需要编造最终答案。',
        '未获批准的建议不能填作监管规则。实际填报前的业务审批由具备权限的人员完成。','',
        '| case_id | 原文定位 | 未解决事项 |','| --- | --- | --- |']
    for c in blocked:
        anchor='；'.join(f"{e.get('source_sheet_name','')}!{e.get('source_cell_range','')}" for e in c['anchors']) or '缺合规原文'
        lines.append(f"| `{c['case_id']}` | {anchor} | {c['agent_expected_summary'].replace('|','／')} |")
    (output/'business-confirmation-20261115.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'cases_reviewed':len(cases),'business_content_gaps':len(blocked),'output':str(output)}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-directory',required=True)
    p.add_argument('--output-directory',required=True)
    a=p.parse_args()
    export(Path(a.run_directory).resolve(),Path(a.output_directory).resolve())
