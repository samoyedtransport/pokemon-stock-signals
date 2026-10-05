import json
import unittest
from unittest.mock import MagicMock
from major_retailers import parse_direct_ld,parse_bestbuy,bestbuy_candidates,check_bestbuy_catalogue
from pokemon_center_browser import browser_observation

EB='https://www.ebgames.ca/shop/795430-pokemon-110183'
PC='https://www.pokemoncenter.com/en-ca/product/10-10451-115/pokemon-tcg-30th-celebration-booster-bundle-6-packs'
BB='https://www.bestbuy.ca/en-ca/product/pokemon/19843199'

def ld(url=EB,sku='795430',availability='InStock',currency='CAD',name='Pokemon Booster Bundle'):
    node={'@type':'Product','sku':sku,'name':name,'url':url,'offers':{'url':url,'price':49.99,'priceCurrency':currency,'availability':'https://schema.org/'+availability,'seller':{'name':'Pokémon Center'},'itemCondition':'https://schema.org/NewCondition'}}
    return '<div>New: '+sku+'</div><script type="application/ld+json">'+json.dumps(node)+'</script>'

def bb(**changes):
    product={'sku':'19843199','isMarketplace':False,'seller':None,'grade':'Brand New','isPreorderable':False,'priceWithoutEhf':49.99}
    product.update(changes)
    return {'intl':{'locale':'en-CA'},'product':{'product':product,'isAvailabilityError':False,'isAvailabilityLoading':False,'availability':{'sku':'19843199','shipping':{'purchasable':True,'status':'InStockOnlineOnly'}}}}

def bb_page(data):return '<div data-testid="sold-by-best-buy"></div><script>window.__INITIAL_STATE__ = '+json.dumps(data)+';</script>'

class RetailerAdapterTests(unittest.TestCase):
    def test_eb_canadian_new_offer(self):self.assertEqual(parse_direct_ld(ld(),'ebgames_ca',EB),('in_stock',49.99))
    def test_eb_table_condition_and_canonical_category(self):
        page=ld(EB.replace('/shop/','/shop/trading-cards-pokemon-204/')).replace('New: 795430','')+'<tr><td><span>Condition</span></td><td><span>New</span></td></tr>'
        self.assertEqual(parse_direct_ld(page,'ebgames_ca',EB),('in_stock',49.99))
    def test_eb_out_of_stock(self):self.assertEqual(parse_direct_ld(ld(availability='OutOfStock'),'ebgames_ca',EB),('out_of_stock',49.99))
    def test_eb_rejects_us_wrong_sku_used_and_preorder(self):
        for page in [ld(currency='USD'),ld(sku='123'),ld(name='Pokemon Used Booster Bundle'),ld(availability='PreOrder'),ld().replace('New:','Used:')]:self.assertEqual(parse_direct_ld(page,'ebgames_ca',EB),('unknown',None))
    def test_pc_canadian_identity_condition_and_seller(self):
        page=ld(PC,'10-10451-115',availability='OutOfStock')
        self.assertEqual(parse_direct_ld(page,'pokemon_center_ca',PC),('out_of_stock',49.99))
        for wrong in [page.replace('CAD','USD'),page.replace('NewCondition','UsedCondition'),page.replace('Pok\\u00e9mon Center','Other'),page.replace('/en-ca/','/')]:self.assertEqual(parse_direct_ld(wrong,'pokemon_center_ca',PC),('unknown',None))
    def test_block_is_never_stock(self):self.assertEqual(parse_direct_ld('Pardon Our Interruption Add to cart','pokemon_center_ca',PC),('unknown',None))
    def test_bb_first_party_shipping(self):self.assertEqual(parse_bestbuy(bb_page(bb()),BB),('in_stock',49.99))
    def test_bb_marketplace_and_unknown_seller_rejected(self):
        for data in [bb(isMarketplace=True),bb(isMarketplace=None),bb(seller={'name':'Other'}),bb(grade='Open Box'),bb(isPreorderable=True)]:self.assertEqual(parse_bestbuy(bb_page(data),BB),('unknown',None))
    def test_bb_wrong_country_and_sku(self):
        data=bb();data['intl']['locale']='en-US';self.assertEqual(parse_bestbuy(bb_page(data),BB),('unknown',None))
        data=bb();data['product']['availability']['sku']='1';self.assertEqual(parse_bestbuy(bb_page(data),BB),('unknown',None))
    def test_bb_pickup_not_shipping_and_loading(self):
        data=bb();data['product']['availability']['shipping']={'purchasable':False,'status':'InStock'}
        self.assertEqual(parse_bestbuy(bb_page(data),BB),('unknown',None))
        data=bb();data['product']['isAvailabilityLoading']=True;self.assertEqual(parse_bestbuy(bb_page(data),BB),('unknown',None))
    def test_bb_confirmed_soldout(self):
        data=bb();data['product']['availability']['shipping']={'purchasable':False,'status':'OutOfStock'}
        self.assertEqual(parse_bestbuy(bb_page(data),BB),('out_of_stock',49.99))
    def test_bb_candidate_anniversary_and_marketplace_filter(self):
        candidate={'name':'Pokemon 30th Celebration Elite Trainer Box','sku':'123','seoName':'pokemon-30th-etb','isMarketplace':False,'seller':None}
        data={'intl':{'locale':'en-CA'},'search':{'searchResult':{'products':[candidate,{**candidate,'isMarketplace':True}], 'totalPages':1}}}
        ps,pages=bestbuy_candidates(data);self.assertEqual(len(ps),1);self.assertEqual(ps[0]['max_price'],90)
    def test_bb_zero_firstparty_matches_is_healthy(self):
        data={'intl':{'locale':'en-CA'},'search':{'searchResult':{'products':[], 'totalPages':0}}}
        ps,health=check_bestbuy_catalogue(lambda *a:bb_page(data),lambda p:self.fail('no product request expected'))
        self.assertEqual(ps,[]);self.assertTrue(health[0]['ok'])
    def test_pc_available_requires_enabled_product_button(self):
        page=MagicMock();page.url=PC;page.content.return_value=ld(PC,'10-10451-115')
        page.locator.return_value.count.return_value=1
        button=page.locator.return_value.first;button.is_enabled.return_value=False;button.is_visible.return_value=True;button.inner_text.return_value='Add to cart'
        product={'title':'30th','url':PC,'max_price':50}
        self.assertEqual(browser_observation(page,product)['stock'],'unknown')
        button.is_enabled.return_value=True
        self.assertEqual(browser_observation(page,product)['stock'],'in_stock')

if __name__=='__main__':unittest.main()
