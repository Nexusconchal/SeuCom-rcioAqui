import { api } from './ui.js';
let slug='',token='',chain=Promise.resolve();
export function startShopping(value){
  slug=value;try{token=sessionStorage.getItem('sca.shopping.'+slug)||'';}catch{}
  return shoppingEvent('visit');
}
export function shoppingToken(){return token;}
export function shoppingEvent(event,items=[],contact={}){
  const body={event,items,...contact};
  chain=chain.catch(()=>{}).then(async()=>{
    try{const result=await api('/api/store/'+encodeURIComponent(slug)+'/shopping',{method:'POST',body:JSON.stringify({...body,token})});token=result.token;try{sessionStorage.setItem('sca.shopping.'+slug,token);}catch{}}
    catch(e){if(e.status===404){token='';try{sessionStorage.removeItem('sca.shopping.'+slug);}catch{}}}
  });
  return chain;
}
export function finishShopping(){token='';try{sessionStorage.removeItem('sca.shopping.'+slug);}catch{}}
