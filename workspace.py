#!/usr/bin/env python3
"""User entry point for a personal XMind cloud workspace."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
DIRS = ['00_临时', '10_进行中', '20_草稿', '30_长期', '90_归档']


def init():
    for name in DIRS:
        (ROOT / name).mkdir(exist_ok=True)
    target = ROOT / DIRS[0] / '入门示例.xmind'
    if not target.exists():
        content = [{'id':'welcome-sheet','class':'sheet','title':'入门示例', 'rootTopic':{
            'id':'welcome-root','class':'topic','title':'我的 AI 导图工作区',
            'structureClass':'org.xmind.ui.logic.right','children':{'attached':[
                {'id':'welcome-read','class':'topic','title':'读取：让 AI 理解已有导图'},
                {'id':'welcome-edit','class':'topic','title':'修改：围绕节点持续完善'},
                {'id':'welcome-sync','class':'topic','title':'保存：云目录与版本历史'}]}}}]
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('content.json',json.dumps(content,ensure_ascii=False))
            z.writestr('metadata.json',json.dumps({'creator':{'name':'XMind AI Workspace','version':'1.0.0'}}))
            z.writestr('manifest.json',json.dumps({'file-entries':{'content.json':{},'metadata.json':{}}}))
    catalog()
    print('工作区就绪。示例：00_临时/入门示例.xmind')


def files():
    return sorted(p for name in DIRS for p in (ROOT / name).rglob('*.xmind') if p.is_file())


def catalog():
    lines=['# 我的导图目录', '', '点击文件下载后用 XMind 打开。Git 同步后请重新打开文档。', '']
    for name in DIRS:
        lines.extend(['## '+name,''])
        matches=[p for p in files() if p.relative_to(ROOT).parts[0]==name]
        lines.extend(f'- [{p.stem}]({quote(p.relative_to(ROOT).as_posix())})' for p in matches)
        if not matches: lines.append('暂未放入导图。')
        lines.append('')
    (ROOT / 'CATALOG.md').write_text('\n'.join(lines),encoding='utf-8')
    for p in files(): print(p.relative_to(ROOT))


def call(tool, args):
    return subprocess.call([sys.executable, str(ROOT/'tools'/tool), *args],cwd=ROOT)


def demo():
    init()
    source=ROOT/DIRS[0]/'入门示例.xmind'
    # A separate output makes repeat demos safe for the original.
    target='00_临时/入门示例-修改后.xmind'
    request={'version':1,'request_id':'local-demo','file':str(source),
             'output':str(ROOT/target),'expect_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
             'operations':[{'op':'rename','target':{'id':'welcome-root'},'title':'已完成第一次 AI 导图修改'}]}
    req=ROOT/'requests/local-demo.json'; req.parent.mkdir(exist_ok=True)
    req.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    code=call('xmind_edit.py',['--request',str(req)])
    if code: return code
    catalog(); print('演示完成，原图保留。用 XMind 打开：'+target)
    return 0


def menu():
    print('\nXMind AI Workspace\n1 初始化 / 刷新云目录\n2 查看导图结构\n3 跑通示例修改（保留原图）\n0 退出')
    choice=input('选择 [1]: ').strip() or '1'
    if choice=='0': return 0
    if choice=='1': init(); return 0
    if choice=='3': return demo()
    if choice=='2':
        paths=files()
        if not paths: init(); paths=files()
        for i,p in enumerate(paths,1): print(i,p.relative_to(ROOT))
        try:
            number=int(input('输入文件序号: '))
            if not 1 <= number <= len(paths): raise ValueError('invalid index')
            p=paths[number-1]
        except (ValueError,IndexError): print('序号无效'); return 1
        return call('xmind_read.py',[str(p),'--format','tree'])
    print('选择无效'); return 1


def main():
    parser=argparse.ArgumentParser(description='XMind 云工作区：初始化、目录、读取和示例')
    parser.add_argument('action',nargs='?',choices=['init','list','demo','read'])
    args,rest=parser.parse_known_args()
    if args.action=='read': return call('xmind_read.py',rest)
    if rest: parser.error('无法识别参数：'+' '.join(rest))
    if args.action=='init': init(); return 0
    if args.action=='list': catalog(); return 0
    if args.action=='demo': return demo()
    return menu()


if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError) as e: print('未完成：',e,file=sys.stderr); raise SystemExit(1)
    except KeyboardInterrupt: raise SystemExit(130)
