const baseApi = "https://api.dexscreener.com/latest/dex/pairs"

export async function getPair(chainId, PairAdressId){
   const address = `${baseApi}/${chainId}/${PairAdressId}`
   const res = await fetch(address)

   if(!res.ok){
    console.log("this is an error")
   }
   
   return (res.json())
   
   

}

export async function getInfo(chainId, pairId){
    //const chainId = "solana"
    //const pairId = "EUabMnyQkcomQDcknKyFpFPdKGfFyGe361b9w2Nz5wCV"

    const data = await getPair(chainId,pairId)
    //console.log(data)
    const dataOutput = [
        {chainId : data.pair.chainId},
        {dexId : data.pair.dexId},
        {url : data.pair.url},
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
    return(dataOutput)

}

getInfo("solana","EUabMnyQkcomQDcknKyFpFPdKGfFyGe361b9w2Nz5wCV")
