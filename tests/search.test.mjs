import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesSearch, normalizeSearch, productMatches, quantitySearch } from '../static/search.js';

test('Brazilian accents, reordered words, punctuation and telephone formatting',()=>{
  assert.equal(normalizeSearch('  AÇAÍ — açúcar!  '),'acai acucar');
  assert(matchesSearch('casa burger',['Burger da casa']));
  assert(matchesSearch('joao 19999990000',['João da Silva','(19) 99999-0000']));
  assert(matchesSearch('#1045',['Cliente',1045]));
  assert(!matchesSearch('acai banana',['Açaí com morango']));
  assert(!matchesSearch('não existe',['Café expresso']));
  assert(matchesSearch('',[null,undefined,'Café']));
});
test('catalog category and description, with exact explicit references',()=>{
  const p={id:12,name:'Açaí',description:'Com banana',category_id:4};
  assert(productMatches(p,'banana acai'));
  assert(productMatches(p,'sobremesa',[{id:4,name:'Sobremesas'}]));
  assert(productMatches(p,'#12'));
  assert(!productMatches(p,'#1'));
  assert(!productMatches(p,'12'));
});
test('quantity shortcut has bounded integer quantities; it never adds a product',()=>{
  assert.deepEqual(quantitySearch('3* cafe'),{query:'cafe',quantity:3,error:''});
  assert.equal(quantitySearch('cafe').quantity,1);
  assert(quantitySearch('0* cafe').error);
  assert(quantitySearch('51* cafe').error);
  assert(quantitySearch('999999999999999999999* cafe').error);
  assert.equal(quantitySearch('2.5* cafe').quantity,1);
});
