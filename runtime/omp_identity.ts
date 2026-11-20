// Identity only: no completion/status/notification policy and no private omp imports.
import { randomUUID } from 'node:crypto';
import { closeSync, constants, fstatSync, linkSync, lstatSync, mkdirSync, openSync, unlinkSync, writeFileSync, writeSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { spawnSync } from 'node:child_process';

type Profile = { name: string | null; agent_dir: string };
export type IdentityContext = { mode?: string; agent?: { kind: string; depth?: number };
  sessionManager: { getSessionId(): string; getSessionFile(): string | undefined; getCwd(): string } };
export type Observation = { terminal_id: string; tab_id: string | null; window_id: string | null; tty: string };
export type RecordValue = {
  schema: number; terminal_id: string; tab_id: string | null; window_id: string | null;
  session_file: string | null; session_id: string; cwd: string; profile: Profile;
  pid: number; process_start: string; generation: string };
type API = { on(event: string, handler: (event: unknown, ctx: IdentityContext) => Promise<void>): void };
type Options = { registry: string; profile: Profile;
  process(): { pid: number; process_start: string } | null;
  observe(): Observation | null;
  publish(tty: string, value: RecordValue): void };
type Installation = { registry: string; profile: Profile; python: string; helper: string };
// Replaced by the transactional installer, not a user config or environment override.
function installation(): Installation { throw new Error('Install the profile-scoped identity extension first'); }

function privateDirectory(path: string) {
  if (!isAbsolute(path)) throw new Error('Identity registry must be absolute');
  // Reject symlink ancestors, not just the final directory.
  let current = '/';
  for (const part of path.split('/').filter(Boolean)) {
    current = join(current, part);
    try { if (!lstatSync(current).isDirectory()) throw new Error('Unsafe registry ancestor'); }
    catch (error) {
      if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
      mkdirSync(current, { mode: 0o700 });
    }
  }
  const info = lstatSync(path);
  if ((info.mode & 0o777) !== 0o700 || info.uid !== process.getuid?.()) throw new Error('Registry is not private');
}

export function registerIdentity(api: API, options: Options) {
  const instance = randomUUID();
  let owned: string | undefined;
  const remove = () => {
    if (owned) { try { unlinkSync(owned); } catch (error) {
      if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
    } owned = undefined; }
  };
  const update = async (_event: unknown, ctx: IdentityContext) => {
    if (ctx.mode !== 'tui' || ctx.agent?.kind !== 'main') return;
    remove(); // A failed switch must not leave the prior dialog looking live.
    const processIdentity = options.process();
    const observation = options.observe();
    if (!processIdentity || !observation?.tty || !isAbsolute(observation.tty)) { remove(); return; }
    const sid = ctx.sessionManager.getSessionId();
    const file = ctx.sessionManager.getSessionFile();
    const cwd = ctx.sessionManager.getCwd();
    if (!sid || !isAbsolute(cwd) || file !== undefined && !isAbsolute(file)) { remove(); return; }
    privateDirectory(options.registry);
    const generation = randomUUID();
    const record: RecordValue = { schema:1, terminal_id:observation.terminal_id,
      tab_id:observation.tab_id, window_id:observation.window_id, session_file:file ?? null,
      session_id:sid, cwd, profile:options.profile, ...processIdentity, generation };
    const destination = join(options.registry, instance+'-'+generation+'.json');
    const temporary = destination+'.tmp';
    const fd = openSync(temporary, constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW, 0o600);
    try { writeFileSync(fd, JSON.stringify(record)+'\n'); } finally { closeSync(fd); }
    let created = false;
    try {
      // Random generation names never overwrite a foreign path or another process.
      if (exists(destination)) throw new Error('Identity record collision');
      linkSync(temporary,destination);
      created = true;
      unlinkSync(temporary);
      options.publish(observation.tty,record);
      remove();
      owned = destination;
    } catch (error) {
      try { unlinkSync(temporary); } catch {}
      if (created) { try { unlinkSync(destination); } catch {} }
      throw error;
    }
  };
  for (const event of ['session_start','session_switch','session_branch']) api.on(event,update);
  api.on('session_shutdown', async (_event,ctx) => {
    if (ctx.mode === 'tui' && ctx.agent?.kind === 'main') remove();
    // Do not clear terminal variables: another generation may already own them.
    // A variable without a matching private live record is never evidence.
  });
}
function exists(path: string) {
  try { lstatSync(path); return true; } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return false;
    throw error;
  }
}
function observation(value: unknown): value is Observation {
  if (!value || typeof value !== 'object') return false;
  return 'terminal_id' in value && typeof value.terminal_id === 'string' &&
    /^[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}$/.test(value.terminal_id) &&
    'tty' in value && typeof value.tty === 'string' && isAbsolute(value.tty) &&
    'tab_id' in value && typeof value.tab_id === 'string' &&
    'window_id' in value && typeof value.window_id === 'string';
}
type ProcessRunner = (python: string, args: string[]) => { status: number | null; stdout: string };
export function readProcessIdentity(python: string, helper: string, pid: number,
  run: ProcessRunner = (binary,args) => spawnSync(binary,args,{encoding:'utf8',timeout:2000,maxBuffer:4096})) {
  // One Python/kernel authority for both publication and registry consumption.
  const result = run(python,[helper,'--process-start',String(pid)]);
  if (result.status !== 0) return null;
  try {
    const birth: unknown = JSON.parse(result.stdout);
    return typeof birth === 'string' && /^darwin-bsd:[1-9][0-9]*:[0-9]{6}$/.test(birth)
      ? {pid,process_start:birth} : null;
  } catch { return null; }
}
export default function identity(api: API) {
  const install = installation();
  registerIdentity(api, { registry:install.registry, profile:install.profile,
    process: () => readProcessIdentity(install.python,install.helper,process.pid),
    observe: () => {
      // readlink of fd 0 would resolve /dev/tty aliases inconsistently; tty(1) asks the fd itself.
      const ownTTY = spawnSync('/usr/bin/tty',[],{encoding:'utf8',stdio:[0,'pipe','pipe'],timeout:2000});
      if (ownTTY.status !== 0) return null;
      const result = spawnSync(install.python,[install.helper,String(process.pid),ownTTY.stdout.trim()],
        {encoding:'utf8',timeout:6000,maxBuffer:65536});
      if (result.status !== 0) return null;
      try { const value: unknown = JSON.parse(result.stdout); return observation(value) ? value : null; }
      catch { return null; }
    },
    publish: (tty,record) => {
      const fd = openSync(tty,constants.O_WRONLY|constants.O_NOFOLLOW|constants.O_NONBLOCK);
      try {
        const info = fstatSync(fd);
        if (!info.isCharacterDevice() || info.rdev !== fstatSync(0).rdev) throw new Error('TTY changed');
        const encoded = Buffer.from(JSON.stringify(record)).toString('base64');
        writeSync(fd,'\x1b]1337;SetUserVar=iterm2_utils_omp='+encoded+'\x07');
      } finally { closeSync(fd); }
    } });
}
