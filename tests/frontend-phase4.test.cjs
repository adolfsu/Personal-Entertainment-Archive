const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function context() {
  const ctx = vm.createContext({URL,setTimeout,clearTimeout});
  for (const name of ['immersive-background.js','series-immersive.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',name),'utf8'),ctx);
  return ctx.ArchiveV2;
}
test('series background pool includes all member media, legacy URLs, and series artwork without duplicates',()=>{
  const {seriesImmersive:s}=context();
  const works=[{id:'a',category:'game',immersiveBackgroundUrls:['https://example.com/a','https://example.com/b']},
    {id:'b',category:'novel'}, {id:'c',category:'anime',immersiveBackgroundUrl:'https://example.com/a'}];
  const series={immersiveBackgroundUrls:['https://example.com/s'],members:[{id:'b'},{id:'c'},{id:'gone'},{id:'a'}]};
  const before=JSON.stringify([series,works]);
  assert.deepEqual(Array.from(s.members(series,id=>works.find(w=>w.id===id)),w=>w.id),['b','c','a']);
  assert.deepEqual(Array.from(s.pool(series,works)),['https://example.com/s','https://example.com/a','https://example.com/b']);
  assert.equal(JSON.stringify([series,works]),before);
  assert.equal(s.images({immersiveBackgroundUrls:['javascript:alert(1)','https://user:pass@example.com/']}).length,0);
});
test('cross-media search preserves member order; series content distinguishes ratings and escapes text',()=>{
  const {seriesImmersive:s}=context();
  const works=[{id:'a',title:'<漫画>',category:'manga',rating:0},{id:'b',title:'书',originalTitle:'Book',category:'book'}];
  const labels=w=>({category:w.category,status:'计划中'});
  assert.deepEqual(Array.from(s.select(works,'all','book'),w=>w.id),['b']);
  assert.deepEqual(Array.from(s.select(works,'manga',''),w=>w.id),['a']);
  const html=s.content({name:'<系列>',rating:9,avgRating:0,memberCount:2,ratedCount:1},works,labels,{category:'all',query:'',matchedIds:['a']});
  assert.match(html,/&lt;系列&gt;/);assert.match(html,/&lt;漫画&gt;/);
  assert.match(html,/系列个人评分/);assert.match(html,/成员均分/);assert.match(html,/>0.0</);
  assert.match(html,/首页筛选匹配 1 \/ 2/);
  assert.equal((html.match(/data-im-member=/g)||[]).length,2);
});
function harness(){
  const {backgrounds,seriesImmersive}=context(),timers=new Map(),images=[],displayed=[];let seq=0;
  const schedule=(fn,ms)=>{timers.set(++seq,{fn,ms});return seq},unschedule=id=>timers.delete(id);
  const loader=backgrounds.createLoader({schedule,unschedule,imageFactory:()=>{const image={naturalWidth:200,naturalHeight:100,removeAttribute(){}};images.push(image);return image}});
  const controller=seriesImmersive.createBackgrounds({loader,schedule,unschedule});
  const tick=ms=>{const [id,t]=[...timers].find(([,t])=>t.ms===ms)||[];assert.ok(t,`missing ${ms} ms timer`);timers.delete(id);t.fn()};
  return {controller,images,timers,displayed,tick,start:(series,works)=>controller.start(series,works,(img,kind)=>displayed.push([img?.src||null,kind]),{immersive_background_interval:5})};
}
test('hover waits, uses member images, and a member without artwork resumes the shared position',()=>{
  const h=harness(),a={id:'a',immersiveBackgroundUrls:['https://example.com/a','https://example.com/b']},b={id:'b',immersiveBackgroundUrl:'https://example.com/c'},book={id:'book'};
  h.start({},[a,b,book]);h.images.at(-1).onload();h.tick(5000);h.images.at(-1).onload();
  assert.equal(h.controller.current().sharedUrl,'https://example.com/b');
  h.controller.preview(a);h.controller.preview(b);h.tick(300);
  assert.equal(h.images.at(-1).src,'https://example.com/c');h.images.at(-1).onload();
  h.controller.preview(book);h.tick(300);assert.equal(h.images.at(-1).src,'https://example.com/b');h.images.at(-1).onload();
  assert.equal(h.displayed.at(-1)[0],'https://example.com/b');
  h.tick(5000);assert.equal(h.images.at(-1).src,'https://example.com/c');
  h.controller.cancel();assert.equal(h.timers.size,0);
});
test('failed hover artwork returns to shared pool and stale image loads cannot replace it',()=>{
  const h=harness(),a={id:'a',immersiveBackgroundUrl:'https://example.com/a'},b={id:'b',immersiveBackgroundUrl:'https://example.com/b'};
  h.start({},[a,b]);h.images.at(-1).onload();h.controller.preview(b);h.tick(300);const stale=h.images.at(-1).onload;
  h.controller.resume();h.tick(300);h.images.at(-1).onload();stale();assert.equal(h.displayed.at(-1)[0],'https://example.com/a');
  h.controller.preview(b);h.tick(300);h.images.at(-1).onerror();assert.equal(h.images.at(-1).src,'https://example.com/a');
  h.images.at(-1).onload();h.controller.cancel();assert.equal(h.timers.size,0);
});
test('book series tries representative then member covers as static ambience; empty series uses default',()=>{
  const h=harness();h.start({coverUrl:'/covers/broken.jpg'},[{id:'book',coverUrl:'/covers/book.jpg'}]);
  h.images.at(-1).onerror();assert.equal(h.images.at(-1).src,'/covers/book.jpg');h.images.at(-1).onload();
  assert.deepEqual(h.displayed.at(-1),['/covers/book.jpg','ambient']);assert.equal(h.timers.size,0);
  h.controller.preview({id:'book'});h.tick(300);assert.equal(h.images.length,2);
  h.controller.cancel();h.start({},[]);assert.deepEqual(h.displayed.at(-1),[null,'default']);h.controller.cancel();
});
