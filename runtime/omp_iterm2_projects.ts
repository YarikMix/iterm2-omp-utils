// Local preview stays in the native dialog, never in tool output or logs.
import type { ExtensionAPI, ExtensionContext } from '@oh-my-pi/pi-coding-agent';
import { isAbsolute } from 'node:path';

export type ProjectChange = {operation:'add';name:string;path:string} |
  {operation:'rename';project:string;name:string} | {operation:'move';project:string;path:string} |
  {operation:'remove';project:string};
type Installation = {python:string;entry:string;profile:{name:string|null;agent_dir:string};receipt:string};
export type Worker = {stdin:{write(value:string):unknown;flush():unknown;end():unknown};stdout:ReadableStream<Uint8Array>;
  exited:Promise<number>;kill():unknown};
export type Options = Installation & {spawn?: (argv:string[],options:{stdin:'pipe';stdout:'pipe';stderr:'ignore'})=>Worker};
// Replaced by the transactional installer, not environment or model-controlled input.
function installation(): Installation { throw new Error('Install the profile-scoped projects extension first'); }
const limit = 65536;
const statuses = ['applied','blocked','conflict','declined','noop','rolled_back','unknown'];
function object(value:unknown): value is Record<string,unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function validChange(value:unknown): value is ProjectChange {
  if (!object(value) || typeof value.operation !== 'string') return false;
  const fields:Record<string,string[]> = {add:['operation','name','path'],rename:['operation','project','name'],
    move:['operation','project','path'],remove:['operation','project']};
  const keys=fields[value.operation];
  return Array.isArray(keys) && Object.keys(value).length===keys.length && keys.every(key=>
    typeof value[key]==='string' && !!value[key].trim() && value[key].length<=(key==='name'?256:4096) &&
    !/[\x00-\x1f\x7f]/.test(value[key])) && (!('path' in value) || isAbsolute(String(value.path)));
}
function validPreview(value:unknown): value is Record<string,unknown> {
  if (!object(value) || Object.keys(value).sort().join(',')!=='after,before,removes_launcher,status' ||
      value.status!=='ready' || typeof value.removes_launcher!=='boolean') return false;
  return [value.before,value.after].every(rows=>Array.isArray(rows) && rows.every(row=>object(row) &&
    Object.keys(row).sort().join(',')==='id,name,path' && ['id','name','path'].every(key=>
      typeof row[key]==='string' && !!row[key] && !/[\x00-\x1f\x7f]/.test(row[key]))));
}
async function bounded<T>(promise:Promise<T>, milliseconds:number, signal?:AbortSignal):Promise<T> {
  const waiting=Promise.withResolvers<T>();
  const abort=()=>waiting.reject(new Error('Cancelled'));
  const timer=setTimeout(abort,milliseconds);
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted) abort();
  promise.then(waiting.resolve,waiting.reject);
  try { return await waiting.promise; }
  finally { clearTimeout(timer);signal?.removeEventListener('abort',abort); }
}

export function registerProjects(api:Pick<ExtensionAPI,'registerTool'|'zod'>, options:Options) {
  const z=api.zod;
  const text=z.string().min(1).max(4096);
  const name=z.string().min(1).max(256);
  const parameters=z.union([
    z.object({operation:z.literal('add'),name,path:text}).strict(),
    z.object({operation:z.literal('rename'),project:text,name}).strict(),
    z.object({operation:z.literal('move'),project:text,path:text}).strict(),
    z.object({operation:z.literal('remove'),project:text}).strict(),
  ]);
  api.registerTool({name:'iterm2_project_edit',label:'Edit iTerm2 projects',approval:'write',
    description:'Edit an installed project button after a fresh local human confirmation. Move changes the button path, not files.',
    parameters,
    async execute(_id,change,signal,_update,ctx:ExtensionContext) {
      const result=(status:string)=>({content:[{type:'text' as const,text:JSON.stringify({status})}],details:{status}});
      if(ctx.mode!=='tui' || !ctx.hasUI || typeof ctx.ui?.confirm!=='function' || signal?.aborted ||
         !validChange(change) || ![options.python,options.entry,options.receipt,options.profile.agent_dir].every(isAbsolute)) return result('blocked');
      let child:Worker|undefined;let committed=false;let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
      try {
        const spawn=options.spawn ?? ((argv,stdio)=>Bun.spawn(argv,stdio));
        const prepareDeadline=Date.now()+60000;
        child=spawn([options.python,'-I',options.entry,'--project-worker','--omp-profile',options.profile.agent_dir,
          '--receipt',options.receipt],{stdin:'pipe',stdout:'pipe',stderr:'ignore'});
        reader=child.stdout.getReader();
        const frames:Record<string,unknown>[]=[];let error:unknown;let done=false;
        let wake=()=>{};
        const pump=(async()=>{
          let pending=new Uint8Array(0);
          try {
            while(true){
              const part=await reader!.read();
              if(part.done){if(pending.length)throw new Error('Partial frame');done=true;break;}
              if(pending.length+part.value.length>2*limit)throw new Error('Oversized output');
              const bytes=new Uint8Array(pending.length+part.value.length);bytes.set(pending);bytes.set(part.value,pending.length);
              let start=0;
              for(let end=0;end<bytes.length;end++)if(bytes[end]===10){
                if(end-start+1>limit || frames.length>=2)throw new Error('Oversized or extra frame');
                const frame:unknown=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(start,end)));
                if(!object(frame))throw new Error('Invalid frame');frames.push(frame);start=end+1;wake();
              }
              pending=bytes.slice(start);if(pending.length>=limit)throw new Error('Oversized frame');
            }
          }catch(failure){error=failure;}finally{wake();}
        })();
        const next=async(index:number)=>{
          while(!error && !done && frames.length<=index){
            const waiting=Promise.withResolvers<void>();wake=waiting.resolve;await waiting.promise;
          }
          if(error || frames.length<=index)throw new Error('Worker unavailable');return frames[index];
        };
        child.stdin.write(JSON.stringify({type:'prepare',change})+'\n');
        child.stdin.flush();
        const first=await bounded(next(0),Math.max(0,prepareDeadline-Date.now()),signal);
        if(Object.keys(first).join(',')==='result'){
          await bounded(pump,Math.max(0,prepareDeadline-Date.now()),signal);
          if(error || frames.length!==1 || !object(first.result) ||
             !['blocked','noop','conflict'].includes(String(first.result.status)))throw new Error('Invalid result');
          const guidance=first.result.status==='blocked' && first.result.reason==='handoff_requires_uninstall';
          if(Object.keys(first.result).sort().join(',')!==(guidance?'reason,status':'status'))throw new Error('Invalid result');
          if(guidance)await bounded(ctx.ui.confirm('Edit iTerm2 projects',
            'Use explicit uninstall to restore the original manual launcher.',{signal:signal??new AbortController().signal}),
            120000,signal);
          return result(String(first.result.status));
        }
        if(Object.keys(first).join(',')!=='preview' || !validPreview(first.preview))throw new Error('Invalid preview');
        let approved=false;
        const expiry=new AbortController();
        const confirmationDeadline=Date.now()+120000;
        const confirmation=AbortSignal.any([...(signal?[signal]:[]),expiry.signal]);
        const timer=setTimeout(()=>expiry.abort(),120000);
        try {
          // The host selector auto-selects Yes on its timeout; only our abort may expire approval.
          approved=await bounded(ctx.ui.confirm('Edit iTerm2 projects',JSON.stringify({change,...first.preview}),
            {signal:confirmation}),120000,confirmation)===true;
        }catch{} // Timeout, escape and abort all deny; no fallback approval.
        finally { clearTimeout(timer); }
        if(!approved || confirmation.aborted || Date.now()>=confirmationDeadline){child.stdin.end();return result('declined');}
        if(error || done || frames.length!==1)throw new Error('Extra frame before confirmation');
        committed=true;child.stdin.write('{"type":"commit"}\n');child.stdin.end();
        // After commit, cancellation is loss of observation, not proof of no write.
        const final=await bounded((async()=>{
          const frame=await next(1);await pump;
          if(error || frames.length!==2 || Object.keys(frame).join(',')!=='result' || !object(frame.result) ||
             Object.keys(frame.result).join(',')!=='status' || !statuses.includes(String(frame.result.status)) ||
             await child!.exited!==0)throw new Error('Invalid outcome');
          return String(frame.result.status);
        })(),60000);
        return result(final);
      }catch{return result(committed?'unknown':'blocked');}
      finally {
        try{child?.stdin.end();}catch{}
        if(!committed){try{child?.kill();}catch{}}
        // Never terminate an applying worker: preserve its journal and readback work.
        try{await reader?.cancel();}catch{}
      }
    }});
}
export default function projects(api:ExtensionAPI) { registerProjects(api,installation()); }
