const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
const start=source.indexOf('  function projectionResultSelectionText('),end=source.indexOf('  function projectionResultNumber(',start);
for(const locale of ['sk','cz','en']){
 const context={lcopy:(en,sk,cz)=>({en,sk,cz})[locale]};vm.createContext(context);vm.runInContext(source.slice(start,end),context);
 const render=context.projectionResultSelectionText,unit=locale==='sk'?'esá':locale==='cz'?'esa':'aces';
 const base={market:'aces',projection:10.8,market_line:6.5};
 const duplicate=render({...base,selection:'Hubert Hurkacz Over 6.5 Aces · Over 6.5 Aces'});
 assert.equal((duplicate.match(/Over 6\.5/gi)||[]).length,1);
 assert.match(duplicate,/Hubert Hurkacz/);
 assert.match(duplicate,new RegExp(unit,'i'));
 assert.match(render({...base,projection:4,selection:'Hurkacz Over 6.5 Aces'}),/Over 6\.5/); // explicit published side wins
 assert.match(render({...base,selection:'Hurkacz',projection_direction:'under'}),/Under 6\.5/);
 assert.match(render({...base,selection:'Hurkacz',ou_side:'under',projection_direction:'over',price_contract:'player_total_ou'}),/Under 6\.5/);
 assert.doesNotMatch(render({market:'aces',selection:'Hurkacz',market_line:null,projection:8}),/0\.0/);
 assert.equal(render({...base,selection:'Over 6.5 Aces · Over 7.5 Aces'}).match(/Over/g).length,2); // do not collapse different contracts
}

const actualStart=source.indexOf('  function projectionResultUnitLabel(');
const actualEnd=source.indexOf('  function resultCategoryLabel(',actualStart);
assert(actualStart>=0 && actualEnd>actualStart);
for(const locale of ['sk','cz','en']){
 const context={lcopy:(en,sk,cz)=>({en,sk,cz})[locale]};
 vm.createContext(context);
 vm.runInContext(source.slice(actualStart,actualEnd),context);
 const text=context.projectionResultActualText({
   market:'aces',projection_metric:'aces',price_contract:'player_total_ou',ou_side:'over',market_line:10.5,
   result:{actual_count:9,opponent_actual_count:5},
 });
 assert.match(text,/10\.5/);
 assert.match(text,/9 /);
 assert.doesNotMatch(text,/súper|soupeř|opponent/i);
}
console.log('Projection labels: SK/CZ/EN, duplicate contracts, explicit side and missing line passed.');
