import { test, expect } from 'bun:test';
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { registerIdentity, readProcessIdentity, type IdentityContext, type Observation, type RecordValue } from '../runtime/omp_identity';

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
