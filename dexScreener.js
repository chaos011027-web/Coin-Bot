const baseApi = "https://api.dexscreener.com/latest/dex/pairs"

async function getPair(chainId, PairAdressId){
   const address = `${baseApi}/${chainId}/${PairAdressId}`
   const res = await fetch(address)

   if(!res.ok){
    console.log("this is an error")
   }
   console.log("success")
   return (res.json())

}

async function getInfo(){
    const chainId = "solana"
    const pairId = "J3s2eaBdxaTEJd9NgHAvsRv88PuGSQWmrggyWxoEL587"

    const data = await getPair(chainId,pairId)
    const dataOutput = [
        {PairAddress : data.pair.pairAddress},
        {PriceUsd : data.pair.priceUsd},
        {mcapUsd : data.pair.marketCap},
        {liquidity : data.pair.liquidity},
        {PriceChange : data.pair.priceChange},
        {volume : data.pair.volume},
        {txn :data.pair.txns.m5 },// { txn: { m5: [Object], h1: [Object], h6: [Object], h24: [Object] } },
        {boosts :data.pair.boosts }
        
    ]

    console.log(dataOutput)

}

getInfo()
