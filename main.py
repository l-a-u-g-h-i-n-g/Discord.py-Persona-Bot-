import discord
import os
import httpx
import json
import datetime
import asyncio
import re
import configparser

CONFIG_FILE = 'config.txt'

def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Configuration file '{CONFIG_FILE}' not found. Please create it.")
        
    config.read(CONFIG_FILE)

    settings = {}
    
    settings['DISCORD_TOKEN'] = os.getenv("DISCORD_TOKEN") or config.get('GLOBAL', 'DISCORD_TOKEN', fallback=None)
    settings['GEMINI_API_KEY'] = os.getenv("GEMINI_API_KEY") or config.get('GLOBAL', 'GEMINI_API_KEY', fallback=None)
    settings['GEMINI_API_URL'] = config.get('GLOBAL', 'GEMINI_API_URL')
    settings['MAX_HISTORY_MESSAGES'] = config.getint('GLOBAL', 'MAX_HISTORY_MESSAGES')
    settings['MEMORIES_FILE'] = config.get('GLOBAL', 'MEMORIES_FILE')
    settings['BOT_MEMORIES_FILE'] = config.get('GLOBAL', 'BOT_MEMORIES_FILE')
    settings['MEMORY_STORE_PREFIX'] = config.get('GLOBAL', 'MEMORY_STORE_PREFIX')
    settings['PREFIX_GROK'] = config.get('GLOBAL', 'PREFIX_GROK')
    settings['PREFIX_G'] = config.get('GLOBAL', 'PREFIX_G')

    settings['PERSONA'] = config.get('INSTRUCTIONS', 'PERSONA')
    settings['USER_MEMORY_EXTRACT'] = config.get('INSTRUCTIONS', 'USER_MEMORY_EXTRACT')
    settings['BOT_MEMORY_EXTRACT'] = config.get('INSTRUCTIONS', 'BOT_MEMORY_EXTRACT')

    return settings

try:
    CONFIG = load_config()
except Exception as e:
    print(f"Failed to load configuration: {e}")
    exit()

DISCORD_TOKEN = CONFIG['DISCORD_TOKEN']
GEMINI_API_KEY = CONFIG['GEMINI_API_KEY']
GEMINI_API_URL = CONFIG['GEMINI_API_URL']
MAX_HISTORY_MESSAGES = CONFIG['MAX_HISTORY_MESSAGES']
MEMORIES_FILE = CONFIG['MEMORIES_FILE']
BOT_MEMORIES_FILE = CONFIG['BOT_MEMORIES_FILE']
MEMORY_STORE_PREFIX = CONFIG['MEMORY_STORE_PREFIX']
PREFIX_GROK = CONFIG['PREFIX_GROK']
PREFIX_G = CONFIG['PREFIX_G']

class MemoryManager:
    def __init__(self, user_file, bot_file):
        self.user_file = user_file
        self.bot_file = bot_file
        self.user_memories = {}
        self.bot_memories = []

    def load_all(self):
        self._load_user_memories()
        self._load_bot_memories()

    def _load_user_memories(self):
        try:
            if not os.path.exists(self.user_file) or os.stat(self.user_file).st_size == 0:
                self.user_memories = {}
                return
            with open(self.user_file, 'r', encoding='utf-8') as f:
                self.user_memories = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.user_memories = {}

    def _save_user_memories(self):
        try:
            with open(self.user_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_memories, f, indent=4)
        except IOError as e:
            print(f"Error saving user memories to {self.user_file}: {e}")

    def _load_bot_memories(self):
        try:
            if not os.path.exists(self.bot_file) or os.stat(self.bot_file).st_size == 0:
                self.bot_memories = []
                return
            with open(self.bot_file, 'r', encoding='utf-8') as f:
                self.bot_memories = json.load(f)
        except (json.JSONDecodeError, IOError):
            self.bot_memories = []

    def _save_bot_memories(self):
        try:
            with open(self.bot_file, 'w', encoding='utf-8') as f:
                json.dump(self.bot_memories, f, indent=4)
        except IOError as e:
            print(f"Error saving bot memories to {self.bot_file}: {e}")

    async def add_user_memory(self, user_id, user_display_name, memory_content):
        if user_id not in self.user_memories:
            self.user_memories[user_id] = []
        
        memory_content = re.sub(r'^\* |^- |^• ', '', memory_content).strip()

        new_memory = {
            "content": memory_content,
            "stored_by_user_name": user_display_name, 
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.user_memories[user_id].append(new_memory)
        self._save_user_memories()
        print(f"Stored user memory for {user_display_name} ({user_id}): '{memory_content}'")

    async def add_bot_memory(self, memory_content):
        memory_content = re.sub(r'^\* |^- |^• ', '', memory_content).strip()

        new_memory = {
            "content": memory_content,
            "timestamp": datetime.datetime.now().isoformat()
        }
        self.bot_memories.append(new_memory)
        self._save_bot_memories()
        print(f"Stored general bot memory: '{memory_content}'")

    async def _call_gemini_memory_extractor(self, instruction, user_message, bot_response):
        extraction_prompt = (
            f"{instruction}\n\n"
            f"**CONVERSATION TURN:**\n"
            f"User's message: {user_message}\n"
            f"Grok's response: {bot_response}\n\n"
            f"**EXTRACTED MEMORIES (or 'NONE'):**"
        )

        payload_contents = [
            {"role": "user", "parts": [{"text": extraction_prompt}]}
        ]

        payload = {"contents": payload_contents}

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }

        try:
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(GEMINI_API_URL, headers=headers, json=payload, timeout=10.0) 
                response.raise_for_status()
                gemini_response_data = response.json()

                if gemini_response_data and gemini_response_data.get('candidates'):
                    extracted_text = gemini_response_data['candidates'][0]['content']['parts'][0]['text'].strip()
                    return extracted_text
                else:
                    return "NONE"

        except Exception as e:
            print(f"Error during memory extraction: {e}")
            return None

    async def extract_and_store_user_memories(self, user_id, user_display_name, user_message_content, bot_response_content):
        extracted_text = await self._call_gemini_memory_extractor(
            CONFIG['USER_MEMORY_EXTRACT'], user_message_content, bot_response_content
        )

        if extracted_text and extracted_text.lower() != 'none':
            new_memories_list = [
                m.strip() for m in extracted_text.split('\n')
                if m.strip() and m.strip().lower() != 'none'
            ]
            
            for mem_content in new_memories_list:
                await self.add_user_memory(user_id, user_display_name, mem_content)

    async def extract_and_store_bot_memories(self, user_message_content, bot_response_content):
        extracted_text = await self._call_gemini_memory_extractor(
            CONFIG['BOT_MEMORY_EXTRACT'], user_message_content, bot_response_content
        )

        if extracted_text and extracted_text.lower() != 'none':
            new_memories_list = [
                m.strip() for m in extracted_text.split('\n')
                if m.strip() and m.strip().lower() != 'none'
            ]
            
            for mem_content in new_memories_list:
                await self.add_bot_memory(mem_content)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
conversation_histories = {}
memory_manager = MemoryManager(MEMORIES_FILE, BOT_MEMORIES_FILE)

@client.event
async def on_ready():
    memory_manager.load_all()
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    prompt_text = ""
    user_id = str(message.author.id)
    user_display_name = message.author.display_name
    conversation_key = user_id

    if message.content.startswith(MEMORY_STORE_PREFIX):
        memory_content = message.content[len(MEMORY_STORE_PREFIX):].strip()
        if memory_content:
            await memory_manager.add_user_memory(user_id, user_display_name, memory_content)
            await message.add_reaction('✅')
        else:
            await message.channel.send(f"What should I remember? Use `{MEMORY_STORE_PREFIX}<your memory here>`.", reference=message)
        return

    if client.user in message.mentions:
        prompt_text = message.content.replace(f'<@{client.user.id}>', '').strip()
    else:
        user_message_content = message.content.strip()

        if user_message_content.startswith(PREFIX_GROK):
            prompt_text = user_message_content[len(PREFIX_GROK):].strip()
        elif user_message_content.startswith(PREFIX_G):
            prompt_text = user_message_content[len(PREFIX_G):].strip()
        else:
            return

    if not prompt_text: 
        await message.channel.send(f"Hey, you need to ask me something! Try `{PREFIX_GROK}<your question>`, `{PREFIX_G}<your question>`, or mention me directly `@grok <your question>`.", reference=message)
        return

    if not GEMINI_API_KEY:
        await message.channel.send("Grok is currently offline. My Gemini API key is missing.", reference=message)
        return

    grok_persona_instruction = CONFIG['PERSONA']

    context_and_memory = ""
    context_and_memory += f"**CURRENT USER DETAILS:**\n- Display Name: {user_display_name}\n- User ID: {user_id}\n\n"

    if memory_manager.bot_memories:
        context_and_memory += "**GROK'S GENERAL MEMORIES/INSIGHTS (FACTS FOR YOU TO USE):**\n"
        for memory_item in memory_manager.bot_memories:
            context_and_memory += f"- {memory_item['content']}\n"
        context_and_memory += "\n"

    if user_id in memory_manager.user_memories and memory_manager.user_memories[user_id]:
        context_and_memory += f"**MEMORIES ABOUT {user_display_name} (USE THESE FACTS WHEN RESPONDING):**\n"
        for memory_item in memory_manager.user_memories[user_id]:
            context_and_memory += f"- {memory_item['content']}\n"
        context_and_memory += "\n"

    if conversation_key not in conversation_histories:
        conversation_histories[conversation_key] = []
        
    conversation_histories[conversation_key].append({"role": "user", "text": prompt_text})
    truncated_history_for_api = conversation_histories[conversation_key][:-1][-MAX_HISTORY_MESSAGES:]

    full_context_part = f"{grok_persona_instruction}\n\n{context_and_memory}"
    
    payload_contents = [
        {"role": "user", "parts": [{"text": full_context_part}]}
    ]

    for history_item in truncated_history_for_api:
        role = "model" if history_item["role"] == "model" else "user"
        payload_contents.append({"role": role, "parts": [{"text": history_item["text"]}]})

    payload_contents.append({"role": "user", "parts": [{"text": prompt_text}]})
    payload = {"contents": payload_contents}

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    grok_response_text = ""

    try:
        async with message.channel.typing():
            async with httpx.AsyncClient() as http_client:
                response = await http_client.post(GEMINI_API_URL, headers=headers, json=payload, timeout=30.0)
                response.raise_for_status()
                gemini_raw_response_data = response.json()

                if gemini_raw_response_data and gemini_raw_response_data.get('candidates'):
                    grok_response_text = gemini_raw_response_data['candidates'][0]['content']['parts'][0]['text']
                    conversation_histories[conversation_key].append({"role": "model", "text": grok_response_text})
                    await message.reply(grok_response_text, mention_author=False)
                else:
                    await message.reply("Grok couldn't articulate a response.", mention_author=False)

    except Exception as e:
        error_message = f"Grok failed to connect to the AI network: {e}"
        print(f"Error: {e}")
        await message.reply(error_message, mention_author=False)
    finally:
        if grok_response_text:
            asyncio.create_task(memory_manager.extract_and_store_user_memories(user_id, user_display_name, prompt_text, grok_response_text))
            asyncio.create_task(memory_manager.extract_and_store_bot_memories(prompt_text, grok_response_text))

if DISCORD_TOKEN and GEMINI_API_KEY:
    client.run(DISCORD_TOKEN)
else:
    print("Error: DISCORD_TOKEN or GEMINI_API_KEY not found. Ensure they are set as environment variables or correctly configured in config.txt.")
