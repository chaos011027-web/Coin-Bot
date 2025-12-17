import axios from "axios"
import { getInfo } from "./dexScreener.js";
import {formatText} from "./textFormat.js"
import { format } from "path";


const server = axios.create({
    timeout : 5000,
    headers :{
        "Content-Type" : "application/json"
    }
})


const botToken = "8397587329:AAGn34BYz2chUKSCJ_AT1ihum1mWu1i49nQ"
const TELEGRAM_API = `https://api.telegram.org/bot${botToken}`;
const chatId = "7705580005"


// set up webhook for incoming updates
server.post(`${TELEGRAM_API}/setWebhook`,{
    url : "https://nonprobable-nylah-finickily.ngrok-free.dev/telegram/webhook"
})

// set up the basic commands for bot 
server.post(`${TELEGRAM_API}/setMyCommands`,{
    commands : [
      {command : "/start", description : "Start this bot/开始机器人"},
      {command : "/search_pair", description : "search for pair information by pairID/输入代币地址并开始搜索"},
      {command : "/analysis_ai",description : "Analyze by AI/开启AI分析"}

    ]
})

// how to handle command/update
export async function handleNewPost(newPost){
    
    if(newPost.startsWith("PairID:")){
        const pairId = newPost.split(":")[1]
        console.log(pairId)
        const data = await getInfo("solana",pairId)
        const formatData = formatText(data)
        sendMessage(formatData)
    }
    
    else {switch(newPost){
        case "/start" :
            sendMessage("Let's start with the bot")
            break;

        case "/search_pair" :
            sendMessage("please input pair address starts with PairID:")
            break;
            

        default:
            sendMessage("unknown command 🤔")
    }}

    
}

const exampleText = await getInfo("solana","EUabMnyQkcomQDcknKyFpFPdKGfFyGe361b9w2Nz5wCV")

// function to send message to bot
   async function sendMessage(messageText){
       try {
         const res = server.post(`${TELEGRAM_API}/sendMessage`,
            {
                chat_id : chatId,
                text : messageText,
                disable_web_page_preview : true
            }
         )
         console.log(res.data)
       } catch (error) {
         console.error(error , "ups, something goes wrong")
       }
   }

   

  

