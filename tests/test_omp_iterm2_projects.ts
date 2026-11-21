import { test, expect, spyOn } from 'bun:test';
import { registerProjects } from '../runtime/omp_iterm2_projects';
import type { ExtensionAPI } from '@oh-my-pi/pi-coding-agent';
type Context = {mode:string;hasUI:boolean;ui:{confirm?:(title:string,message:string,options:{timeout?:number;signal:AbortSignal})=>Promise<unknown>}};
type Tool = {name:string;approval:string;execute:(id:string,change:unknown,signal:AbortSignal|undefined,update:undefined,ctx:Context)=>Promise<{details:{status:string}}>};
const preview = {status:'ready', before:[{id:'a',name:'Private old',path:'/private/old'}],
  after:[{id:'a',name:'Private new',path:'/private/old'}], removes_launcher:false};
const change = {operation:'rename',project:'a',name:'Private new'};
async function fixture(realPipe=false, first:unknown={preview}, autoPreview=true) {
  let tool!: Tool; let count = 0; let controller!: ReadableStreamDefaultController<Uint8Array>;
  const writes: string[] = []; let ended = false; let killed = false;
  const {promise:exited,resolve:exit} = Promise.withResolvers<number>();
  const child = {stdout:new ReadableStream<Uint8Array>({start(c){controller=c;}}),
    stdin:{write(value:string){writes.push(value);},flush(){},end(){ended=true;}},
    exited,kill(){killed=true;exit(1);controller.close();}};
  const send = (value:unknown) => controller.enqueue(new TextEncoder().encode(JSON.stringify(value)+'\n'));
  // Schema construction is host-owned; execution must independently reject extra/model approval fields.
  const schema = new Proxy(()=>undefined,{get:()=>schema,apply:()=>schema});
  // The fake owns only host registration/schema construction, not edit execution.
  const api = {zod:schema,registerTool(value:Tool){tool=value;}} as unknown as Pick<ExtensionAPI,'zod'|'registerTool'>;
  registerProjects(api, {
    python:'/fixture/python',entry:'/fixture/entry',profile:{name:'work',agent_dir:'/fixture/agent'},receipt:'/fixture/receipt.json',
    spawn(argv, options){
      if(realPipe){
        const script=`
          const timer=setTimeout(()=>process.exit(1),500);
          const lines=[];
          const rl=require('node:readline').createInterface({input:process.stdin});
          rl.on('line',line=>{
            lines.push(JSON.parse(line));
            if(lines.length===1)process.stdout.write(JSON.stringify({preview:${JSON.stringify(preview)}})+'\\n');
          });
          rl.on('close',()=>{
            clearTimeout(timer);
            if(lines.length===2 && lines[0].type==='prepare' && lines[1].type==='commit')
              process.stdout.write('{"result":{"status":"applied"}}\\n');
            else process.exitCode=1;
          });
        `;
        return Bun.spawn([process.execPath,'-e',script],options);
      }
      count++; expect(argv).toEqual(['/fixture/python','-I','/fixture/entry','--project-worker','--omp-profile','/fixture/agent','--receipt','/fixture/receipt.json']);
      expect(options.stderr).toBe('ignore'); if(autoPreview)queueMicrotask(()=>send(first)); return child;
    }});
  const ctx:Context={mode:'tui',hasUI:true,ui:{confirm:async()=>false}};
  const run=(signal?:AbortSignal,args:unknown=change)=>tool.execute('call',args,signal,undefined,ctx);
  return {tool,ctx,run,writes,send,sendBytes:(bytes:Uint8Array)=>controller.enqueue(bytes),
    get count(){return count;},get ended(){return ended;},get killed(){return killed;},
    finish(status='applied'){send({result:{status}});controller.close();exit(0);},
    lost(){controller.close();exit(1);}};
}
const tick = async () => { await Bun.sleep(0); };

test('requires native TUI and one human approval',async()=>{
  const f=await fixture();
  expect(f.tool.name).toBe('iterm2_project_edit'); expect(f.tool.approval).toBe('write');
  for(const patch of [{mode:'rpc'},{hasUI:false},{ui:{}}]){
    const old={...f.ctx};Object.assign(f.ctx,patch);
    expect((await f.run()).details.status).toBe('blocked');Object.assign(f.ctx,old);
  }
  expect((await f.run(undefined,{...change,confirm:true})).details.status).toBe('blocked');
  expect(f.count).toBe(0);
  const {promise:answer,resolve:approve} = Promise.withResolvers<boolean>();
  f.ctx.ui.confirm=(title,message,options)=>{
    expect(title).toBe('Edit iTerm2 projects');
    expect(JSON.parse(message)).toEqual({change,...preview});
    expect(options.timeout).toBeUndefined();expect(options.signal).toBeInstanceOf(AbortSignal);
    return answer;
  };
  const running=f.run();await tick();
  expect(f.writes).toEqual([JSON.stringify({type:'prepare',change})+'\n']);
  approve(true);await tick();
  expect(f.writes).toEqual([JSON.stringify({type:'prepare',change})+'\n','{"type":"commit"}\n']);
  expect(f.ended).toBe(true);f.finish();
  const result=await running;expect(result.details).toEqual({status:'applied'});
  expect(JSON.stringify(result)).not.toContain('Private');expect(f.count).toBe(1);
});

test('denial, confirmation timeout and abort send EOF without commit',async()=>{
  for(const answer of ['false','throw','abort','not-boolean']){
    const f=await fixture();const abort=new AbortController();
    f.ctx.ui.confirm=async()=>{
      if(answer==='throw')throw new Error('timeout private data');
      if(answer==='abort'){abort.abort();return true;}
      return answer==='not-boolean'?'yes':false;
    };
    const result=await f.run(abort.signal);
    expect(result.details.status).toBe('declined');expect(f.writes).toHaveLength(1);expect(f.ended).toBe(true);
  }
  const f=await fixture();const abort=new AbortController();abort.abort();
  expect((await f.run(abort.signal)).details.status).toBe('blocked');expect(f.count).toBe(0);
});

test('does not repeat after uncertain apply',async()=>{
  const f=await fixture();f.ctx.ui.confirm=async()=>true;
  const running=f.run();await tick();f.lost();
  expect((await running).details.status).toBe('unknown');expect(f.count).toBe(1);
  expect(f.writes.filter(x=>x.includes('commit'))).toHaveLength(1);expect(f.killed).toBe(false);
});

test('abort after commit preserves a still knowable outcome',async()=>{
  const f=await fixture();const abort=new AbortController();f.ctx.ui.confirm=async()=>true;
  const running=f.run(abort.signal);await tick();abort.abort();f.finish('rolled_back');
  expect((await running).details.status).toBe('rolled_back');expect(f.killed).toBe(false);
});

test('real Bun pipes deliver prepare while stdin remains open',async()=>{
  const f=await fixture(true);f.ctx.ui.confirm=async()=>true;
  expect((await f.run()).details.status).toBe('applied');
});

test('malformed and extra previews never authorize a write',async()=>{
  for(const first of [null,{preview:{...preview,extra:'secret'}},{preview:{...preview,before:'bad'}}]){
    const f=await fixture(false,first);f.ctx.ui.confirm=async()=>{throw new Error('must not ask');};
    expect((await f.run()).details.status).toBe('blocked');
    expect(f.writes).toHaveLength(1);
  }
  const f=await fixture();const answer=Promise.withResolvers<boolean>();
  f.ctx.ui.confirm=()=>answer.promise;
  const running=f.run();await tick();f.send({result:{status:'applied'}});await tick();answer.resolve(true);
  expect((await running).details.status).toBe('blocked');expect(f.writes).toHaveLength(1);
});

test('abort during prepare or pending confirmation closes without committing',async()=>{
  for(const autoPreview of [false,true]){
    const f=await fixture(false,{preview},autoPreview);const abort=new AbortController();
    f.ctx.ui.confirm=()=>Promise.withResolvers<boolean>().promise;
    const running=f.run(abort.signal);await tick();abort.abort();
    expect(['blocked','declined']).toContain((await running).details.status);
    expect(f.writes).toHaveLength(1);expect(f.ended).toBe(true);
  }
  const f=await fixture();
  expect((await f.run(undefined,{operation:'__proto__'})).details.status).toBe('blocked');expect(f.count).toBe(0);
});

async function microtasks() {
  for(let i=0;i<30;i++)await Promise.resolve();
}

function controlledClock() {
  let now=0;
  const originalSet=setTimeout, originalClear=clearTimeout;
  const timers=new Map<ReturnType<typeof setTimeout>,{at:number;run:()=>void}>();
  const date=spyOn(Date,'now').mockImplementation(()=>now);
  const set=spyOn(globalThis,'setTimeout').mockImplementation((callback,delay,...args)=>{
    // A disposed native handle preserves Bun's timer type; only this fixture drives callbacks.
    const handle=originalSet(()=>{},2147483647);originalClear(handle);
    timers.set(handle,{at:now+Number(delay??0),run:()=>callback(...args)});
    return handle;
  });
  const clear=spyOn(globalThis,'clearTimeout').mockImplementation(handle=>{
    if(handle!==undefined)timers.delete(handle);
  });
  return {
    async advance(milliseconds:number){
      const until=now+milliseconds;
      while(true){
        const next=[...timers].filter(([,timer])=>timer.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];
        if(!next)break;
        now=next[1].at;timers.delete(next[0]);next[1].run();
        // Real timers drain promise jobs between callbacks, including equal-deadline callbacks.
        await microtasks();
      }
      now=until;await microtasks();
    },
    restore(){set.mockRestore();clear.mockRestore();date.mockRestore();},
  };
}

test('valid oversized previews, whole and split, never reach the dialog',async()=>{
  for(const split of [false,true]){
    const f=await fixture(false,undefined,false);let dialogs=0;
    f.ctx.ui.confirm=async()=>{dialogs++;return true;};
    const running=f.run();
    const oversized={preview:{...preview,after:[{id:'a',name:'Private new',path:'/'+ 'p'.repeat(66000)}]}};
    const bytes=new TextEncoder().encode(JSON.stringify(oversized)+'\n');
    expect(bytes.length).toBeGreaterThan(65536);
    if(split){
      f.sendBytes(bytes.subarray(0,35000));await microtasks();
      expect(dialogs).toBe(0);expect(f.writes).toHaveLength(1);
      f.sendBytes(bytes.subarray(35000));
    }else f.sendBytes(bytes);
    expect((await running).details.status).toBe('blocked');
    expect(dialogs).toBe(0);expect(f.writes).toHaveLength(1);
  }
});

test('elapsed confirmation deadline denies host auto-yes and late true without equal-timer ordering',async()=>{
  const clock=controlledClock();
  try{
    const f=await fixture();const answer=Promise.withResolvers<boolean>();
    let nativeTimeout:number|undefined;let dialogSignal:AbortSignal|undefined;
    f.ctx.ui.confirm=(_title,_message,options)=>{
      nativeTimeout=options.timeout;dialogSignal=options.signal;
      // Model the installed host: its own selector timeout auto-selects the initial Yes.
      if(options.timeout!==undefined)setTimeout(()=>answer.resolve(true),options.timeout);
      options.signal.addEventListener('abort',()=>answer.resolve(true),{once:true});
      return answer.promise;
    };
    let status:string|undefined;
    const running=f.run().then(result=>status=result.details.status);await microtasks();
    await clock.advance(119999);expect(f.writes).toHaveLength(1);expect(status).toBeUndefined();
    await clock.advance(1);
    const atDeadline={status,commits:f.writes.filter(line=>line.includes('commit')).length,aborted:dialogSignal?.aborted};
    // Bounded cleanup also lets a broken implementation finish rather than hang the test.
    if(atDeadline.commits)f.finish();
    answer.resolve(true);await microtasks();await running;
    expect(nativeTimeout).toBeUndefined();
    expect(atDeadline).toEqual({status:'declined',commits:0,aborted:true});
    expect(f.writes).toHaveLength(1);expect(f.ended).toBe(true);
  }finally{clock.restore();}
});

test('elapsed prepare deadline closes helper without dialog or commit',async()=>{
  const clock=controlledClock();
  try{
    const f=await fixture(false,undefined,false);const abort=new AbortController();let dialogs=0;let status:string|undefined;
    f.ctx.ui.confirm=async()=>{dialogs++;return true;};
    const running=f.run(abort.signal).then(result=>status=result.details.status);await microtasks();
    await clock.advance(59999);expect(status).toBeUndefined();expect(f.killed).toBe(false);
    await clock.advance(1);const atDeadline=status;
    abort.abort();await running;
    expect(atDeadline).toBe('blocked');expect(dialogs).toBe(0);
    expect(f.writes).toHaveLength(1);expect(f.ended).toBe(true);expect(f.killed).toBe(true);
  }finally{clock.restore();}
});

test('elapsed apply deadline returns unknown without retry or kill',async()=>{
  const clock=controlledClock();
  try{
    const f=await fixture();let status:string|undefined;f.ctx.ui.confirm=async()=>true;
    const running=f.run().then(result=>status=result.details.status);await microtasks();
    expect(f.writes.filter(line=>line.includes('commit'))).toHaveLength(1);
    await clock.advance(59999);expect(status).toBeUndefined();expect(f.killed).toBe(false);
    await clock.advance(1);const atDeadline=status;
    if(status===undefined)f.finish();await running;
    expect(atDeadline).toBe('unknown');expect(f.killed).toBe(false);expect(f.count).toBe(1);
    expect(f.writes.filter(line=>line.includes('commit'))).toHaveLength(1);
  }finally{clock.restore();}
});

test('true resolving after elapsed confirmation expiration cannot commit',async()=>{
  const clock=controlledClock();
  try{
    const f=await fixture();const answer=Promise.withResolvers<boolean>();let status:string|undefined;
    f.ctx.ui.confirm=()=>answer.promise; // Even a UI that ignores abort must not extend approval.
    const running=f.run().then(result=>status=result.details.status);await microtasks();
    await clock.advance(120000);const atDeadline=status;
    answer.resolve(true);await microtasks();await running;
    expect(atDeadline).toBe('declined');expect(f.writes).toHaveLength(1);expect(f.ended).toBe(true);
  }finally{clock.restore();}
});
