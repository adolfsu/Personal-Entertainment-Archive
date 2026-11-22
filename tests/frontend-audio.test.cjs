const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function harness(saved,hooks={}){
  let time=0,id=0;const timers=new Map(),medias=[],events=[],stored=new Map();
  if(saved)stored.set('grdag_immersive_audio',JSON.stringify(saved));
  const ctx=vm.createContext({URL,setTimeout,clearTimeout,setInterval,clearInterval});
  vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/immersive-audio.js'),'utf8'),ctx);
  const schedule=(fn,ms)=>{timers.set(++id,{fn,ms,at:time+ms});return id};
  const repeat=(fn,ms)=>{const i=++id;timers.set(i,{fn,ms,at:time+ms,repeat:true});return i};
  const controller=ctx.ArchiveV2.audio.create({storage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},now:()=>time,schedule,unschedule:i=>timers.delete(i),repeat,unrepeat:i=>timers.delete(i),onChange:s=>events.push(s),...hooks,mediaFactory:()=>{
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
test('automatic playlist exposes song, performer, bound work, and category fields',()=>{
  const {audio}=harness();
  const tracks=audio.playlist([
    {id:'anime',title:'星海',category:'anime',bgm:{src:a.src,title:'片尾曲',artist:'歌手甲'}},
    {id:'game',title:'远行',category:'game',bgm:{src:b.src,title:'主题曲',artist:'歌手乙'}},
    {id:'empty',title:'无音乐',category:'book'},
  ],[{id:'series',name:'旅程系列',members:[{id:'game'}],bgm:{src:'https://example.com/series.mp3',title:'系列曲',artist:'歌手丙'}}]);
  assert.equal(tracks.length,3);
  assert.deepEqual([tracks[0].title,tracks[0].artist,tracks[0].workTitle,tracks[0].category],['片尾曲','歌手甲','星海','anime']);
  assert.equal(tracks[2].workId,'game');
  assert.deepEqual(Array.from(tracks.filter(track=>track.category==='game'),track=>track.id),['work:game','series:series']);
});

test('global mode owns playback independently of immersive target changes and closing views',async()=>{
  const h=harness(),tracks=[{id:'a',...a,workId:'a'},{id:'b',...b,workId:'b'}];
  h.controller.setCatalog(tracks);h.controller.setQueue(tracks);h.controller.setMode('global');
  const media=h.medias.find(item=>item.playCalls);assert.ok(media);media.finish();await h.tick(0);
  h.controller.setTarget({src:'https://example.com/immersive.mp3',title:'沉浸曲'});
  assert.equal(h.controller.snapshot().track.id,'a');
  assert.equal(h.medias.reduce((count,item)=>count+item.playCalls,0),1);
  h.controller.close();assert.equal(h.controller.snapshot().state,'playing');h.controller.destroy();
});

test('playlist playback navigates to bound works, advances on track end, and shuffles without repeating',async()=>{
  const navigation=[],h=harness(null,{onNavigate:track=>navigation.push(track.workId)});
  const tracks=[{id:'a',...a,workId:'a'},{id:'b',...b,workId:'b'},{id:'c',src:'https://example.com/c.mp3',title:'C',workId:'c'}];
  h.controller.setCatalog(tracks);h.controller.setQueue(tracks);h.controller.setMode('playlist');
  assert.equal(navigation.at(-1),'a');
  const first=h.medias.find(item=>item.playCalls);first.finish();await h.tick(0);first.onended();
  assert.equal(navigation.at(-1),'b');assert.notEqual(h.controller.snapshot().currentIndex,0);
  h.controller.setShuffle(true);const before=h.controller.snapshot().currentIndex;h.controller.next();
  assert.notEqual(h.controller.snapshot().currentIndex,before);
  assert.equal(navigation.length,3);h.controller.destroy();
});
test('immersive binding auto-plays; the shared player fades and remembers preferences',async()=>{
  const h=harness();h.controller.setTarget(a);const media=h.medias.find(m=>m.playCalls);assert.ok(media);
  media.finish();await h.tick(0);await h.tick(1000);
  assert.equal(h.controller.snapshot().state,'playing');assert.equal(media.volume,.2);
  media.currentTime=18;h.controller.setTarget({...a,title:'renamed'});assert.equal(media.playCalls,1);assert.equal(media.currentTime,18);
  h.controller.setVolume(.35);assert.equal(media.volume,.35);assert.equal(JSON.parse(h.stored.get('grdag_audio_player')).volume,.35);
  h.controller.destroy();assert.equal(h.timers.size,0);
});
test('immersive playback does not advance the playlist when a bound song ends',async()=>{
  const h=harness({enabled:true,loop:false}),tracks=[{id:'a',...a},{id:'b',...b}];
  h.controller.setCatalog(tracks);h.controller.setQueue(tracks);h.controller.setTarget(a);
  const media=h.medias.find(item=>item.playCalls);media.finish();await h.tick(0);
  media.onended();assert.equal(h.controller.snapshot().state,'ended');
  assert.equal(h.controller.snapshot().currentIndex,0);assert.equal(h.medias.reduce((n,item)=>n+item.playCalls,0),1);
  h.controller.destroy();
});
test('changing playlist filters keeps the active track and playback position',async()=>{
  const h=harness({mode:'global'}),tracks=[{id:'a',...a},{id:'b',...b}];
  h.controller.setCatalog(tracks);h.controller.setQueue(tracks);
  const media=h.medias.find(item=>item.playCalls);media.finish();await h.tick(0);media.currentTime=32;
  h.controller.setQueue([{id:'a',...a}]);
  assert.equal(h.controller.snapshot().track.id,'a');assert.equal(h.controller.snapshot().state,'playing');
  assert.equal(h.medias.reduce((n,item)=>n+item.playCalls,0),1);h.controller.destroy();
});
test('catalog refreshes do not autoplay; deliberate track selection starts playback',async()=>{
  const h=harness({mode:'global',enabled:false}),tracks=[{id:'a',...a},{id:'b',...b}];
  h.controller.setCatalog(tracks);
  assert.equal(h.medias.reduce((n,item)=>n+item.playCalls,0),0);
  h.controller.setQueue([tracks[1]]);
  assert.equal(h.medias.reduce((n,item)=>n+item.playCalls,0),0);
  h.controller.playTrack('b');
  assert.equal(h.medias.reduce((n,item)=>n+item.playCalls,0),1);
  h.controller.destroy();
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
