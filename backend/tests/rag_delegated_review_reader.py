"""Display bounded source excerpts for explicit case-by-case delegated review."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from rag_regression import digest, read_json
from rag_review_replay import setup


def clean(text):
    text = re.sub(r'(?:提交人|提出人)?联系方式[^\n]*', '[contact]', str(text))
    text = re.sub(r'[（(][^（）()\n]{0,50}\d{3,4}[- ]?\d{7,8}[^（）()\n]{0,15}[）)]', '', str(text))
    text = re.sub(r'\d{3,4}[- ]?\d{7,8}', '[contact]', str(text))
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[contact]', text)
    return text


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--start', type=int, default=0)
    p.add_argument('--count', type=int, default=10)
    a = p.parse_args()
    setup(a.runtime.resolve())
    from app.core.database import SessionLocal
    from app.models import KnowledgeUnit
    dataset = read_json(a.dataset)
    source_path = Path(__file__).resolve().parents[2] / '.local-run/rag-source-review-20261115/source-review.json'
    original = read_json(source_path)
    rows = {(u['source_sheet_name'], u['source_cell_range']): u for u in original['units']}
    with SessionLocal() as db:
        for case in dataset['cases'][a.start:a.start + a.count]:
            sources = []
            for identity in case['gold']['relevant_ids']:
                unit = db.get(KnowledgeUnit, identity)
                assert unit is not None
                source = rows.get((unit.source_sheet_name, unit.source_cell_range))
                if source:
                    content = '\n'.join(str(f['header']) + ': ' + str(f['value'] or '')
                        for f in source['fields'] if str(f['header']) in {
                            '流程状态', '具体问题描述', '解决方案或建议', '反馈意见',
                            '是否变更制度', '数据项编码', '数据项名称', '表号（主）',
                            '业务规则版本', '脚本程序版本'})
                else:
                    content = unit.content
                sources.append({'id': identity, 'sha256': digest(unit.content),
                    'source_excerpt': clean(content[:1800]), 'truncated': len(content) > 1800})
            print(json.dumps({'case_id': case['case_id'], 'query': clean(case['query']),
                'decision': case['gold']['decision'], 'expected': case['gold']['expected_summary'],
                'sources': sources}, ensure_ascii=False))


if __name__ == '__main__':
    main()
