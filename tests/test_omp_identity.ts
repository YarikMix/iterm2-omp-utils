import { test, expect } from 'bun:test';
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { registerIdentity, readProcessIdentity, type IdentityContext, type Observation, type RecordValue } from '../runtime/omp_identity';
import { spawnSync } from 'node:child_process';

const terminal = 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE';
function fixture() {
  const root = realpathSync(mkdtempSync(join(tmpdir(), 'omp-identity-')));
  const handlers = new Map<string, Function>();
  const writes: RecordValue[] = [];
  const profile = { name: 'work', agent_dir: join(root, 'agent') };
  let observation: Observation | null = { terminal_id: terminal, tab_id: 'tab', window_id: 'window', tty: '/dev/ttys001' };
  const options = { registry: join(root, 'registry'), profile,
    process: () => ({ pid: 123, process_start: 'birth-1' }),
    observe: () => observation, publish: (_tty: string, value: RecordValue) => writes.push(value) };
  registerIdentity({ on: (event: string, handler: Function) => handlers.set(event, handler) }, options);
  let sid = 'real-id', file: string | undefined = join(root, 'non-derived.jsonl');
  const ctx: IdentityContext = { mode: 'tui', agent: { kind: 'main', depth: 0 },
    sessionManager: { getSessionId: () => sid, getSessionFile: () => file, getCwd: () => root } };
  return { root, handlers, writes, options, ctx, switch: (id: string, path?: string) => { sid=id; file=path; },
    observe: (value: Observation | null) => { observation=value; },
    records: () => readdirSync(options.registry).filter(n => n.endsWith('.json')).map(n => JSON.parse(readFileSync(join(options.registry,n),'utf8'))) };
}

test('only proven main TUI publishes actual manager values and private records', async () => {
  const f = fixture();
  try {
    for (const patch of [{mode:'print'}, {agent:{kind:'sub',depth:0}}, {agent:undefined}])
      await f.handlers.get('session_start')!({}, {...f.ctx,...patch});
    expect(f.writes).toEqual([]);
    await f.handlers.get('session_start')!({}, f.ctx);
    expect(f.records()[0]).toMatchObject({ session_id:'real-id', session_file:join(f.root,'non-derived.jsonl'), cwd:f.root,
      profile:f.options.profile, pid:123, process_start:'birth-1', terminal_id:terminal });
    expect(statSync(f.options.registry).mode & 0o777).toBe(0o700);
    const name = readdirSync(f.options.registry)[0];
    expect(statSync(join(f.options.registry,name)).mode & 0o777).toBe(0o600);
    f.switch('switched',join(f.root,'different.jsonl'));
    await f.handlers.get('session_switch')!({}, f.ctx);
    expect(f.records()).toHaveLength(1);
    expect(f.records()[0].session_id).toBe('switched');
    f.switch('unsaved');
    await f.handlers.get('session_branch')!({}, f.ctx);
    expect(f.records()[0].session_file).toBeNull();
    expect(f.records()[0].session_id).toBe('unsaved');
  } finally { rmSync(f.root,{recursive:true,force:true}); }
});

test('shutdown cannot remove another process generation and old records cannot impersonate it', async () => {
  const f = fixture();
  try {
    await f.handlers.get('session_start')!({}, f.ctx);
    const old = f.records()[0];
    const next = new Map<string,Function>();
    registerIdentity({on:(event:string,handler:Function)=>next.set(event,handler)},
      {...f.options, process:()=>({pid:123,process_start:'birth-2'})});
    await next.get('session_start')!({},f.ctx);
    expect(f.records()).toHaveLength(2);
    const current = f.writes.at(-1);
    expect(current.generation).not.toBe(old.generation);
    await f.handlers.get('session_shutdown')!({},f.ctx);
    expect(f.records()).toHaveLength(1);
    expect(f.records()[0].process_start).toBe('birth-2');
  } finally { rmSync(f.root,{recursive:true,force:true}); }
});

test('missing own tty observation and symlink registry fail closed', async () => {
  const f = fixture();
  try {
    f.observe(null);
    await f.handlers.get('session_start')!({}, f.ctx);
    expect(f.writes).toEqual([]);
    f.observe({terminal_id:terminal,tab_id:'tab',window_id:'window',tty:''});
    await f.handlers.get('session_start')!({}, f.ctx);
    expect(f.writes).toEqual([]);
    symlinkSync(f.root,f.options.registry);
    f.observe({terminal_id:terminal,tab_id:'tab',window_id:'window',tty:'/dev/ttys001'});
    await expect(f.handlers.get('session_start')!({},f.ctx)).rejects.toThrow();
    expect(f.writes).toEqual([]);
  } finally { rmSync(f.root,{recursive:true,force:true}); }
});

test('failed session-switch observation invalidates the prior record', async () => {
  const f = fixture();
  try {
    await f.handlers.get('session_start')!({},f.ctx);
    expect(f.records()).toHaveLength(1);
    f.switch('new-dialog',join(f.root,'new.jsonl'));
    f.observe(null);
    await f.handlers.get('session_switch')!({},f.ctx);
    expect(f.records()).toEqual([]);
    expect(f.writes.at(-1)?.session_id).toBe('real-id');
  } finally { rmSync(f.root,{recursive:true,force:true}); }
});

test('publisher uses shared precise kernel birth and fails closed on unavailable live identity', () => {
  const calls: string[][] = [];
  let response = JSON.stringify('darwin-bsd:1800000000:123456');
  const run = (python: string, args: string[]) => {
    calls.push([python,...args]);
    return {status:0,stdout:response};
  };
  expect(readProcessIdentity('/selected/python','/owned/terminal_identity.py',123,run))
    .toEqual({pid:123,process_start:'darwin-bsd:1800000000:123456'});
  response = JSON.stringify('darwin-bsd:1800000000:123457');
  expect(readProcessIdentity('/selected/python','/owned/terminal_identity.py',123,run))
    .toEqual({pid:123,process_start:'darwin-bsd:1800000000:123457'});
  response = 'null'; // Zombie/unsupported probe returns no live birth, not coarse ps data.
  expect(readProcessIdentity('/selected/python','/owned/terminal_identity.py',123,run)).toBeNull();
  response = JSON.stringify('Sun Jan 15 08:00:00 2027');
  expect(readProcessIdentity('/selected/python','/owned/terminal_identity.py',123,run)).toBeNull();
  expect(calls).toEqual(Array(4).fill(['/selected/python','/owned/terminal_identity.py','--process-start','123']));
});

test('unavailable shared live process authority cannot publish a stale main identity', async () => {
  const f = fixture();
  try {
    registerIdentity({on:(event,handler)=>f.handlers.set(event,handler)}, {
      ...f.options,
      process: () => readProcessIdentity('/selected/python','/owned/terminal_identity.py',123,
        () => ({status:0,stdout:'null'})),
    });
    await f.handlers.get('session_start')!({},f.ctx);
    expect(f.writes).toEqual([]);
    expect(readdirSync(f.root)).not.toContain('registry');
  } finally { rmSync(f.root,{recursive:true,force:true}); }
});

test.skipIf(process.platform !== 'darwin')('installed default entrypoint publishes only to own private PTY and cleans failed publication', () => {
  const driver = String.raw`
import fcntl,json,os,pathlib,pty,select,shutil,subprocess,sys,tempfile,termios,threading
from iterm2_utils.features.shell import identity_extension
from iterm2_utils.models import Context,OmpProfile,Paths,Selection
repo=pathlib.Path.cwd()
rows=[]
for scenario in ('own','mismatch','failure'):
  with tempfile.TemporaryDirectory(prefix='installed-identity-') as tmp:
    root=pathlib.Path(tmp).resolve()
    paths=Paths(root,root/'.zshrc',root/'config',root/'cache',root/'data',root/'profiles',repo)
    profile=OmpProfile('work',root/'.omp/profiles/work/agent')
    context=Context(paths,{'python3':pathlib.Path(sys.executable)},{},frozenset(),{},{},omp_profile=profile)
    selection=Selection(frozenset({'restore'}),frozenset(),'Default',profile)
    edit=identity_extension(context,selection).edits[0]
    edit.path.parent.mkdir(parents=True);edit.path.write_bytes(edit.after)
    helper=paths.data/'current/terminal_identity.py';helper.parent.mkdir(parents=True)
    shutil.copyfile(repo/'runtime/terminal_identity.py',helper)
    master,slave=pty.openpty();other_master,other_slave=pty.openpty()
    tty=os.ttyname(slave)
    if scenario!='own':
      destination=os.ttyname(other_slave) if scenario=='mismatch' else str(root/'missing-tty')
      helper.write_text('import json,sys\nsys.path.insert(0,'+repr(str(repo))+')\n'
        'from runtime.terminal_identity import process_start\n'
        'if sys.argv[1]=="--process-start": print(json.dumps(process_start(int(sys.argv[2]))))\n'
        'else: print(json.dumps('+repr(dict(terminal_id='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE',
          tab_id='tab',window_id='window',tty=destination))+'))\n')
    (root/'iterm2.py').write_text('''import os
from types import SimpleNamespace
class Session:
    session_id="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    async def async_get_variable(self,key):
        return os.environ["FIXTURE_TTY"] if key=="tty" else None
async def close(): pass
class Connection:
    @staticmethod
    async def async_create(): return SimpleNamespace(websocket=SimpleNamespace(close=close))
async def async_get_app(connection):
    return SimpleNamespace(terminal_windows=[SimpleNamespace(window_id="window",tabs=[
        SimpleNamespace(tab_id="tab",sessions=[Session()])])])
''')
    child=root/'exercise.ts'
    child.write_text('import identity from '+json.dumps(str(edit.path))+';\n'+'''
import { readdirSync, readFileSync } from "node:fs";
const handlers = new Map<string,Function>();
identity({on:(event,handler)=>handlers.set(event,handler)});
const ctx={mode:"tui",agent:{kind:"main"},sessionManager:{
 getSessionId:()=>"actual-dialog",getSessionFile:()=>undefined,getCwd:()=>process.env.HOME!}};
let failed=false;
try { await handlers.get("session_start")!({},ctx); } catch { failed=true; }
const directory=process.env.HOME+"/data/identity";
const names=readdirSync(directory).filter(n=>n.endsWith(".json"));
const records=names.map(n=>JSON.parse(readFileSync(directory+"/"+n,"utf8")));
await handlers.get("session_shutdown")!({},ctx);
console.log(JSON.stringify({failed,records,remaining:readdirSync(directory),pid:process.pid}));
''')
    env=dict(os.environ,HOME=str(root),ZDOTDIR=str(root),PYTHONPATH=str(root),
      FIXTURE_TTY=tty,ITERM_SESSION_ID='w0t0p0:AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE',
      TERM_SESSION_ID='AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE')
    def controlling_tty():
      os.setsid();fcntl.ioctl(0,termios.TIOCSCTTY,0)
    child_process=None;reader=None;finished=threading.Event();captured=bytearray()
    os.set_blocking(master,False)
    def drain():
      while not finished.is_set() or select.select([master],[],[],0)[0]:
        if select.select([master],[],[],.05)[0]:
          try:part=os.read(master,65536)
          except BlockingIOError:continue
          except OSError:break
          if not part:break
          captured.extend(part)
    try:
      child_process=subprocess.Popen([sys.argv[1],'--no-install','--no-env-file','--config=/dev/null',str(child)],
        stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env,preexec_fn=controlling_tty,cwd=root)
      (root/'child.pid').write_text(str(child_process.pid))
      # Darwin exit can wait for tty output; consume the master during communicate.
      reader=threading.Thread(target=drain);reader.start()
      stdout,stderr=child_process.communicate(timeout=8)
      if child_process.returncode:raise AssertionError((child_process.returncode,stdout,stderr))
      finished.set();reader.join(timeout=1)
      assert not reader.is_alive(),'fixture PTY reader did not finish'
      rows.append(dict(scenario=scenario,result=json.loads(stdout),osc=captured.decode('utf8')))
    finally:
      if child_process is not None and child_process.poll() is None:
        child_process.kill();child_process.wait(timeout=2)
      finished.set()
      if reader is not None:reader.join(timeout=1)
      for fd in (master,slave,other_master,other_slave):
        if fd is not None:os.close(fd)
print(json.dumps(rows))
`;
  const result = spawnSync('python3', ['-c', driver, process.execPath],
    { encoding:'utf8', timeout:28000, maxBuffer:65536, env:process.env });
  expect(result.status).toBe(0);
  if (result.status !== 0) throw new Error(result.stderr || String(result.error));
  const rows = JSON.parse(result.stdout);
  const own = rows[0];
  expect(own.result.failed).toBe(false);
  expect(own.result.records).toHaveLength(1);
  expect(own.result.remaining).toEqual([]);
  const match = /^\x1b\]1337;SetUserVar=iterm2_utils_omp=([A-Za-z0-9+/=]+)\x07$/.exec(own.osc);
  if (!match) throw new Error('Fixture PTY bytes: '+JSON.stringify(own.osc));
  expect(match).not.toBeNull();
  const published = JSON.parse(Buffer.from(match![1], 'base64').toString());
  expect(published).toEqual(own.result.records[0]);
  expect(published).toMatchObject({ session_id:'actual-dialog', session_file:null, pid:own.result.pid,
    terminal_id:terminal, tab_id:'tab', window_id:'window', profile:{name:'work'} });
  expect(published.process_start).toMatch(/^darwin-bsd:[1-9][0-9]*:[0-9]{6}$/);
  for (const row of rows.slice(1)) {
    expect(row.result.failed).toBe(true);
    expect(row.result.records).toEqual([]);
    expect(row.result.remaining).toEqual([]);
    expect(row.osc).toBe('');
  }
}, 30000);
