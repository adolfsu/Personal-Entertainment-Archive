const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ctx = vm.createContext({URL,setTimeout,clearTimeout});
for (const file of ['immersive-background.js','background-editor.js','series-immersive.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',file),'utf8'),ctx);
}
const {backgrounds,backgroundEditor,seriesImmersive} = ctx.ArchiveV2;

test('local background paths are accepted without admitting traversal or executable schemes',()=>{
  assert.equal(backgrounds.safeBackgroundUrl('covers/background_a.png'),'/covers/background_a.png');
  assert.equal(backgrounds.safeBackgroundUrl('/covers/background_a.webp'),'/covers/background_a.webp');
  for(const url of ['/covers/../a.png','/covers/%2e%2e.png','//evil.com/a.png','javascript:alert(1)','/covers/a.svg']) {
    assert.equal(backgrounds.safeBackgroundUrl(url),'');
  }
  assert.equal(backgrounds.safeRemoteUrl('/covers/background_a.png'),'');
});

test('series pools retain local originals and legacy remote images in their saved order',()=>{
  const series={immersiveBackgroundUrls:['/covers/series.png'],members:[{id:'a'}]};
  const works=[{id:'a',immersiveBackgroundUrls:['/covers/second.png','https://example.com/old.jpg','/covers/series.png']}];
  assert.deepEqual(Array.from(seriesImmersive.pool(series,works)),['/covers/series.png','/covers/second.png','https://example.com/old.jpg']);
});

test('background playback uses a local original as a dedicated background',()=>{
  const displayed=[], images=[];
  const loader=backgrounds.createLoader({schedule:()=>1,unschedule:()=>{},imageFactory:()=>{
    const image={naturalWidth:1920,naturalHeight:1080,set src(value){this.url=value;images.push(this)},removeAttribute(){}};
    return image;
  }});
  loader.load({immersiveBackgroundUrls:['/covers/background_a.png'],coverUrl:'/covers/poster.jpg'},(image,kind)=>displayed.push([image?.url,kind]));
  images[0].onload();
  assert.deepEqual(displayed.at(-1),['/covers/background_a.png','dedicated']);
});

test('reordering produces saved playback order without changing the original draft',()=>{
  const source=['/covers/a.png','/covers/b.png','https://example.com/c'];
  assert.deepEqual(Array.from(backgroundEditor.reorder(source,2,0)),[source[2],source[0],source[1]]);
  assert.deepEqual(source,['/covers/a.png','/covers/b.png','https://example.com/c']);
  assert.deepEqual(Array.from(backgroundEditor.reorder(source,0,99)),source);
});

test('form reads reject an unfinished link and preserve the complete local order',()=>{
  const fields={'[data-background-link]':{value:''},'[data-background-value]':{value:'/covers/b.png\n/covers/a.png'}};
  const box={querySelector:selector=>fields[selector]},root={querySelector:()=>box};
  assert.deepEqual(Array.from(backgroundEditor.read(root,'test')),['/covers/b.png','/covers/a.png']);
  fields['[data-background-link]'].value='https://example.com/pending.png';
  assert.throws(()=>backgroundEditor.read(root,'test'),/未添加/);
});
