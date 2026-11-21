const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function harness(saved){
  let time=0,id=0;const timers=new Map(),medias=[],events=[],stored=new Map();
  if(saved)stored.set('grdag_immersive_audio',JSON.stringify(saved));
  const ctx=vm.createContext({URL,setTimeout,clearTimeout,setInterval,clearInterval});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/immersive-audio.js'),'utf8'),ctx);
  const schedule=(fn,ms)=>{timers.set(++id,{fn,ms,at:time+ms});return id};
  const repeat=(fn,ms)=>{const i=++id;timers.set(i,{fn,ms,at:time+ms,repeat:true});return i};
  const controller=ctx.ArchiveV2.audio.create({storage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},now:()=>time,schedule,unschedule:i=>timers.delete(i),repeat,unrepeat:i=>timers.delete(i),onChange:s=>events.push(s),mediaFactory:()=>{
    const audio={currentTime:0,duration:100,paused:true,volume:0,playCalls:0,load(){this.currentTime=0},pause(){this.paused=true},removeAttribute(){this.src=''},play(){this.playCalls++;this.paused=false;this.onloadedmetadata?.();return new Promise((resolve,reject)=>{this.finish=resolve;this.fail=reject})}};medias.push(audio);return audio;
  }});
  async function tick(ms){
    const end=time+ms;let guard=0;
    while(true){
      const due=[...timers].filter(([,timer])=>timer.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];
      if(!due)break;
      if(++guard>10000)throw Error('fake clock did not settle');
      const [timerId,timer]=due;time=timer.at;
      if(timer.repeat)timer.at+=timer.ms;else timers.delete(timerId);
      timer.fn();await Promise.resolve();
    }
    time=end;await Promise.resolve();await Promise.resolve();
  }
  return {controller,medias,timers,stored,events,tick,audio:ctx.ArchiveV2.audio};
}
const a={src:'https://example.com/a.mp3',title:'A'},b={src:'https://example.com/b.mp3',title:'B'};
test('music resolves member first and inherits series only within series context',()=>{
  const {audio}=harness();
  assert.equal(audio.resolve({bgm:a},{bgm:b}).src,a.src);
  assert.equal(audio.resolve({}, {bgm:b}).owner,'沿用系列音乐');
  assert.equal(audio.resolve({},null),null);
  assert.equal(audio.resolve({bgm:a},{bgm:b},true).src,b.src);
  for(const src of ['javascript:alert(1)','file:///x','/audio/../x','https://u:p@example.com/'])assert.equal(audio.source(src),'');
});
test('default is off; enabling plays, fades, preserves same source, and remembers preferences',async()=>{
  const h=harness();h.controller.setTarget(a);assert.equal(h.medias[0].playCalls,0);
  h.controller.toggle();const media=h.medias.find(m=>m.playCalls);media.finish();await h.tick(0);await h.tick(1000);
  assert.equal(h.controller.snapshot().state,'playing');assert.equal(media.volume,.2);
  media.currentTime=18;h.controller.setTarget({...a,title:'renamed'});assert.equal(media.playCalls,1);assert.equal(media.currentTime,18);
  h.controller.setVolume(.35);assert.equal(media.volume,.35);assert.equal(JSON.parse(h.stored.get('grdag_immersive_audio')).volume,.35);
  h.controller.destroy();assert.equal(h.timers.size,0);
});
test('pause remains across navigation and explicit play resumes current target',async()=>{
  const h=harness({enabled:true});h.controller.setTarget(a);h.medias[0].finish();await h.tick(1000);await h.tick(1000);
  h.controller.toggle();h.controller.setTarget(b);assert.equal(h.controller.snapshot().state,'paused');assert.equal(h.medias.reduce((n,m)=>n+m.playCalls,0),1);
  h.controller.toggle();const media=h.medias.find(m=>m.src===b.src);media.finish();await h.tick(0);assert.equal(h.controller.snapshot().state,'playing');h.controller.destroy();
});
test('switching fades and restores per-track position; stale play completion cannot revive previous track',async()=>{
  const h=harness({enabled:true});h.controller.setTarget(a);const first=h.medias[0];first.finish();await h.tick(0);await h.tick(1000);first.currentTime=24;
  h.controller.setTarget(b);const stale=h.medias[1].finish;await h.tick(1000);assert.equal(first.paused,true);
  h.controller.setTarget(a);const restored=h.medias[0];assert.equal(restored.currentTime,24);stale();await h.tick(0);assert.equal(h.controller.snapshot().state,'loading');restored.finish();await h.tick(0);assert.equal(h.controller.snapshot().state,'playing');h.controller.destroy();
});
test('autoplay rejection offers retry and visibility respects explicit pause',async()=>{
  const h=harness({enabled:true});h.controller.setTarget(a);h.medias[0].fail({name:'NotAllowedError'});await h.tick(0);
  assert.equal(h.controller.snapshot().state,'blocked');h.controller.toggle();h.medias[0].finish();await h.tick(0);await h.tick(1000);
  h.controller.visibility(true);assert.equal(h.controller.snapshot().state,'hidden');assert.equal(h.medias[0].paused,true);
  h.controller.visibility(false);h.medias[0].finish();await h.tick(0);h.controller.toggle();h.controller.visibility(true);h.controller.visibility(false);
  assert.equal(h.controller.snapshot().state,'paused');h.controller.destroy();
});
test('failed or missing tracks stop old music, timeout ends loading, and closing clears timers',async()=>{
  const h=harness({enabled:true});h.controller.setTarget(a);h.medias[0].finish();await h.tick(0);await h.tick(1000);
  h.controller.setTarget(null);await h.tick(1000);assert.equal(h.medias[0].paused,true);assert.equal(h.controller.snapshot().state,'empty');
  h.controller.setTarget(b);await h.tick(15000);assert.equal(h.controller.snapshot().state,'error');
  h.controller.close();await h.tick(1000);assert.equal(h.timers.size,0);assert.ok(h.medias.every(m=>m.paused));
});
