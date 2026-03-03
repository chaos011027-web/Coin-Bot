
import {handleNewPost} from "./teleBot.js"
import express from "express"
const app = express()
const port = 3000

app.use(express.json())

//set up local server
app.get("/",(req,res)=>{
    res.send("hello world")
})

app.get("/telegram/webhook", (req,res)=>{
    res.send("wow hahha this is good")
})

app.post("/telegram/webhook", (req,res)=>{
    
    const update = req.body

    res.sendStatus(200)
    console.log("--new post--")
    console.log(update.message.text)
    handleNewPost(update.message.text)
    



})

app.listen(port,()=>{
    console.log("listening ")
})