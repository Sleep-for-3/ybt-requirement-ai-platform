"""Source-first delegated review, ingestion and freeze; no generation or retrieval."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_component_acceptance import authenticate_client, checked, reindex, upload
from rag_regression import digest, freeze_environment, read_json
from rag_review_environment import source_identity
from rag_review_replay import setup
from rag_source_review import write_json

SPECS = [
    ('FX01', 'HYF_PB_EXCH_RT_INFO.sql', 'mart_cny_pricing',
     '归档脚本HYF_PB_EXCH_RT_INFO的人民币本币分支，中间价、基准价、现钞买入价怎样换算，现汇买入价如何取值？',
     'HOME_CURR_TYP=CNY；中间价和基准价均A.MIDRATE/100，现钞买入价A.CSHBUYRATE/100，现汇买入价BUY_PRICE为NULL。不把注释中的旧表达式当现行脚本逻辑。',
     ['A.MIDRATE /100 AS MIDDLE_PRICE', 'NULL AS BUY_PRICE --7.']),
    ('FX02', 'HYF_PB_EXCH_RT_INFO.sql', 'mart_usd_cross_rate',
     '归档脚本HYF_PB_EXCH_RT_INFO的美元本币分支怎样计算中间价？美元基准行怎样关联和限定有效期？',
     '美元本币分支为A.MIDRATE/C.MIDRATE，LEFT JOIN同一汇率表C且C.CCY=USD，业务日去横线后满足C.START_DT<=业务日<C.END_DT。',
     ['A.MIDRATE / C.MIDRATE AS MIDDLE_PRICE', "ON C.CCY = 'USD'"]),
    ('FX03', 'HYF_PB_EXCH_RT_INFO.sql', 'mart_fx_identifier_date',
     '按归档脚本HYF_PB_EXCH_RT_INFO，人民币分支的EXCHANGE_NO与EXCHANGE_DATE分别使用哪一个日期？美元分支的EXCHANGE_NO又是什么？',
     '人民币EXCHANGE_NO为A.CCY拼CNY拼去横线的DATA_DATE，EXCHANGE_DATE来自去横线的A.VALUEDATE；美元分支EXCHANGE_NO为NULL，不能混用两种日期。',
     ["A.CCY||'CNY'", 'NULL AS EXCHANGE_NO']),
    ('FX04', 'HYF_PB_EXCH_RT_INFO.sql', 'mart_lpr_asof_selection',
     '归档脚本HYF_PB_EXCH_RT_INFO如何选择LPR记录日期及有效区间，并把一年期、五年期利率转成两列？',
     '只选一年期和五年期名称，业务日位于START_DT闭区间和END_DT开区间；取不晚于业务日的最大STDT，外层仍受同一有效期及名称约束；MAX(CASE WHEN名称匹配 THEN INTRT_VAL ELSE 0 END)分成LPR_1和LPR_5，并ON 1=1关联。',
     ["MAX(CASE WHEN INTRT_NM = 'LPR一年期利率'", 'WHERE STDT  = (SELECT MAX(STDT)']),
    ('TM01', 'HYF_BK_TERMINAL_INFO.sql', 'mart_atm_terminal_class',
     '归档脚本HYF_BK_TERMINAL_INFO在ATM来源分支中，CRS和VTS各映射成什么终端类型，是否统一填A01？',
     'CRS映射F01，VTS映射Z01；A01是被注释的旧写法，当前CASE没有统一填A01。',
     ["CASE WHEN B.CLASS_CODE = 'CRS' THEN 'F01'"]),
    ('TM02', 'HYF_BK_TERMINAL_INFO.sql', 'mart_atm_state_precedence',
     '归档脚本HYF_BK_TERMINAL_INFO的ATM终端状态CASE中，若DEV_EXT为2但DEV_STATUS为0会得到什么？请说明判断顺序，而非只罗列状态码。',
     '首分支DEV_EXT在0/1或DEV_STATUS=0即返回01，因此指定组合返回01，后面的DEV_EXT在2/8返回02分支不再执行。按SQL CASE顺序解释，不以注释覆盖表达式。',
     ["CASE WHEN G.DEV_EXT IN ('0','1')"]),
    ('TM03', 'HYF_BK_TERMINAL_INFO.sql', 'mart_stm_terminal_class',
     '归档脚本HYF_BK_TERMINAL_INFO的STM来源分支如何区分含BXS的终端类型？该分支金融IC卡受理标志是什么，和ATM来源是否相同？',
     'STM分支ID含BXS为Z01，否则G01，IC_CARD_FLG固定N；ATM分支IC_CARD_FLG固定Y，两来源不能混淆。',
     ["CASE WHEN A.ID LIKE '%BXS%' THEN 'Z01'", "'Y' AS IC_CARD_FLG"]),
    ('TM04', 'HYF_BK_TERMINAL_INFO.sql', 'mart_stm_start_date',
     '归档脚本HYF_BK_TERMINAL_INFO中STM终端启用日期怎样分支取值？请说明BXS、最早START_DT以及20260630边界。',
     '含BXS取去横线的A.STARTDATE；其他终端若D.START_DT<=20260630固定20210824，否则D.START_DT。D为按ID聚合MIN(START_DT)，不是最大或最新日期。',
     ["CASE WHEN A.ID LIKE '%BXS%' THEN REPLACE(A.STARTDATE", 'SELECT ID,MIN(START_DT)']),
    ('GM01', 'HYF_CL_GROUP_MEM_INFO.sql', 'mart_member_identifier_fallback',
     '归档脚本HYF_CL_GROUP_MEM_INFO里成员组织机构代码的来源优先级是什么？从统一社会信用代码构造时怎样截取？',
     '优先B.ORCD非空；否则B.UNN_SOC_CR_CD非空时取第9位起8字符、横线、第17位1字符；再否则用B1.UNN_SOC_CR_CD同样构造。空字符串判断不可擅自改为NULL判断。',
     ["CASE WHEN B.ORCD <> ''"]),
    ('GM02', 'HYF_CL_GROUP_MEM_INFO.sql', 'mart_member_expiry_asof',
     '归档脚本HYF_CL_GROUP_MEM_INFO如何保留集团成员的失效日期，上一期数据按哪些键和日期关联？',
     '关系状态不在1/2且T1.END_DATE非空时保留旧日期；不在1/2但没有旧日期取A.START_DT；其他为NULL。T1按集团客户号及成员客户号关联，DATA_DT为业务日前一天。',
     ["CASE WHEN A.CRG_GRP_REL_ST NOT IN ('1','2')", 'LEFT JOIN HYF_CL_GROUP_MEM_INFO T1']),
    ('GM03', 'HYF_CL_GROUP_MEM_INFO.sql', 'mart_member_active_filters',
     '归档脚本HYF_CL_GROUP_MEM_INFO实际WHERE是否仅保留已加入成员并排除失效集团？请区分可执行过滤和注释。',
     'A.DEL_IND=0且业务日>=A.START_DT、<A.END_DT是实际WHERE。A.CRG_GRP_REL_ST=1和C.CST_GRP_ST<>2都被注释，不能当作实际过滤；B/C关联分别另有DEL_IND及有效期约束。',
     ["WHERE A.DEL_IND = '0'"]),
    ('GM04', 'HYF_CL_GROUP_MEM_INFO.sql', 'mart_member_parent_flag',
     '归档脚本HYF_CL_GROUP_MEM_INFO怎样把GRP_PARCO_IND转换成母公司标志，未命中0和1时有无默认N？',
     '0映射N，1映射Y；CASE未写ELSE，未命中返回NULL，不能声称默认N。',
     ["CASE WHEN A.GRP_PARCO_IND ='0'"]),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    state = setup(args.runtime.resolve())
    identity = source_identity()
    assert identity['code_hash'] == read_json(args.runtime / 'source-identity.json')['code_hash']
    source_root = Path(__file__).resolve().parents[3] / '_assessment_work/testdata/mart_scripts'
    materials = {name: (source_root / name).read_bytes() for name in {s[1] for s in SPECS}}
    source_hashes = {name: hashlib.sha256(value).hexdigest() for name, value in materials.items()}
    for code, filename, _family, _query, _expected, anchors in SPECS:
        original = materials[filename].decode('utf-8-sig').replace('\r\n', '\n')
        assert all(original.count(anchor) == 1 for anchor in anchors), (code, 'ambiguous source anchor')
    review = {'review_kind': 'user_delegated_agent_review', 'human_business_approved': False,
        'regulatory_authority_conferred': False, 'approved_object': 'archived_script_evaluation_expectations',
        'source_hashes': source_hashes, 'questions_and_expectations': SPECS,
        'generation_outputs_observed_before_review': False, 'provider_calls_before_freeze': 0,
        'scope': 'Only executable archived SQL logic, comments distinguished; no live regulatory authority.'}
    review_path = root / 'source-only-review.private.json'
    if review_path.exists():
        assert read_json(review_path) == json.loads(json.dumps(review))
    else:
        write_json(review_path, review)
    from app.core.database import SessionLocal
    from app.models import KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeUnit, Project
    from app.services.storage import get_storage_service
    from sqlalchemy import select
    old_snapshot = read_json(Path(__file__).resolve().parents[2] /
        '.local-run/rag-source-review-20261115/final/snapshot/reviewed-environment.json')
    assert not set(source_hashes.values()) & {u['file_hash'] for u in old_snapshot['corpus']}
    checkpoint = root / 'ingestion-state.private.json'
    progress = read_json(checkpoint) if checkpoint.exists() else {'uploads': {}}
    with httpx.Client(base_url=state['backend_url'], timeout=120) as client:
        version = checked(client.get('/version'))
        assert version['app_commit'] == identity['git_head'] + '+worktree.' + identity['code_hash'][:12]
        from app.workers import celery_app
        worker = celery_app.send_task('app.workers.version_report').get(timeout=40)
        assert all(worker.get(k) == version.get(k) for k in ('app_commit', 'build_time', 'schema_head'))
        authenticate_client(client, state)
        if not progress.get('project_id'):
            with SessionLocal() as db:
                institution = db.get(Project, 1).institution_id
            progress['project_id'] = checked(client.post('/api/projects', json={
                'name': 'P0独立集市来源留出20261116', 'bank_name': 'RAG本地组件验收',
                'institution_id': institution}))['id']
            write_json(checkpoint, progress)
        project = progress['project_id']
        # Add all original documents as distractors through the real upload path.
        with SessionLocal() as db:
            existing_sources = []
            for version_id in sorted({u['version_id'] for u in old_snapshot['corpus']}):
                version = db.get(KnowledgeDocumentVersion, version_id)
                doc = db.get(KnowledgeDocument, version.document_id)
                existing_sources.append((doc.file_name, get_storage_service().read(version.storage_path), doc.source_type))
        for name, data, kind in existing_sources + [(name, materials[name], 'sql_evidence') for name in sorted(materials)]:
            if name not in progress['uploads']:
                progress['uploads'][name] = upload(client, project, name, data,
                    version='HOLDOUT-' + hashlib.sha256(data).hexdigest()[:12],
                    knowledge_type=kind, source_category='technical_evidence' if name.endswith('.sql') else 'regulatory_qa')
                write_json(checkpoint, progress)
        if not progress.get('index_ready'):
            reindex(client, project)
            progress['index_ready'] = True
            write_json(checkpoint, progress)
    with SessionLocal() as db:
        units = list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.project_id == project)))
        cases = []
        for code, filename, family, query, expected, anchors in SPECS:
            original = materials[filename].decode('utf-8-sig').replace('\r\n', '\n')
            required = {}
            for anchor in anchors:
                assert original.count(anchor) == 1, (code, 'ambiguous source anchor')
                line = original.count('\n', 0, original.index(anchor)) + 1
                matches = [u for u in units if u.document_id == progress['uploads'][filename]['document_id']
                    and u.unit_type == 'sql_text' and anchor in u.content
                    and type((u.metadata_json or {}).get('locator', {}).get('paragraph_index')) is int
                    and (u.metadata_json['locator']['line_start'] <= line <= u.metadata_json['locator']['line_end'])]
                assert matches, (code, 'missing raw source paragraph')
                unit = min(matches, key=lambda u: len(u.content))
                required[unit.id] = unit
            evidence = [{'unit_id': u.id, 'document_id': u.document_id, 'file_hash': source_hashes[filename],
                         'content_hash': digest(u.content)} for u in required.values()]
            cases.append({'case_id': 'MART-H-' + code, 'query': query, 'families': [family],
                'split': 'holdout', 'observed_before_run': False, 'review_kind': review['review_kind'],
                'review_status': 'approved', 'provenance': [{'source': filename, 'source_sha256': source_hashes[filename]}],
                'gold': {'decision': 'answerable', 'expected_summary': expected, 'must_refuse': False,
                    'must_confirm': False, 'relevant_ids': sorted(required),
                    'roles': {f'raw_source_paragraph_{u.id}': [u.id] for u in required.values()},
                    'evidence': evidence, 'review_kind': review['review_kind'],
                    'delegated_business_approved': True, 'human_business_approved': False,
                    'reviewer': 'Codex under explicit user delegation'}})
        dataset = {'schema': 'rag-fresh-source-delegated-holdout-v1', 'cases': cases,
            'split_policy': 'unobserved_mart_documents_and_executable_logic_families_only_no_tuning_on_holdout',
            'source_review_hash': digest(review), 'summary': {'cases': len(cases), 'new_holdout_cases': len(cases),
                'delegated_approved': len(cases), 'human_approved': 0}, 'blockers': []}
        dataset['dataset_version'] = digest(dataset)
        manifest = freeze_environment(None, project, dataset, session=db)
        for case in cases:
            case['gold']['corpus_hash'] = manifest['corpus_hash']
        dataset.pop('dataset_version')
        dataset['dataset_version'] = digest(dataset)
        manifest['dataset_version'] = dataset['dataset_version']
    snapshot = root / 'snapshot'
    if snapshot.exists():
        raise ValueError('Do not overwrite a frozen holdout')
    write_json(snapshot / 'reviewed-dataset.json', dataset)
    write_json(snapshot / 'reviewed-environment.json', manifest)
    write_json(root / 'freeze-summary.json', {'source_hash': identity['code_hash'],
        'dataset_version': dataset['dataset_version'], 'corpus_hash': manifest['corpus_hash'],
        'project_id': project, 'cases': len(cases), 'new_source_documents': len(materials),
        'distractor_documents': len(existing_sources), 'source_review_hash': digest(review),
        'external_model_calls': 0, 'human_business_approved': False, 'delegated_business_approved': True})
    print(json.dumps({'cases': len(cases), 'project_id': project, 'dataset_version': dataset['dataset_version'],
                      'corpus_units': len(manifest['corpus']), 'external_model_calls': 0}))


if __name__ == '__main__':
    main()
