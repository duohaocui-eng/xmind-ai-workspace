"""Manual, one-click Git synchronization for XMind workspaces."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import queue
import shutil
import hashlib
import time
import zipfile
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote
import uuid

MAP_DIRS = ('00_临时','10_进行中','20_草稿','30_长期','90_归档')


class SyncError(RuntimeError):
    pass


def state_dir():
    root = Path(os.environ.get('LOCALAPPDATA') or (Path.home()/'.local/share'))/'XMindSync'
    root.mkdir(parents=True,exist_ok=True)
    return root


def run_git(root, *args, check=True):
    env=dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never')
    env.setdefault('GIT_SSH_COMMAND','ssh -o BatchMode=yes -o ConnectTimeout=15')
    executable=shutil.which('git')
    if not executable and os.name=='nt':
        for base in (os.environ.get('ProgramFiles',''),os.environ.get('LOCALAPPDATA','')):
            for relative in ('Git/cmd/git.exe','Programs/Git/cmd/git.exe'):
                candidate=Path(base)/relative
                if candidate.is_file():executable=str(candidate);break
            if executable:break
    try:
        p=subprocess.run([executable or 'git','-c','core.quotepath=false',*args],cwd=root,env=env,
            capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except FileNotFoundError:
        raise SyncError('未找到 Git。请先安装 Git，或使用已经可以拉取和推送的电脑。') from None
    except subprocess.TimeoutExpired:
        raise SyncError('连接超时，文件已保留。请检查网络后重试。') from None
    if check and p.returncode:
        raise SyncError('操作未完成，文件已保留。请检查仓库权限、网络和现有 Git 认证；也可能是云端刚有新提交，请重试。')
    return p


def git_text(root,*args):
    return run_git(root,*args).stdout.decode('utf-8','replace').strip()


def sync_path(path):
    p=PurePosixPath(path)
    return path=='CATALOG.md' or (len(p.parts)>1 and p.parts[0] in MAP_DIRS and p.suffix.lower()=='.xmind' and '..' not in p.parts)


def zpaths(raw):
    return {s.decode('utf-8') for s in raw.split(b'\0') if s}


def dirty_paths(root):
    chunks=run_git(root,'status','--porcelain=v1','-z','--untracked-files=all').stdout.split(b'\0')
    paths=set();i=0
    while i<len(chunks):
        chunk=chunks[i];i+=1
        if not chunk:continue
        status=chunk[:2].decode('ascii'); paths.add(chunk[3:].decode('utf-8'))
        if 'R' in status or 'C' in status:
            if i<len(chunks) and chunks[i]:paths.add(chunks[i].decode('utf-8'))
            i+=1
    return paths


@contextmanager
def repo_lock(root):
    common=Path(git_text(root,'rev-parse','--git-common-dir'))
    if not common.is_absolute():common=root/common
    with (common/'xmind-sync.lock').open('a+b') as lock:
        lock.seek(0,2)
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise SyncError('另一个同步操作正在进行，请稍后重试。') from None
        try:yield
        finally:
            lock.seek(0)
            if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock,fcntl.LOCK_UN)


def catalog(root):
    lines=['# 我的导图目录','','点击文件下载后用 XMind 打开。Git 同步后请重新打开文档。','']
    for name in MAP_DIRS:
        lines.extend(['## '+name,''])
        paths=sorted((root/name).rglob('*.xmind')) if (root/name).exists() else []
        lines.extend(f'- [{p.stem.replace(chr(93), chr(65341))}]({quote(p.relative_to(root).as_posix())})' for p in paths if p.is_file())
        if not paths:lines.append('暂未放入导图。')
        lines.append('')
    (root/'CATALOG.md').write_text('\n'.join(lines),encoding='utf-8')


class WorkspaceSync:
    def __init__(self,path,progress=lambda text:None):
        candidate=Path(path).expanduser().resolve()
        if not candidate.is_dir():raise SyncError('请选择已经克隆到电脑的工作区文件夹。')
        probe=run_git(candidate,'rev-parse','--show-toplevel',check=False)
        if probe.returncode:raise SyncError('此目录不是 Git 仓库。首次请克隆自己的云工作区，再选择它。')
        self.root=Path(probe.stdout.decode('utf-8').strip()).resolve()
        if not any((self.root/d).is_dir() for d in MAP_DIRS):
            raise SyncError('未找到导图工作区目录，请选择 XMind 工作区仓库。')
        self.progress=progress

    def refs(self):
        branch=git_text(self.root,'symbolic-ref','--quiet','--short','HEAD')
        remote=git_text(self.root,'config',f'branch.{branch}.remote')
        merge=git_text(self.root,'config',f'branch.{branch}.merge')
        if remote=='.' or not merge.startswith('refs/heads/'):
            raise SyncError('当前分支没有可用的云端上游，请先完成仓库克隆与分支设置。')
        return remote,merge,remote+'/'+merge[len('refs/heads/'):]

    def check_idle(self):
        for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','rebase-merge','rebase-apply'):
            p=Path(git_text(self.root,'rev-parse','--git-path',name))
            if not p.is_absolute():p=self.root/p
            if p.exists():raise SyncError('仓库有尚未处理完成的合并或变基，请先处理后再同步。')
        if run_git(self.root,'diff','--cached','--quiet',check=False).returncode:
            raise SyncError('仓库有已暂存内容。为保留你原来的提交操作，请先处理后再同步。')

    def fetch(self):
        remote,merge,upstream=self.refs()
        self.progress('正在检查云端更新…')
        run_git(self.root,'fetch','--no-tags',remote)
        run_git(self.root,'rev-parse','--verify',upstream)
        return remote,merge,upstream

    def status(self,fetch=False):
        if fetch:
            with repo_lock(self.root):_,_,upstream=self.fetch()
        else:_,_,upstream=self.refs()
        ahead,behind=map(int,git_text(self.root,'rev-list','--left-right','--count','HEAD...'+upstream).split())
        dirty=dirty_paths(self.root)
        return {'root':str(self.root),'local_files':len([p for p in dirty if sync_path(p)]),'ahead':ahead,'behind':behind}

    def changed(self,a,b):
        return zpaths(run_git(self.root,'diff','--name-only','--no-renames','-z',a,b,'--').stdout)

    def conflict_copies(self,paths,upstream):
        folder=state_dir()/'conflicts'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
        for side,ref in [('本地','HEAD'),('云端',upstream)]:
            for path in paths:
                p=PurePosixPath(path)
                if p.is_absolute() or '..' in p.parts:continue
                result=run_git(self.root,'show',ref+':'+path,check=False)
                if result.returncode==0:
                    target=folder/side/Path(*p.parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result.stdout)
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'说明.txt').write_text('双方均有改动，未自动覆盖。原仓库保留本地版本，云端版本未被覆盖。\n'+'\n'.join(sorted(paths)),encoding='utf-8')
        return folder

    def integrate(self,upstream):
        ahead,behind=map(int,git_text(self.root,'rev-list','--left-right','--count','HEAD...'+upstream).split())
        if not behind:return
        if not ahead:
            run_git(self.root,'merge','--ff-only',upstream);return
        base=git_text(self.root,'merge-base','HEAD',upstream)
        ours=self.changed(base,'HEAD');theirs=self.changed(base,upstream)
        overlap=(ours&theirs)-{'CATALOG.md'}
        if overlap:
            folder=self.conflict_copies(overlap,upstream)
            raise SyncError('双方修改了同一文件，已停止同步并保留双方副本。\n副本目录：'+str(folder))
        before=git_text(self.root,'rev-parse','HEAD')
        with tempfile.TemporaryDirectory(prefix='xmind-sync-') as temporary:
            work=Path(temporary)/'merge'
            run_git(self.root,'worktree','add','--detach',str(work),before)
            try:
                result=run_git(work,'merge','--no-commit','--no-ff',upstream,check=False)
                conflicts=zpaths(run_git(work,'diff','--name-only','--diff-filter=U','-z').stdout)
                if conflicts-{'CATALOG.md'} or (result.returncode and not conflicts):
                    raise SyncError('更新无法自动整合，已保留原文件；请先处理冲突。')
                if 'CATALOG.md' in conflicts:run_git(work,'checkout','--ours','--','CATALOG.md')
                catalog(work);run_git(work,'add','--','CATALOG.md')
                run_git(work,'commit','-m','Sync XMind workspace changes')
                combined=git_text(work,'rev-parse','HEAD')
                if git_text(self.root,'rev-parse','HEAD')!=before or dirty_paths(self.root):
                    raise SyncError('同步期间本地又有修改，已停止应用更新，请保存后重试。')
                run_git(self.root,'merge','--ff-only',combined)
            finally:
                run_git(self.root,'worktree','remove','--force',str(work),check=False)

    def download(self):
        with repo_lock(self.root):
            self.check_idle()
            if dirty_paths(self.root):raise SyncError('本地有尚未上传的修改。请先保存并点击“上传本地修改”，再获取更新。')
            _,_,upstream=self.fetch()
            before=git_text(self.root,'rev-parse','HEAD')
            self.integrate(upstream)
            paths=self.changed(before,'HEAD')
            maps=sorted(p for p in paths if p.lower().endswith('.xmind'))
            return {'message':f'已获取 {len(maps)} 张导图更新。请重新打开相关 XMind 文档。' if paths else '已是最新版本。','files':maps}

    def upload(self):
        with repo_lock(self.root):
            self.check_idle()
            dirty=dirty_paths(self.root)
            if any(not sync_path(p) for p in dirty):
                raise SyncError('工作区还有导图以外的修改。请先处理这些修改；本工具只提交导图和目录索引。')
            remote,merge,upstream=self.fetch()
            base=git_text(self.root,'merge-base','HEAD',upstream)
            if any(not sync_path(p) for p in self.changed(base,'HEAD')):
                raise SyncError('本地有尚未推送的程序或其他文件提交，请先自行处理；本工具不会顺带上传。')
            # Save locally first. Divergent edits can then be checked without losing either version.
            if dirty:
                signatures={}
                for name in dirty:
                    file=self.root/name
                    if file.suffix.lower()=='.xmind' and file.exists():
                        try:
                            with zipfile.ZipFile(file) as z:
                                if z.testzip() is not None:raise ValueError('corrupt')
                            signatures[name]=hashlib.sha256(file.read_bytes()).hexdigest()
                        except (OSError,ValueError,zipfile.BadZipFile):
                            raise SyncError('导图可能尚未保存完成，请在 XMind 中保存后重试。') from None
                time.sleep(.35)
                for name,digest in signatures.items():
                    file=self.root/name
                    if not file.exists() or hashlib.sha256(file.read_bytes()).hexdigest()!=digest:
                        raise SyncError('检测到文件仍在保存，请等待保存完成后重试。')
                catalog(self.root)
                current=dirty_paths(self.root)
                if any(not sync_path(p) for p in current):raise SyncError('检查期间出现其他文件改动，已暂停。')
                allowed=sorted(current)
                if allowed:
                    run_git(self.root,'add','--all','--',*allowed)
                    try:run_git(self.root,'commit','-m','Save XMind maps '+datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    except SyncError:
                        run_git(self.root,'reset','--mixed','HEAD',check=False)
                        raise SyncError('本地保存未完成，请检查 Git 提交身份。文件仍保留。') from None
            if dirty_paths(self.root):raise SyncError('同步期间文件又有修改，已保留当前进度，请保存后重试。')
            self.integrate(upstream)
            pending=self.changed(upstream,'HEAD')
            count=int(git_text(self.root,'rev-list','--count',upstream+'..HEAD'))
            if not count:return {'message':'没有需要上传的修改。','files':[]}
            self.progress('正在上传已保存的导图…')
            run_git(self.root,'push',remote,'HEAD:'+merge)
            maps=sorted(p for p in pending if p.lower().endswith('.xmind'))
            return {'message':f'已上传 {len(maps)} 张导图修改。','files':maps}


def open_folder(path):
    if sys.platform=='win32':os.startfile(str(path))
    elif sys.platform=='darwin':subprocess.Popen(['open',str(path)])
    else:subprocess.Popen(['xdg-open',str(path)])


def gui(smoke_report=None):
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    window=tk.Tk();window.title('XMind 工作区同步');window.geometry('720x480+100+100');window.minsize(620,420)
    config=state_dir()/'settings.json'
    try:saved=json.loads(config.read_text(encoding='utf-8'))
    except (OSError,ValueError):saved={}
    path=tk.StringVar(value=saved.get('workspace',''));status=tk.StringVar(value='选择已有的本地工作区，点击按钮同步。')
    counts=tk.StringVar(value='本地与云端状态：尚未检查')
    frame=ttk.Frame(window,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='导图在电脑和 AI 之间，一键接续',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,16))
    row=ttk.Frame(frame);row.pack(fill='x')
    entry=ttk.Entry(row,textvariable=path);entry.pack(side='left',fill='x',expand=True)
    messages=queue.Queue();controls=[]
    def select():
        folder=filedialog.askdirectory(title='选择已有的本地 Git 工作区')
        if folder:path.set(folder);config.write_text(json.dumps({'workspace':folder},ensure_ascii=False),encoding='utf-8');start('status',False)
    choose=ttk.Button(row,text='选择工作区',command=select);choose.pack(side='right',padx=(8,0));controls.append(choose)
    ttk.Label(frame,textvariable=counts).pack(anchor='w',pady=(14,10))
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=(0,12))
    def start(action,fetch=True):
        selected=path.get().strip()
        if not selected:messagebox.showinfo('选择工作区','请选择已经克隆到电脑的工作区文件夹。');return
        for c in controls:c.configure(state='disabled')
        entry.configure(state='disabled');status.set('正在处理，请稍候…')
        def work():
            try:
                client=WorkspaceSync(selected,lambda text:messages.put(('progress',text)))
                result=client.status(fetch=fetch) if action=='status' else getattr(client,action)()
                messages.put(('done',(action,result,client.status())))
            except Exception as error:messages.put(('error',str(error) if isinstance(error,SyncError) else '操作未完成，文件已保留。请检查仓库后重试。'))
        threading.Thread(target=work,daemon=True).start()
    for title,action in [('获取云端更新','download'),('上传本地修改','upload')]:
        button=ttk.Button(buttons,text=title,command=lambda a=action:start(a));button.pack(side='left',expand=True,fill='x',padx=(0,10));controls.append(button)
    helpers=ttk.Frame(frame);helpers.pack(fill='x')
    for title,fn in [('刷新状态',lambda:start('status')),('打开导图文件夹',lambda:open_folder(Path(path.get())) if path.get() else None)]:
        button=ttk.Button(helpers,text=title,command=fn);button.pack(side='left',padx=(0,10));controls.append(button)
    ttk.Label(frame,text='上传前先保存导图；获取前先保存并关闭相关 XMind 文档。',wraplength=650).pack(anchor='w',pady=(16,10))
    ttk.Label(frame,textvariable=status,wraplength=650).pack(anchor='w')
    output=tk.Text(frame,height=8,wrap='word',font=('Microsoft YaHei UI',10));output.pack(fill='both',expand=True,pady=(8,0));output.configure(state='disabled')
    def poll():
        try:
            while True:
                kind,value=messages.get_nowait()
                if kind=='progress':status.set(value);continue
                for c in controls:c.configure(state='normal')
                entry.configure(state='normal')
                if kind=='error':status.set('同步已暂停');text=value
                else:
                    action,result,info=value
                    counts.set(f"本地待保存文件 {info['local_files']} · 本地待上传提交 {info['ahead']} · 云端待获取提交 {info['behind']}")
                    text='状态已更新。' if action=='status' else result['message']+'\n'+'\n'.join(result['files'])
                    status.set('状态已更新' if action=='status' else result['message'])
                output.configure(state='normal');output.delete('1.0','end');output.insert('1.0',text);output.configure(state='disabled')
        except queue.Empty:pass
        window.after(100,poll)
    def closing():
        if entry.instate(['disabled']):messagebox.showinfo('正在同步','请等待本次同步结束后关闭窗口。');return
        window.destroy()
    window.protocol('WM_DELETE_WINDOW',closing);poll()
    if path.get():window.after(200,lambda:start('status',False))
    if smoke_report:
        def finish_smoke():
            Path(smoke_report).write_text(json.dumps({'gui_started':True,'tk_version':tk.TkVersion,'children':len(frame.winfo_children())}),encoding='utf-8')
            window.destroy()
        window.after(1500,finish_smoke)
    window.mainloop()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--check-repo');parser.add_argument('--report');parser.add_argument('--smoke-gui')
    args=parser.parse_args()
    if args.check_repo:
        try:result=WorkspaceSync(args.check_repo).status()
        except Exception as error:result={'error':str(error)}
        if args.report:Path(args.report).write_text(json.dumps(result),encoding='utf-8')
        return 1 if 'error' in result else 0
    gui(smoke_report=args.smoke_gui);return 0


if __name__=='__main__':raise SystemExit(main())
