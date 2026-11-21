const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ctx = vm.createContext({});
for (const file of ['presentation-core.js','exhibit-cards.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',file),'utf8'),ctx);
}
const {core,cards} = ctx.ArchiveV2;
const filters = {group:'series',cat:'all',status:'all',time:'all',q:''};
const series = [{id:'s',name:'系列',memberCount:2,completedCount:1,avgRating:8,
  members:[{id:'a',title:'成员一',coverUrl:'/one.jpg'},{id:'b',title:'成员二',coverUrl:'/two.jpg'}]}];

test('exhibition grouping preserves first matching member order and never changes input',()=>{
  const works=[{id:'b',primarySeriesId:'s'},{id:'c'},{id:'a',primarySeriesId:'s'}];
  const before=JSON.stringify([works,series]);
  assert.deepEqual(Array.from(core.exhibitionItems(works,series,filters),item=>item.entity.id),['s','c']);
  assert.deepEqual(Array.from(core.exhibitionItems(works,series,{...filters,group:'flat'}),item=>item.entity.id),['b','c','a']);
  assert.equal(JSON.stringify([works,series]),before);
});

test('filtered series retains full aggregates and reports matching members separately',()=>{
  const [item]=core.exhibitionItems([{id:'a',primarySeriesId:'s'}],series,{...filters,q:'成员一'});
  assert.equal(item.matchedCount,1);
  const html=cards.seriesCard(item.entity,item);
  assert.match(html,/共 2 部 · 当前匹配 1 部/);
  assert.match(html,/全系列已完成 1 \/ 2/);
  assert.match(html,/成员均分 8.0/);
  assert.doesNotMatch(html,/系列评分/);
});

test('empty series are visible only in unfiltered grouped view; unknown primary stays a work',()=>{
  const collections=[...series,{id:'empty',name:'空',memberCount:0}];
  assert.equal(core.exhibitionItems([],collections,filters).length,1);
  for (const changed of [{group:'flat'},{cat:'book'},{status:'active'},{time:'y'},{q:'x'}]) {
    assert.equal(core.exhibitionItems([],collections,{...filters,...changed}).length,0);
  }
  assert.equal(core.exhibitionItems([{id:'x',primarySeriesId:'deleted'}],collections,filters)[0].type,'work');
});

test('work labels follow the cover; text, ids and image attributes are escaped',()=>{
  const html=cards.workCard({id:'" onclick="bad',title:'<作品>',coverUrl:'/x?y="',rating:0,status:'completed'},
    {category:'图书',status:'已读完',series:'<系列>'});
  assert.match(html,/个人评分 0.0/);
  assert.match(html,/&lt;作品&gt;/);
  assert.match(html,/data-id="&quot; onclick=&quot;bad"/);
  assert.match(html,/<\/div>\s*<div class="exhibit-label">/);
  assert.doesNotMatch(html,/<button|data-delete|data-edit/);
});

test('series representative has a finite member fallback and at most three covers',()=>{
  const html=cards.seriesCard({...series[0],coverUrl:'/representative.jpg'});
  assert.match(html,/src="\/representative.jpg"/);
  assert.match(html,/data-cover-fallbacks="\[&quot;\/one.jpg&quot;,&quot;\/two.jpg&quot;\]"/);
  assert.equal((html.match(/class="exhibit-series-cover"/g)||[]).length,3);
  assert.match(cards.seriesCard({id:'empty',name:'空',memberCount:0,members:[]}),/暂无成员，进入详情添加/);
  const partial=cards.seriesCard({...series[0],members:[{id:'no-cover'},...series[0].members]});
  assert.match(partial,/<img src="\/one.jpg"/);
  assert.equal((partial.match(/class="exhibit-series-cover"/g)||[]).length,2);
});

test('image failure advances once and then reveals placeholder; delegation binds once',()=>{
  const listeners=[];
  const wall={contains:()=>true,querySelectorAll:()=>[],addEventListener:(...args)=>listeners.push(args)};
  let opened='';
  cards.bindWall(wall,{openWork:id=>opened=id,openSeries:id=>opened=id});
  cards.bindWall(wall,{openWork:id=>opened=id,openSeries:id=>opened=id});
  assert.equal(listeners.length,1);
  const image={matches:()=>true,dataset:{coverFallbacks:'["/next.jpg"]'},removeAttribute:name=>{image.removed=name}};
  listeners[0][1]({target:image});assert.equal(image.src,'/next.jpg');
  listeners[0][1]({target:image});assert.equal(image.hidden,true);assert.equal(image.removed,'src');
  const card={dataset:{id:'w'}};card.closest=()=>card;
  let prevented=false;
  wall.onkeydown({target:card,type:'keydown',key:' ',preventDefault:()=>prevented=true});
  assert.equal(opened,'w');assert.equal(prevented,true);
  opened='';wall.onkeydown({target:card,type:'keydown',key:'ArrowRight',preventDefault(){}});
  assert.equal(opened,'');
});
