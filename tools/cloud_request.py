"""Apply one version-checked user request in a copied workspace."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workspace import DIRS, catalog
from xmind_core import XMindError, file_sha256, load_package, validate, write_package
from xmind_edit import apply_operation


def run():
    path=ROOT/'requests/request.json'
    if not path.exists(): print('没有待处理请求。'); return
    request=json.loads(path.read_text(encoding='utf-8'))
    request_id=request.get('request_id','')
    if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',request_id):
        raise ValueError('request_id 只能使用字母、数字、下划线和连字符，最长 80 字符。')
    if request.get('version')!=1: raise ValueError('version 必须是 1。')
    digest=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    report=ROOT/'requests/results'/f'{request_id}.json'
    if report.exists():
        if json.loads(report.read_text())['request_sha256']==digest:
            print('此请求已完成；未重复执行。'); return
        raise ValueError('request_id 已使用；新请求请用新 ID。')
    rel=Path(request.get('file',''))
    if rel.is_absolute() or not rel.parts or rel.parts[0] not in DIRS or '..' in rel.parts or rel.suffix!='.xmind':
        raise ValueError('只能修改工作区五个导图目录内的 .xmind 文件。')
    target=ROOT/rel
    if any(p.is_symlink() for p in [target,*target.parents] if p!=ROOT.parent):
        raise ValueError('拒绝通过符号链接修改文件。')
    target.resolve().relative_to(ROOT.resolve())
    expected=request.get('expect_sha256')
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
        raise ValueError('必须提供最新读取结果中的 expect_sha256。')
    if file_sha256(target)!=expected: raise ValueError('导图已经更新，请重新读取后提交新请求。')
    operations=request.get('operations')
    if not isinstance(operations,list) or not operations or len(operations)>1000 or not all(isinstance(op,dict) for op in operations):
        raise ValueError('operations 必须包含 1–1000 个操作。')
    entries,content=load_package(target)
    for op in operations: apply_operation(content,op)
    validation=validate(content)
    # Recheck immediately before saving, using the same package writer as local edits.
    if file_sha256(target)!=expected: raise ValueError('保存前发现文件更新，已停止。')
    write_package(target,entries,content)
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({'request_id':request_id,'request_sha256':digest,'file':rel.as_posix(),
        'before_sha256':expected,'after_sha256':file_sha256(target),'operation_count':len(operations),
        'status':'completed','validation':validation},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    catalog()
    print('已处理：'+request_id)


if __name__=='__main__':
    try: run()
    except (ValueError,OSError,XMindError) as e: print(str(e),file=sys.stderr); raise SystemExit(1)
