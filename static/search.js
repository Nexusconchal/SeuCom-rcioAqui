// One search rule for the storefront and the merchant tools. No data leaves the page.
export function normalizeSearch(value){
  return String(value??'').normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase('pt-BR').replace(/[^\p{L}\p{N}]+/gu,' ').trim().replace(/\s+/g,' ');
}
export function matchesSearch(query,fields){
  const tokens=normalizeSearch(query).split(' ').filter(Boolean);
  const values=fields.filter(v=>v!==null&&v!==undefined).map(normalizeSearch);
  const text=values.join(' ');
  return tokens.every(token=>text.includes(token)||(/^\d+$/.test(token)&&values.some(v=>v.replace(/\s/g,'').includes(token))));
}
export function productMatches(product,query,categories=[]){
  // #123 is an exact internal product reference; a bare number is regular text.
  const reference=String(query).match(/^\s*#(\d+)\s*$/);
  if(reference)return product.id===Number(reference[1]);
  return matchesSearch(query,[product.name,product.description,categories.find(c=>c.id===product.category_id)?.name]);
}
export function quantitySearch(value){
  const match=String(value).match(/^\s*(\d+)\s*\*\s*(.*)$/s);
  if(!match)return {query:value,quantity:1,error:''};
  const quantity=Number(match[1]);
  return {query:match[2],quantity,error:quantity<1||quantity>50?'Use uma quantidade de 1 a 50 antes do asterisco.':''};
}
