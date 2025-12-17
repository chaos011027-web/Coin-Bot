import {getInfo} from "./dexScreener.js"

//const exampleData = await getInfo("solana","EUabMnyQkcomQDcknKyFpFPdKGfFyGe361b9w2Nz5wCV")

export const formatText = (data)=>{
   
   let text = 
   `
        🔗区块链： ${data[0].chainId} 
        📌代币地址：${data[3].PairAddress}
        💰当前价格：$${data[4].PriceUsd} url : ${data[2].url}
        ━━━━━━━━━━━━━━━━━━
        📊 近 5 分钟交易情况                                 近5分钟价格变动
        🟢 买入 (Buys)： ${data[9].txn.buys}         ${data[7].PriceChange}
        🔴 卖出 (Sells)： ${data[9].txn.sells}
        ━━━━━━━━━━━━━━━━━━
`;

    //console.log(text)
    return (text)
}

